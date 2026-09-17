"""P2c-4 个人数据导出与**物理删除**（本人 · 同步 · 幂等）的接口层用例。

口径（真源）：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.11（含实现期裁定）
与 `docs/api-contract.md`「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」。

覆盖（真库对应项见 `tests/test_conversation_lifecycle_postgres.py`）：
  ① 导出只含**本人**数据（他人与跨租户会话一律不出现）+ 审计 `conversation.exported`（不落正文）；
  ② 导出分页与**上限如实告知**（注入小上限 ⇒ `truncated` + `limit_reason`，不静默截断）；
  ③ 删除：本人 `200` + 四个计数；删除后**列表 / 详情 / 流 / 发消息 / 改模式一律 `404`**；
  ④ **复删幂等**（仍 `200`、计数全 0、**不新增审计**）；
  ⑤ 他人 / `ceo` / 跨租户删除一律 `404`，且数据仍在；
  ⑥ 审计 `conversation.deleted` 明细为受控计数（**不含正文**）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.service import MAX_EXPORT_ITEMS, ConversationService
from app.conversation.store import InMemoryConversationStore
from app.domain import UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.conversation.stream import InMemoryStreamStore

client = TestClient(app)
TENANT = "t-life"
OTHER_TENANT = "t-life-other"
EMPLOYEE = "u-1"
OTHER = "u-2"


@pytest.fixture()
def wired(monkeypatch):
    audit = AuditService(InMemoryAuditStore())
    conv_store = InMemoryConversationStore()
    stream_store = InMemoryStreamStore()
    idempotency = InMemoryExecutionIdempotencyStore()
    conversations = ConversationService(
        conv_store, audit=audit, stream_store=stream_store, idempotency_store=idempotency
    )
    monkeypatch.setattr(main, "store", conv_store)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "conversation_stream_store", stream_store)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    return {
        "audit": audit,
        "store": conv_store,
        "stream": stream_store,
        "idempotency": idempotency,
        "runs": InMemoryRunRecordStore(),
        "service": conversations,
    }


def headers(user_id: str = EMPLOYEE, role: str = "employee", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "X-User-Id": user_id, "X-User-Role": role}


def _context(user_id: str = EMPLOYEE, tenant: str = TENANT) -> UserContext:
    return UserContext(tenant, user_id, "employee")


def _create(user_id: str = EMPLOYEE, tenant: str = TENANT, *, title: str = "") -> str:
    response = client.post(
        "/api/v1/conversations", headers=headers(user_id, "employee", tenant), json={"title": title}
    )
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def _seed_content(store: InMemoryConversationStore, conversation_id: str, *, user_id: str = EMPLOYEE, count: int = 2) -> int:
    context = _context(user_id)
    for index in range(count):
        store.append_message(context, conversation_id, role="user", content=f"消息 {index}")
    _items, total = store.list_messages(context, conversation_id, limit=100)
    return total


def _seed_stream(stream: InMemoryStreamStore, conversation_id: str, run_id: str = "run-1") -> None:
    stream.append_frame(TENANT, conversation_id, run_id, kind="message.user", payload={"message_id": "msg-1"})
    stream.set_terminal(
        TENANT, conversation_id, run_id, status="completed", expires_at=datetime.now(UTC) + timedelta(days=7)
    )
    stream.append_frame(TENANT, conversation_id, run_id, kind="run.completed", payload={}, is_terminal=True)


def _audit_records(audit: AuditService, action: str) -> list[dict[str, object]]:
    return [
        record.detail
        for record in audit.store.list_recent(TENANT, limit=200)
        if record.action.value == action
    ]


# --------------------------------------------------------------- 导出


def test_export_mine_contains_only_own_conversations_with_audit(wired) -> None:
    mine = _create(title="我的会话")
    _seed_content(wired["store"], mine)
    other = _create(OTHER, title="他人会话")
    _seed_content(wired["store"], other, user_id=OTHER)

    exported = client.get("/api/v1/conversations/exports/mine", headers=headers())
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["total_conversations"] == 1
    assert [item["conversation_id"] for item in body["conversations"]] == [mine]
    assert body["conversations"][0]["mode"] == "craft"
    assert body["conversations"][0]["messages_total"] == 2
    assert len(body["conversations"][0]["messages"]) == 2
    assert body["truncated"] is False and body["limit_reason"] is None
    # 不含他人数据 / 不含内部字段。
    text = json.dumps(body, ensure_ascii=False)
    assert other not in text
    assert "operator_id" not in text and "dsh_session_id" not in text

    details = _audit_records(wired["audit"], "conversation.exported")
    assert details == [{"conversation_count": 1, "message_count": 2, "truncated": False}]


def test_export_mine_reports_limit_honestly(wired, monkeypatch) -> None:
    """超上限**不静默截断**：如实返回 `truncated` + 受控原因（注入小上限覆盖截断路径）。"""
    first = _create(title="A")
    _seed_content(wired["store"], first, count=2)
    second = _create(title="B")
    _seed_content(wired["store"], second, count=2)

    monkeypatch.setattr(main, "conversation_service", ConversationService(
        wired["store"],
        audit=wired["audit"],
        stream_store=wired["stream"],
        idempotency_store=wired["idempotency"],
        max_export_items=3,
    ))
    body = client.get("/api/v1/conversations/exports/mine", headers=headers()).json()
    assert body["truncated"] is True
    assert body["limit_reason"] == "total_items_exceeded"
    assert body["total_conversations"] == 2 and body["total_messages"] == 4
    # 只装入上限内的条目（1 会话 + 2 消息 = 3），绝不超限。
    packed = len(body["conversations"]) + sum(len(item["messages"]) for item in body["conversations"])
    assert packed <= 3
    assert MAX_EXPORT_ITEMS == 50000


def test_export_mine_rejects_non_conversing_role(wired) -> None:
    assert client.get(
        "/api/v1/conversations/exports/mine", headers=headers("ca-1", "customer_admin")
    ).status_code == 403


# --------------------------------------------------------------- 删除


def test_delete_conversation_purges_content_and_hides_session(wired) -> None:
    conversation = _create(title="敏感标题")
    assert _seed_content(wired["store"], conversation) == 2
    _seed_stream(wired["stream"], conversation)
    wired["idempotency"].insert(_idempotency_row(conversation))

    deleted = client.post(
        f"/api/v1/conversations/{conversation}/delete", headers=headers()
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "conversation_id": conversation,
        "deleted": True,
        "message_count": 2,
        "frame_count": 2,
        "stream_state_count": 1,
        "idempotency_count": 1,
    }

    # 内容行真删（不是墓碑）：消息 / 帧 / 流状态 / 幂等行计数为 0；会话行仍在（软删 + 标题清空）。
    with pytest.raises(Exception):
        wired["store"].list_messages(_context(), conversation)
    with pytest.raises(Exception):
        wired["store"].get_conversation(_context(), conversation)
    assert wired["stream"].list_frames(TENANT, conversation, "run-1") == []
    assert wired["stream"].get_state(TENANT, conversation, "run-1") is None
    assert wired["idempotency"].get(TENANT, EMPLOYEE, conversation, "k-1") is None
    raw = wired["store"].get_conversation_including_deleted(_context(), conversation)
    assert raw.title == "" and raw.deleted_at is not None

    # 全部读写路径 404（与「不存在」不可区分）。
    assert client.get(f"/api/v1/conversations/{conversation}", headers=headers()).status_code == 404
    assert client.post(
        f"/api/v1/conversations/{conversation}/messages", headers=headers(), json={"content": "hi"}
    ).status_code == 404
    assert client.post(
        f"/api/v1/conversations/{conversation}/mode", headers=headers(), json={"mode": "ask"}
    ).status_code == 404
    assert client.get(
        f"/api/v1/conversations/{conversation}/stream", headers=headers()
    ).status_code == 404
    listed = client.get("/api/v1/conversations", headers=headers()).json()["items"]
    assert conversation not in [item["conversation_id"] for item in listed]

    # 审计：受控计数，不含正文。
    details = _audit_records(wired["audit"], "conversation.deleted")
    assert details == [
        {
            "conversation_id": conversation,
            "message_count": 2,
            "frame_count": 2,
            "stream_state_count": 1,
            "idempotency_count": 1,
        }
    ]
    assert "消息 0" not in json.dumps(details, ensure_ascii=False)


def test_delete_is_idempotent_and_does_not_duplicate_audit(wired) -> None:
    conversation = _create()
    _seed_content(wired["store"], conversation)
    first = client.post(f"/api/v1/conversations/{conversation}/delete", headers=headers())
    assert first.status_code == 200 and first.json()["message_count"] == 2

    again = client.post(f"/api/v1/conversations/{conversation}/delete", headers=headers())
    assert again.status_code == 200, again.text
    assert again.json() == {
        "conversation_id": conversation,
        "deleted": True,
        "message_count": 0,
        "frame_count": 0,
        "stream_state_count": 0,
        "idempotency_count": 0,
    }
    assert len(_audit_records(wired["audit"], "conversation.deleted")) == 1


def test_delete_by_others_is_not_found_and_keeps_data(wired) -> None:
    conversation = _create()
    _seed_content(wired["store"], conversation)
    for user_id, role in ((OTHER, "employee"), ("ceo-1", "ceo"), ("admin-1", "super_admin")):
        denied = client.post(
            f"/api/v1/conversations/{conversation}/delete", headers=headers(user_id, role)
        )
        assert denied.status_code == 404, denied.text
    cross = client.post(
        f"/api/v1/conversations/{conversation}/delete", headers=headers(EMPLOYEE, "employee", OTHER_TENANT)
    )
    assert cross.status_code == 404
    # 数据仍在（拒绝不产生副作用）。
    assert wired["store"].list_messages(_context(), conversation)[1] == 2
    assert _audit_records(wired["audit"], "conversation.deleted") == []


def _idempotency_row(conversation_id: str):
    from app.conversation.idempotency import ExecutionIdempotencyRecord

    return ExecutionIdempotencyRecord(
        tenant_id=TENANT,
        actor_id=EMPLOYEE,
        conversation_id=conversation_id,
        idempotency_key="k-1",
        outcome="rejected",
        http_status=409,
    )