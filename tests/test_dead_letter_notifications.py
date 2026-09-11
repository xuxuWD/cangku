from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_dead_letter_store
from app.dead_letters import DeadLetter, DeadLetterStore, NotifyingDeadLetterStore
from app.events import EventEnvelope, InMemoryEventBus
from app.notifications import DeadLetterNotifier, WebhookNotificationChannel
from app.settings import Settings


def event(*, event_id: str = "event-1", payload: dict[str, object] | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        tenant_id="t-1",
        aggregate_type="task",
        aggregate_id="task-1",
        version=1,
        sequence=1,
        dedupe_key="task-1:created:1",
        action="task.created",
        occurred_at=datetime(2026, 9, 11, tzinfo=UTC),
        payload={"status": "queued"} if payload is None else payload,
    )


# ---------------------------------------------------------------------------
# 迁移 015
# ---------------------------------------------------------------------------


def test_migration_015_adds_notified_at_without_index() -> None:
    migration = Path("migrations/015_dead_letter_notifications.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE workbench_dead_letters" in migration
    assert "ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ" in migration
    assert "INDEX" not in migration


# ---------------------------------------------------------------------------
# 通知渠道
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise RuntimeError(f"http-{self.status_code}")


class RecordingTransport:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse()
        self.calls: list[tuple[str, dict[str, object], float]] = []

    def __call__(self, url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        self.calls.append((url, json, timeout))
        return self.response


def test_webhook_channel_posts_json_with_configured_url_and_timeout() -> None:
    transport = RecordingTransport()
    channel = WebhookNotificationChannel(
        "https://hooks.example/dead-letters", timeout_seconds=7.5, transport=transport
    )

    channel.send({"kind": "dead_letter"})

    url, payload, timeout = transport.calls[0]
    assert url == "https://hooks.example/dead-letters"
    assert payload == {"kind": "dead_letter"}
    assert timeout == 7.5
    assert channel.name == "webhook"


def test_webhook_channel_raises_on_non_2xx() -> None:
    channel = WebhookNotificationChannel(
        "https://hooks.example/dead-letters",
        transport=RecordingTransport(FakeResponse(500)),
    )

    with pytest.raises(RuntimeError, match="http-500"):
        channel.send({"kind": "dead_letter"})


def test_webhook_channel_requires_url() -> None:
    with pytest.raises(ValueError):
        WebhookNotificationChannel("")


# ---------------------------------------------------------------------------
# 脱敏载荷
# ---------------------------------------------------------------------------


def test_notifier_payload_omits_event_payload_and_sanitizes_error() -> None:
    transport = RecordingTransport()
    channel = WebhookNotificationChannel("https://hooks.example/dead-letters", transport=transport)
    notifier = DeadLetterNotifier(channel)
    item = DeadLetter(
        event=event(payload={"secret": "S3CRET-VALUE"}),
        error="connect redis://user:p4ss@redis.internal:6379/0 failed " + "x" * 400,
        attempts=4,
    )

    notifier.notify(item)

    payload = transport.calls[0][1]
    assert payload["kind"] == "dead_letter"
    assert payload["event_id"] == "event-1"
    assert payload["tenant_id"] == "t-1"
    assert payload["action"] == "task.created"
    assert payload["aggregate_type"] == "task"
    assert payload["aggregate_id"] == "task-1"
    assert payload["attempts"] == 4
    assert payload["occurred_at"] == item.event.occurred_at.isoformat()
    assert "payload" not in payload
    assert "S3CRET-VALUE" not in str(payload)
    assert "user:p4ss@" not in payload["error"]
    assert "redis://***@redis.internal:6379/0" in payload["error"]
    assert len(payload["error"]) <= 200
    assert notifier.channel_name == "webhook"


def test_notifier_error_is_truncated_to_200_characters() -> None:
    transport = RecordingTransport()
    notifier = DeadLetterNotifier(
        WebhookNotificationChannel("https://hooks.example/dead-letters", transport=transport)
    )

    notifier.notify(DeadLetter(event=event(), error="e" * 500))

    assert len(transport.calls[0][1]["error"]) == 200


# ---------------------------------------------------------------------------
# NotifyingDeadLetterStore
# ---------------------------------------------------------------------------


class RecordingNotifier:
    name = "webhook"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[DeadLetter] = []

    @property
    def channel_name(self) -> str:
        return self.name

    def notify(self, dead_letter: DeadLetter) -> None:
        self.calls.append(dead_letter)
        if self.fail:
            raise RuntimeError("notification boom")


def build_wrapped(*, fail: bool = False):
    inner = DeadLetterStore(InMemoryEventBus())
    notifier = RecordingNotifier(fail=fail)
    audit_store = InMemoryAuditStore()
    wrapped = NotifyingDeadLetterStore(
        inner=inner, notifier=notifier, audit=AuditService(audit_store)
    )
    return wrapped, notifier, audit_store


def test_notifying_store_notifies_once_and_audits_success() -> None:
    wrapped, notifier, audit_store = build_wrapped()

    item = wrapped.record(event(), "redis unavailable", attempts=3)

    assert item.notified_at is not None
    assert len(notifier.calls) == 1
    record = audit_store.list_recent()[-1]
    assert record.action is AuditAction.DEAD_LETTER_NOTIFIED
    assert record.detail == {"event_id": "event-1", "attempts": 3, "channel": "webhook"}
    assert record.tenant_id == "t-1"

    wrapped.record(event(), "redis unavailable", attempts=4)

    assert len(notifier.calls) == 1


def test_notifying_store_swallows_notification_failure_and_audits() -> None:
    wrapped, notifier, audit_store = build_wrapped(fail=True)

    item = wrapped.record(event(), "redis unavailable", attempts=3)

    assert item.event_id == "event-1"
    assert len(notifier.calls) == 1
    records = audit_store.list_recent()
    assert records[-1].action is AuditAction.DEAD_LETTER_NOTIFICATION_FAILED
    assert records[-1].detail == {"event_id": "event-1", "attempts": 3, "channel": "webhook"}

    wrapped.record(event(), "redis unavailable", attempts=4)

    assert len(notifier.calls) == 1


def test_notifying_store_delegates_list_and_replay() -> None:
    wrapped, _notifier, _audit_store = build_wrapped()
    wrapped.record(event(), "redis unavailable", attempts=3)
    context = type("Ctx", (), {"tenant_id": "t-1", "role": "super_admin", "user_id": "u-1"})()

    assert [item.event_id for item in wrapped.list(context)] == ["event-1"]
    assert wrapped.replay(context, "event-1") == "replayed"


# ---------------------------------------------------------------------------
# bootstrap 装配
# ---------------------------------------------------------------------------


def test_build_dead_letter_store_stays_unwrapped_without_webhook() -> None:
    audit = AuditService(InMemoryAuditStore())
    store = build_dead_letter_store(
        Settings(env="development", storage_backend="memory", dead_letter_webhook_url=""),
        event_bus=InMemoryEventBus(),
        audit=audit,
    )

    assert isinstance(store, DeadLetterStore)
    assert not isinstance(store, NotifyingDeadLetterStore)


def test_build_dead_letter_store_stays_unwrapped_without_audit() -> None:
    store = build_dead_letter_store(
        Settings(
            env="development",
            storage_backend="memory",
            dead_letter_webhook_url="https://hooks.example/dead-letters",
        ),
        event_bus=InMemoryEventBus(),
    )

    assert not isinstance(store, NotifyingDeadLetterStore)


def test_build_dead_letter_store_wraps_when_webhook_and_audit_configured() -> None:
    audit = AuditService(InMemoryAuditStore())
    store = build_dead_letter_store(
        Settings(
            env="development",
            storage_backend="memory",
            dead_letter_webhook_url="https://hooks.example/dead-letters",
            dead_letter_webhook_timeout_seconds=9.0,
        ),
        event_bus=InMemoryEventBus(),
        audit=audit,
    )

    assert isinstance(store, NotifyingDeadLetterStore)
    assert isinstance(store.inner, DeadLetterStore)
    assert isinstance(store.notifier.channel, WebhookNotificationChannel)
    assert store.notifier.channel.url == "https://hooks.example/dead-letters"
    assert store.notifier.channel.timeout_seconds == 9.0


def test_settings_dead_letter_webhook_defaults_and_bounds() -> None:
    defaults = Settings()

    assert defaults.dead_letter_webhook_url == ""
    assert defaults.dead_letter_webhook_timeout_seconds == 5.0

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(dead_letter_webhook_timeout_seconds=0.5)
    with pytest.raises(ValidationError):
        Settings(dead_letter_webhook_timeout_seconds=60)
