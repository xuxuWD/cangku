"""对话接口：401/403/404/201、分页、桩回复显式标注、审计、权限收敛（§8 约束 3）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.domain import PolicyError, RiskLevel, UserContext, ensure_can_create
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    store = InMemoryConversationStore()
    audit_store = InMemoryAuditStore()
    audit = AuditService(audit_store)
    service = ConversationService(store, audit=audit)
    monkeypatch.setattr(main, "conversation_store", store)
    monkeypatch.setattr(main, "conversation_service", service)
    monkeypatch.setattr(main, "audit_service", audit)
    return store, audit_store


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(agent_key: str | None = None, **extra) -> dict:
    payload = {"agent_key": agent_key, **extra}
    response = client.post("/api/v1/conversations", headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ 认证与越权


def test_conversation_endpoints_require_authentication() -> None:
    assert client.get("/api/v1/conversations").status_code == 401
    assert client.post("/api/v1/conversations", json={"agent_key": None}).status_code == 401
    assert client.get("/api/v1/conversations/conv-1").status_code == 401
    assert client.post("/api/v1/conversations/conv-1/messages", json={"content": "hi"}).status_code == 401
    assert client.post("/api/v1/conversations/conv-1/archive").status_code == 401


def test_customer_admin_cannot_use_conversation_entry() -> None:
    assert client.get("/api/v1/conversations", headers=headers(role="customer_admin")).status_code == 403
    assert client.post(
        "/api/v1/conversations", headers=headers(role="customer_admin"), json={"agent_key": None}
    ).status_code == 403


# ------------------------------------------------------------ 正常流程


def test_create_and_list_conversations_with_pagination() -> None:
    for index in range(3):
        create_conversation(title=f"会话 {index}")

    body = client.get("/api/v1/conversations", headers=headers(), params={"limit": 2, "offset": 0}).json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2
    # 不泄露账号 PII（不含 operator_id / dsh_session_id）
    assert set(body["items"][0]) == {
        "conversation_id", "agent_key", "title", "status", "created_at", "updated_at",
    }

    page = client.get("/api/v1/conversations", headers=headers(), params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 1
    assert client.get("/api/v1/conversations", headers=headers(), params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/conversations", headers=headers(), params={"status": "paused"}).status_code == 422


def test_send_message_returns_explicit_stub_reply_and_detail() -> None:
    conversation = create_conversation(agent_key="content-writer")

    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(),
        json={"content": "帮我整理一下今天的待办"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stub"] is True  # P1 桩回复必须显式标注，绝不伪装成真实模型输出
    assert body["reply"]["stub"] is True
    assert body["reply"]["role"] == "assistant"

    detail = client.get(f"/api/v1/conversations/{conversation['conversation_id']}", headers=headers()).json()
    assert detail["messages_total"] == 2
    roles = [item["role"] for item in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["stub"] is True


def test_archiving_conversation_blocks_further_messages() -> None:
    conversation = create_conversation()

    archived = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/archive", headers=headers()
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    blocked = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(),
        json={"content": "归档后还能发吗"},
    )
    assert blocked.status_code == 409


# ------------------------------------------------------------ 404：跨租户与改他人会话


def test_cross_tenant_conversation_is_not_found() -> None:
    conversation = create_conversation()

    # 他租户的 CEO 也看不到（跨租户隔离只由 tenant_id 过滤保证）
    other_ceo = headers(role="ceo", user_id="ceo-9", tenant_id="t-2")
    assert client.get(f"/api/v1/conversations/{conversation['conversation_id']}", headers=other_ceo).status_code == 404
    assert client.get("/api/v1/conversations", headers=other_ceo).json()["total"] == 0
    assert client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        headers=other_ceo,
        json={"content": "越权"},
    ).status_code == 404


def test_modifying_another_operators_conversation_is_404() -> None:
    conversation = create_conversation()

    assert client.get(
        f"/api/v1/conversations/{conversation['conversation_id']}",
        headers=headers(user_id="u-2"),
    ).status_code == 404
    assert client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/archive",
        headers=headers(user_id="u-2"),
    ).status_code == 404


# ------------------------------------------------------------ 输入校验


def test_message_and_create_validation_returns_422() -> None:
    conversation = create_conversation()

    assert client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(),
        json={"content": "   "},
    ).status_code == 422
    # 未知字段一律拒绝
    assert client.post(
        "/api/v1/conversations", headers=headers(), json={"agent_key": None, "role": "ceo"}
    ).status_code == 422


# ------------------------------------------------------------ 审计


def test_conversation_lifecycle_is_audited() -> None:
    conversation = create_conversation(agent_key="content-writer")
    client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(),
        json={"content": "你好"},
    )
    client.post(f"/api/v1/conversations/{conversation['conversation_id']}/archive", headers=headers())

    created, _ = main.audit_service.query("t-1", actions=[AuditAction.CONVERSATION_CREATED])
    assert created[0].detail["conversation_id"] == conversation["conversation_id"]
    assert created[0].target_type == "conversation"

    sent, total = main.audit_service.query("t-1", actions=[AuditAction.CONVERSATION_MESSAGE_SENT])
    assert total == 2  # 用户消息 + 桩回复
    assert {record.detail["role"] for record in sent} == {"user", "assistant"}
    # 审计只记标识与角色，不记消息正文
    assert all("content" not in record.detail for record in sent)

    archived, _ = main.audit_service.query("t-1", actions=[AuditAction.CONVERSATION_ARCHIVED])
    assert archived[0].detail["status"] == "archived"


# ------------------------------------------------------------ 权限收敛（§8 约束 3）


def test_conversation_path_reuses_form_permission_gate() -> None:
    """对话入口与表单入口对同一动作必须收敛到同一个判定函数，而不是复制一份。"""
    service = main.conversation_service
    employee = UserContext("t-1", "u-1", "employee")

    # 表单入口拒绝：高风险 + 预算 > 1000
    with pytest.raises(PolicyError):
        ensure_can_create(employee, RiskLevel.HIGH, 5000)
    # 对话入口对同一动作同样拒绝
    with pytest.raises(PolicyError):
        service.ensure_can_create_task(employee, risk_level=RiskLevel.HIGH, budget=5000)

    # 允许的动作两边都放行
    ensure_can_create(employee, RiskLevel.LOW, 10)
    service.ensure_can_create_task(employee, risk_level=RiskLevel.LOW, budget=10)


def test_full_auto_autonomy_does_not_bypass_permission_gate() -> None:
    """自治等级只决定「是否需要人批」，不决定「是否绕开权限判定」。"""
    service = main.conversation_service
    employee = UserContext("t-1", "u-1", "employee")

    with pytest.raises(PolicyError):
        service.ensure_can_create_task(
            employee, risk_level=RiskLevel.HIGH, budget=9999, autonomy_level="full_auto"
        )
