from datetime import UTC, datetime

import pytest

from app.dead_letters import DeadLetterStore
from app.domain import PolicyError, UserContext
from app.events import EventEnvelope, InMemoryEventBus


def event() -> EventEnvelope:
    return EventEnvelope(
        event_id="event-1",
        tenant_id="t-1",
        aggregate_type="task",
        aggregate_id="task-1",
        version=1,
        sequence=1,
        dedupe_key="task-1:created:1",
        action="task.created",
        occurred_at=datetime.now(UTC),
        payload={"status": "queued"},
    )


def test_dead_letter_store_is_tenant_scoped_and_replay_is_auditable() -> None:
    bus = InMemoryEventBus()
    store = DeadLetterStore(bus)
    item = store.record(event(), "redis unavailable")

    assert item.event_id == "event-1"
    assert [row.event_id for row in store.list(UserContext("t-1", "admin", "super_admin"))] == ["event-1"]
    assert store.replay(UserContext("t-1", "admin", "super_admin"), "event-1") == "replayed"
    assert bus.read("replay", after_sequence=0)[0].event_id == "event-1"
    assert store.replay(UserContext("t-1", "admin", "super_admin"), "event-1") == "already_replayed"


def test_dead_letter_store_rejects_non_admin_and_cross_tenant_access() -> None:
    store = DeadLetterStore(InMemoryEventBus())
    store.record(event(), "failed")

    with pytest.raises(PolicyError):
        store.list(UserContext("t-1", "employee", "employee"))
    with pytest.raises(LookupError):
        store.replay(UserContext("t-2", "admin", "super_admin"), "event-1")
