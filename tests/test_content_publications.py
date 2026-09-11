"""内容发布（公众号）的领域、仓储、服务与接口行为测试。

本文件全程离线：外部平台调用一律通过注入式传输层 / 假发布器，不发起任何真实网络请求。
真实公众号发布仍属未验收项。
"""

from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.content.models import ContentBriefInput, SourceInput
from app.content.publication_service import PublicationNotAllowed, PublicationService
from app.content.publication_store import (
    InMemoryPublicationStore,
    PostgresPublicationStore,
    PublicationNotFound,
    PublicationRecord,
)
from app.content.publisher import (
    PublicationFailed,
    PublicationNotConfigured,
    PublicationReceipt,
    WechatMpPublisher,
)
from app.content.service import ContentNotFound, ContentService
from app.content.store import ContentStore
from app.domain import TaskStore, UserContext
from app.runtime.service import RuntimeService

PUBLICATION_COLUMNS = (
    "publication_id",
    "tenant_id",
    "task_id",
    "revision",
    "target",
    "idempotency_key",
    "status",
    "receipt_id",
    "error",
    "created_by",
    "created_at",
    "verified_at",
)


def actor(tenant="tenant-a", user="u1", role="employee") -> UserContext:
    return UserContext(tenant_id=tenant, user_id=user, role=role)


class FakePublisher:
    name = "fake_mp"

    def __init__(self, *, fail=False, receipt_id="rcpt-1", verify_status="published"):
        self.calls: list[dict[str, str]] = []
        self.verify_calls: list[str] = []
        self.fail = fail
        self.receipt_id = receipt_id
        self.verify_status = verify_status

    def publish(self, *, title: str, content: str, idempotency_key: str) -> PublicationReceipt:
        self.calls.append({"title": title, "content": content, "idempotency_key": idempotency_key})
        if self.fail:
            raise PublicationFailed("发布请求失败")
        return PublicationReceipt(
            receipt_id=self.receipt_id, status="succeeded", published_at=datetime.now(UTC)
        )

    def verify(self, receipt_id: str) -> str:
        self.verify_calls.append(receipt_id)
        return self.verify_status


class AuditSpy:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, action, *, tenant_id=None, actor_id=None, target_type=None,
               target_id=None, phone_masked=None, detail=None) -> None:
        self.records.append({"action": action, "detail": dict(detail or {})})

    @property
    def actions(self) -> list[str]:
        return [str(item["action"]) for item in self.records]


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, unparsable=False):
        self.status_code = status_code
        self._payload = payload
        self._unparsable = unparsable

    def json(self):
        if self._unparsable:
            raise ValueError("not json")
        return self._payload


def make_service(store=None, *, publisher=None, audit=None, content_store=None):
    content_store = content_store or ContentStore()
    task_store = TaskStore()
    content_service = ContentService(task_store, RuntimeService(task_store), content_store)
    publication_store = store or InMemoryPublicationStore()
    service = PublicationService(
        content_store, publication_store, publisher=publisher, audit=audit
    )
    return content_service, service, content_store, publication_store


def confirmed_task(content_service, content_store, *, tenant="tenant-a", user="u1", key="k1") -> str:
    created = content_service.create(
        actor=actor(tenant, user),
        payload=ContentBriefInput(
            topic="本周选题",
            sources=[SourceInput(url="https://example.com/a", excerpt="参考摘录")],
            knowledge_references=[],
        ),
        idempotency_key=key,
    )
    task_id = created.task_id
    draft = content_store.get(tenant, user, task_id).draft
    content_service.confirm(actor=actor(tenant, user), task_id=task_id, revision=draft.revision)
    return task_id


# --- 迁移契约 -----------------------------------------------------------------


def test_migration_016_declares_publications_table_with_unique_idempotency() -> None:
    content = (Path(__file__).resolve().parents[1] / "migrations" / "016_content_publications.sql").read_text(
        encoding="utf-8"
    )
    # 判定依据：幂等靠数据库唯一约束兜底，缺它就可能在并发下重复发布。
    assert "CREATE TABLE IF NOT EXISTS workbench_content_publications" in content
    assert "UNIQUE (tenant_id, idempotency_key)" in content
    assert "idx_workbench_content_publications_task" in content
    for status in ("succeeded", "manual_takeover", "pending"):
        assert status in content


# --- 发布器 -------------------------------------------------------------------


def test_publisher_posts_signed_payload_and_parses_receipt() -> None:
    captured: list[tuple] = []

    def transport(method, url, *, headers, json, timeout):
        captured.append((method, url, headers, json, timeout))
        return FakeResponse(payload={"receipt_id": "rcpt-9", "status": "succeeded"})

    publisher = WechatMpPublisher(
        "https://mp.example/api", "acct-1", "token-1", timeout_seconds=7, transport=transport
    )
    receipt = publisher.publish(title="标题", content="正文", idempotency_key="t:1")

    method, url, headers, payload, timeout = captured[0]
    assert (method, url, timeout) == ("POST", "https://mp.example/api/publish", 7)
    assert headers["Authorization"] == "Bearer token-1"
    assert payload == {
        "title": "标题",
        "content": "正文",
        "idempotency_key": "t:1",
        "account_id": "acct-1",
    }
    assert receipt.receipt_id == "rcpt-9"


def test_publisher_rejects_non_2xx_and_missing_receipt() -> None:
    with pytest.raises(PublicationFailed):
        WechatMpPublisher(
            "https://mp.example/api", "acct-1", "token-1", timeout_seconds=5,
            transport=lambda *a, **k: FakeResponse(status_code=500, payload={}),
        ).publish(title="t", content="c", idempotency_key="k")

    with pytest.raises(PublicationFailed, match="缺少回执号"):
        WechatMpPublisher(
            "https://mp.example/api", "acct-1", "token-1", timeout_seconds=5,
            transport=lambda *a, **k: FakeResponse(payload={"status": "ok"}),
        ).publish(title="t", content="c", idempotency_key="k")

    with pytest.raises(PublicationFailed, match="无法解析"):
        WechatMpPublisher(
            "https://mp.example/api", "acct-1", "token-1", timeout_seconds=5,
            transport=lambda *a, **k: FakeResponse(unparsable=True),
        ).publish(title="t", content="c", idempotency_key="k")


def test_publisher_verify_reads_status_and_validates_config() -> None:
    captured: list[tuple] = []

    def transport(method, url, *, headers, json, timeout):
        captured.append((method, url))
        return FakeResponse(payload={"status": "published"})

    publisher = WechatMpPublisher(
        "https://mp.example/api/", "acct-1", "token-1", timeout_seconds=5, transport=transport
    )
    assert publisher.verify("rcpt-9") == "published"
    assert captured == [("GET", "https://mp.example/api/publish/rcpt-9")]

    for args in (("", "a", "t"), ("https://x", "", "t"), ("https://x", "a", "")):
        with pytest.raises(ValueError):
            WechatMpPublisher(*args, timeout_seconds=5)


def test_build_content_publisher_is_closed_without_full_config() -> None:
    from app.bootstrap import build_content_publisher
    from app.settings import Settings

    base = {"content_store_backend": "memory"}
    assert build_content_publisher(Settings(**base)) is None
    assert build_content_publisher(Settings(**base, content_publish_endpoint="https://mp.example/api")) is None
    publisher = build_content_publisher(
        Settings(
            **base,
            content_publish_endpoint="https://mp.example/api",
            content_publish_account_id="acct-1",
            content_publish_access_token="token-1",
            content_publish_target="wechat_mp",
        )
    )
    assert publisher is not None and publisher.name == "wechat_mp"


# --- 仓储 ---------------------------------------------------------------------


def test_in_memory_store_is_idempotent_and_tenant_scoped() -> None:
    store = InMemoryPublicationStore()
    record = PublicationRecord(
        tenant_id="tenant-a", task_id="t1", revision=1, target="wechat_mp",
        idempotency_key="t1:1", created_by="u1",
    )
    assert store.add(record) is record
    again = store.add(
        PublicationRecord(
            tenant_id="tenant-a", task_id="t1", revision=1, target="wechat_mp",
            idempotency_key="t1:1", created_by="u1",
        )
    )
    assert again.publication_id == record.publication_id
    assert store.find_by_idempotency("tenant-a", "t1:1").publication_id == record.publication_id
    assert store.find_by_idempotency("tenant-b", "t1:1") is None
    with pytest.raises(PublicationNotFound):
        store.get("tenant-b", record.publication_id)
    assert store.list_for_task("tenant-b", "t1") == []


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, rows=()):
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj

    def transaction(self):
        return nullcontext()


def pub_row(**overrides) -> tuple:
    values = {
        "publication_id": "pub-1",
        "tenant_id": "tenant-a",
        "task_id": "t1",
        "revision": 1,
        "target": "wechat_mp",
        "idempotency_key": "t1:1",
        "status": "succeeded",
        "receipt_id": "rcpt-1",
        "error": None,
        "created_by": "u1",
        "created_at": datetime.now(UTC),
        "verified_at": None,
    }
    values.update(overrides)
    return tuple(values[name] for name in PUBLICATION_COLUMNS)


def test_postgres_store_uses_conflict_guard_and_tenant_scope() -> None:
    connection = _FakeConnection([
        pub_row(),          # add 的 RETURNING
        pub_row(),          # get
        pub_row(),          # find_by_idempotency
        pub_row(),          # list_for_task
        pub_row(status="manual_takeover"),  # mark_result
    ])
    store = PostgresPublicationStore(connection)

    store.add(
        PublicationRecord(
            tenant_id="tenant-a", task_id="t1", revision=1, target="wechat_mp",
            idempotency_key="t1:1", created_by="u1",
        )
    )
    assert "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING" in connection.cursor_obj.executed[0][0]

    store.get("tenant-a", "pub-1")
    assert "WHERE publication_id = %s AND tenant_id = %s" in connection.cursor_obj.executed[1][0]

    store.find_by_idempotency("tenant-a", "t1:1")
    assert "WHERE tenant_id = %s AND idempotency_key = %s" in connection.cursor_obj.executed[2][0]

    store.list_for_task("tenant-a", "t1")
    assert "WHERE tenant_id = %s AND task_id = %s" in connection.cursor_obj.executed[3][0]

    store.mark_result("pub-1", status="manual_takeover", error="boom")
    assert "RETURNING" in connection.cursor_obj.executed[4][0]


# --- 服务编排 -----------------------------------------------------------------


def test_publish_requires_confirmation_and_fails_closed_without_publisher() -> None:
    content_service, service, content_store, _ = make_service(publisher=None)
    created = content_service.create(
        actor=actor(), payload=ContentBriefInput(
            topic="选题", sources=[SourceInput(url="https://example.com/a", excerpt="摘录")],
            knowledge_references=[],
        ), idempotency_key="k-unconfirmed",
    )
    with pytest.raises(PublicationNotAllowed):
        service.publish(actor(), created.task_id)

    task_id = confirmed_task(content_service, content_store)
    with pytest.raises(PublicationNotConfigured):
        service.publish(actor(), task_id)


def test_publish_succeeds_and_never_resends_on_repeat() -> None:
    publisher = FakePublisher()
    audit = AuditSpy()
    content_service, service, content_store, store = make_service(publisher=publisher, audit=audit)
    task_id = confirmed_task(content_service, content_store)

    first = service.publish(actor(), task_id)
    second = service.publish(actor(), task_id)

    assert first.publication_id == second.publication_id
    assert first.status == "succeeded" and first.receipt_id == "rcpt-1"
    # 幂等的核心：第二次调用不得再次触达外部平台。
    assert len(publisher.calls) == 1
    assert publisher.calls[0]["idempotency_key"].startswith(f"{task_id}:")
    assert audit.actions == ["content.publication.requested", "content.publication.succeeded"]
    assert len(store.list_for_task("tenant-a", task_id)) == 1


def test_publish_failure_goes_to_manual_takeover_without_retry() -> None:
    publisher = FakePublisher(fail=True)
    audit = AuditSpy()
    content_service, service, content_store, store = make_service(publisher=publisher, audit=audit)
    task_id = confirmed_task(content_service, content_store)

    with pytest.raises(PublicationFailed):
        service.publish(actor(), task_id)

    records = store.list_for_task("tenant-a", task_id)
    assert len(records) == 1
    assert records[0].status == "manual_takeover"
    assert records[0].receipt_id is None
    assert len(publisher.calls) == 1
    assert audit.actions == [
        "content.publication.requested",
        "content.publication.manual_takeover",
    ]


def test_publish_is_scoped_to_tenant_and_owner() -> None:
    content_service, service, content_store, _ = make_service(publisher=FakePublisher())
    task_id = confirmed_task(content_service, content_store, tenant="tenant-a", user="owner")
    with pytest.raises(ContentNotFound):
        service.publish(actor("tenant-b", "owner"), task_id)
    with pytest.raises(ContentNotFound):
        service.publish(actor("tenant-a", "other"), task_id)


def test_verify_updates_status_and_audits() -> None:
    publisher = FakePublisher(verify_status="published")
    audit = AuditSpy()
    content_service, service, content_store, _ = make_service(publisher=publisher, audit=audit)
    task_id = confirmed_task(content_service, content_store)
    published = service.publish(actor(), task_id)

    verified = service.verify(actor(), published.publication_id)

    assert publisher.verify_calls == ["rcpt-1"]
    assert verified.status == "published"
    assert verified.verified_at is not None
    assert audit.actions[-1] == "content.publication.verified"


def test_verify_requires_receipt_and_publisher() -> None:
    content_service, service, content_store, store = make_service(publisher=FakePublisher())
    task_id = confirmed_task(content_service, content_store)
    record = store.add(
        PublicationRecord(
            tenant_id="tenant-a", task_id=task_id, revision=1, target="wechat_mp",
            idempotency_key=f"{task_id}:1", created_by="u1",
        )
    )
    with pytest.raises(PublicationFailed, match="没有回执"):
        service.verify(actor(), record.publication_id)

    # 未配置发布渠道时同样拒绝核对（复用同一内容仓储，保证任务可见）。
    no_pub_store = InMemoryPublicationStore()
    no_pub_service = PublicationService(
        content_store, no_pub_store, publisher=None, audit=None
    )
    record2 = no_pub_store.add(
        PublicationRecord(
            tenant_id="tenant-a", task_id=task_id, revision=1, target="wechat_mp",
            idempotency_key=f"{task_id}:1", created_by="u1",
        )
    )
    with pytest.raises(PublicationNotConfigured):
        no_pub_service.verify(actor(), record2.publication_id)


# --- 接口 ---------------------------------------------------------------------


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _headers(user="pub-user", tenant="pub-tenant", role="employee"):
    return {"X-Tenant-Id": tenant, "X-User-Id": user, "X-User-Role": role}


def _confirmed_content_task(client: TestClient, *, user="pub-user", tenant="pub-tenant") -> str:
    created = client.post(
        "/api/v1/content-tasks",
        headers=_headers(user, tenant),
        json={
            "topic": "本周选题",
            "sources": [{"url": "https://example.com/a", "excerpt": "参考摘录"}],
            "knowledge_references": [],
            "idempotency_key": f"pub-{user}-{tenant}",
        },
    )
    task_id = created.json()["task_id"]
    updated = client.put(
        f"/api/v1/content-tasks/{task_id}/draft",
        headers=_headers(user, tenant),
        json={"revision": 1, "title": "发布标题", "summary": "摘要", "body_markdown": "发布正文", "image_suggestions": []},
    )
    revision = updated.json().get("revision") or 2
    assert client.post(
        f"/api/v1/content-tasks/{task_id}/confirmation",
        headers=_headers(user, tenant),
        json={"revision": revision},
    ).status_code == 200
    return task_id


def test_publication_api_returns_503_when_not_configured(monkeypatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module.publication_service, "publisher", None)
    client = _client()
    task_id = _confirmed_content_task(client, user="noconf-user", tenant="noconf-tenant")

    response = client.post(
        f"/api/v1/content-tasks/{task_id}/publications", headers=_headers("noconf-user", "noconf-tenant")
    )
    assert response.status_code == 503


def test_publication_api_rejects_unconfirmed_then_publishes_idempotently(monkeypatch) -> None:
    import app.main as main_module

    publisher = FakePublisher()
    monkeypatch.setattr(main_module.publication_service, "publisher", publisher)
    client = _client()
    headers = _headers("api-user", "api-tenant")

    created = client.post(
        "/api/v1/content-tasks",
        headers=headers,
        json={
            "topic": "本周选题",
            "sources": [{"url": "https://example.com/a", "excerpt": "参考摘录"}],
            "knowledge_references": [],
            "idempotency_key": "pub-api-1",
        },
    )
    task_id = created.json()["task_id"]

    # 未确认 → 409
    assert client.post(f"/api/v1/content-tasks/{task_id}/publications", headers=headers).status_code == 409

    client.put(
        f"/api/v1/content-tasks/{task_id}/draft",
        headers=headers,
        json={"revision": 1, "title": "发布标题", "summary": "摘要", "body_markdown": "发布正文", "image_suggestions": []},
    )
    assert client.post(
        f"/api/v1/content-tasks/{task_id}/confirmation", headers=headers, json={"revision": 2}
    ).status_code == 200

    first = client.post(f"/api/v1/content-tasks/{task_id}/publications", headers=headers)
    second = client.post(f"/api/v1/content-tasks/{task_id}/publications", headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["publication_id"] == second.json()["publication_id"]
    assert first.json()["status"] == "succeeded"
    assert len(publisher.calls) == 1

    listed = client.get(f"/api/v1/content-tasks/{task_id}/publications", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    verified = client.post(
        f"/api/v1/content-publications/{first.json()['publication_id']}/verification", headers=headers
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "published"

    # 跨用户不可见
    assert client.get(
        f"/api/v1/content-tasks/{task_id}/publications", headers=_headers("other-user", "api-tenant")
    ).status_code == 404


def test_publication_api_returns_502_on_platform_failure(monkeypatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module.publication_service, "publisher", FakePublisher(fail=True))
    client = _client()
    headers = _headers("fail-user", "fail-tenant")
    task_id = _confirmed_content_task(client, user="fail-user", tenant="fail-tenant")

    response = client.post(f"/api/v1/content-tasks/{task_id}/publications", headers=headers)
    assert response.status_code == 502
    # 失败后仍留下可追溯记录（人工接管），且不会自动重发
    listed = client.get(f"/api/v1/content-tasks/{task_id}/publications", headers=headers)
    assert listed.json()["items"][0]["status"] == "manual_takeover"
