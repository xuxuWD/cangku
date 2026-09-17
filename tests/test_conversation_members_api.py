"""P2c-6 会话协作（分享与多端协同）接口层用例。

口径（真源）：
    docs/api-contract.md「会话协作：分享与多端协同（P2c-6 · 2026-09-17）」；
    docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md §2.16 / §4「P2c-6（协作）真库用例」。

覆盖：
  ① 分享：添加成员 ⇒ 成员可读（列表 / 详情 / 消息 / 流帧）、非成员 `404`；
  ② 撤销后新读 `404`（已读不可撤回）；复删 / 目标不是成员 `204` 幂等；
  ③ `read` 成员发言 ⇒ `403`（且**不落任何库**）；`write` 成员发言 ⇒ 成功且 `sender_id` 正确；
  ④ 成员触发执行**按其本人身份**走既有闸门（`employee` 成员触发 `critical` ⇒ 拒绝）；
  ⑤ 不合法成员（未知 / 跨租户 / 未审批 / `customer_admin`）⇒ `422`；非本人增删 ⇒ `404`；
  ⑥ 审计动作 `conversation.member.added` / `.removed` 键名正确且不含正文 / 姓名 / 手机号；
  ⑦ 归档会话加 / 撤成员 ⇒ `409`（实现期裁定 ①）；
  ⑧ 参与者列表发起人列首位（`is_owner` / `permission="owner"`）；账号缺失时如实回退，不编造；
  ⑨ 运行级读路径（`/runs/{id}/metrics`、`/events`、`/acceptance`、`/artifacts`、`/approvals`）
     成员可见；**控制类（pause / resume / cancel / 决议）不放松**（实现期裁定 ⑤）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import Account, AccountStatus
from app.accounts.repository import InMemoryAccountRepository
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.members import InMemoryConversationMemberStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.conversation.stream import InMemoryStreamStore
from app.domain import TaskStore, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.service import ToolExecutionResult
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

TENANT = "t-1"
TENANT_OTHER = "t-2"
OWNER = "u-1"
MEMBER = "u-2"
READER = "u-3"
CUSTOMER_ADMIN = "u-4"
FOREIGN = "u-5"
PENDING = "u-6"
STRANGER = "u-9"
AGENT = "content-writer"


class FakeToolExecution:
    """打桩执行入口：只记调用次数与请求（`requested_by` 即「以谁的身份执行」的判据）。"""

    def __init__(self, *, result=None) -> None:
        self.calls = 0
        self.requests = []
        self._result = result if result is not None else ToolExecutionResult(outcome="executed", code=201)

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        self.requests.append(request)
        return self._result


def _account(index: int, account_id: str, *, role: str = "employee", tenant: str = TENANT,
             status: AccountStatus = AccountStatus.APPROVED, full_name: str | None = None) -> Account:
    return Account(
        phone=f"1390000{index:04d}",
        password_hash="hash",
        position="岗位",
        full_name=full_name or f"姓名-{account_id}",
        account_id=account_id,
        role=role,
        tenant_id=tenant,
        status=status,
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    accounts = InMemoryAccountRepository()
    for index, (account_id, kwargs) in enumerate(
        [
            (OWNER, {}),
            (MEMBER, {}),
            (READER, {}),
            (CUSTOMER_ADMIN, {"role": "customer_admin"}),
            (FOREIGN, {"tenant": TENANT_OTHER}),
            (PENDING, {"status": AccountStatus.PENDING}),
        ]
    ):
        accounts.add(_account(index, account_id, **kwargs))

    member_store = InMemoryConversationMemberStore()
    conv_store = InMemoryConversationStore(members=member_store)
    audit = AuditService(InMemoryAuditStore())
    conversations = ConversationService(conv_store, audit=audit, members=member_store, accounts=accounts)
    stream_store = InMemoryStreamStore()
    idempotency = InMemoryExecutionIdempotencyStore()
    task_store = TaskStore()
    metrics = RunMetricsService(InMemoryRunRecordStore())
    # 与生产装配同口径：把**同一个**成员可见性回调注入 RuntimeService（只有读路径会用到）。
    runtime = RuntimeService(task_store, run_metrics=metrics, member_run_reader=main._member_can_read_run)
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    directory.create_employee(admin, agent_key=AGENT, name="内容员工", role_key="writer")

    execution = ConversationExecutionService(
        conversations=conversations,
        conversation_store=conv_store,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=None,
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        audit=audit,
        directory_store=directory,
    )

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_member_store", member_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "conversation_execution_service", execution)
    monkeypatch.setattr(main, "conversation_stream_store", stream_store)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "audit_service", audit)
    return {
        "members": member_store,
        "conv_store": conv_store,
        "service": conversations,
        "execution": execution,
        "stream": stream_store,
        "idempotency": idempotency,
        "accounts": accounts,
        "audit": audit,
        "directory": directory,
        "tasks": task_store,
    }


def wire_execution(monkeypatch, tool_execution) -> None:
    """把打桩执行器接上（带键路径 ⇒ 真实执行分支）；目录沿用隔离夹具里已建好的那一份。"""
    monkeypatch.setattr(main, "conversation_execution_service", ConversationExecutionService(
        conversations=main.conversation_service,
        conversation_store=main.conversation_store,
        task_store=main.store,
        runtime_service=main.runtime_service,
        tool_execution=tool_execution,
        idempotency=main.execution_idempotency_store,
        catalog=build_tool_spec_catalog(),
        audit=main.audit_service,
        directory_store=main.conversation_execution_service.directory_store,
    ))


def headers(role: str = "employee", user_id: str = OWNER, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(**extra) -> dict:
    response = client.post(
        "/api/v1/conversations", headers=headers(), json={"agent_key": AGENT, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(conversation_id: str, member_id: str, *, permission: str | None = None,
               who: str = OWNER, role: str = "employee", tenant: str = TENANT):
    payload: dict[str, object] = {"member_id": member_id}
    if permission is not None:
        payload["permission"] = permission
    return client.post(
        f"/api/v1/conversations/{conversation_id}/members",
        headers=headers(role=role, user_id=who, tenant_id=tenant),
        json=payload,
    )


def list_members(conversation_id: str, *, who: str = OWNER, tenant: str = TENANT, role: str = "employee"):
    return client.get(
        f"/api/v1/conversations/{conversation_id}/members",
        headers=headers(role=role, user_id=who, tenant_id=tenant),
    )


def remove_member(conversation_id: str, member_id: str, *, who: str = OWNER, tenant: str = TENANT):
    return client.delete(
        f"/api/v1/conversations/{conversation_id}/members/{member_id}",
        headers=headers(user_id=who, tenant_id=tenant),
    )


def send(conversation_id: str, content: str, *, key: str | None = None, who: str = OWNER):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(user_id=who), **extra},
        json={"content": content},
    )


# ------------------------------------------------------------ 认证与岗位闸门


def test_member_endpoints_require_authentication() -> None:
    assert client.post("/api/v1/conversations/conv-1/members", json={"member_id": MEMBER}).status_code == 401
    assert client.get("/api/v1/conversations/conv-1/members").status_code == 401
    assert client.delete("/api/v1/conversations/conv-1/members/u-2").status_code == 401


def test_customer_admin_cannot_use_member_endpoints() -> None:
    conversation = create_conversation()
    conversation_id = conversation["conversation_id"]

    assert add_member(conversation_id, MEMBER, who=CUSTOMER_ADMIN, role="customer_admin").status_code == 403
    assert list_members(conversation_id, who=CUSTOMER_ADMIN, role="customer_admin").status_code == 403
    assert client.delete(
        f"/api/v1/conversations/{conversation_id}/members/{MEMBER}",
        headers=headers(role="customer_admin", user_id=CUSTOMER_ADMIN),
    ).status_code == 403


# ------------------------------------------------------------ ①分享 / ⑥审计


def test_owner_adds_member_and_audit_records_controlled_keys() -> None:
    conversation_id = create_conversation()["conversation_id"]

    response = add_member(conversation_id, MEMBER)

    assert response.status_code == 201, response.text
    assert response.json() == {"conversation_id": conversation_id, "member_id": MEMBER, "permission": "read"}

    records, total = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_ADDED])
    assert total == 1
    record = records[0]
    assert record.target_type == "conversation"
    assert record.target_id == conversation_id
    # 受控键：只有会话号 / 成员号 / 权限档；不含正文 / 姓名 / 手机号。
    assert set(record.detail) == {"conversation_id", "member_id", "permission"}
    assert record.detail["member_id"] == MEMBER
    assert record.detail["permission"] == "read"


def test_add_member_is_idempotent_and_permission_upgrade_is_audited() -> None:
    conversation_id = create_conversation()["conversation_id"]

    assert add_member(conversation_id, MEMBER).status_code == 201
    again = add_member(conversation_id, MEMBER)  # 同权限重复添加 ⇒ 幂等，不再写审计
    assert again.status_code == 201
    _, total = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_ADDED])
    assert total == 1

    upgraded = add_member(conversation_id, MEMBER, permission="write")
    assert upgraded.status_code == 201
    assert upgraded.json()["permission"] == "write"
    _, total_after = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_ADDED])
    assert total_after == 2

    body = list_members(conversation_id).json()
    assert [item["permission"] for item in body["items"] if item["member_id"] == MEMBER] == ["write"]


def test_invalid_members_are_rejected_422() -> None:
    conversation_id = create_conversation()["conversation_id"]

    assert add_member(conversation_id, "u-unknown").status_code == 422  # 未知账号
    assert add_member(conversation_id, FOREIGN).status_code == 422  # 跨租户
    assert add_member(conversation_id, PENDING).status_code == 422  # 未审批
    assert add_member(conversation_id, CUSTOMER_ADMIN).status_code == 422  # customer_admin
    assert add_member(conversation_id, MEMBER, permission="admin").status_code == 422  # 非法权限档
    # 未知字段一律拒绝（extra=forbid）
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/members",
        headers=headers(),
        json={"member_id": MEMBER, "role": "ceo"},
    ).status_code == 422


def test_member_management_requires_owner() -> None:
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER)

    # 成员自己：增删成员仍仅本人 ⇒ 404（不区分「无权限」，避免探测）
    assert add_member(conversation_id, READER, who=MEMBER).status_code == 404
    assert remove_member(conversation_id, MEMBER, who=MEMBER).status_code == 404
    # 非成员：一律 404
    assert add_member(conversation_id, READER, who=STRANGER).status_code == 404
    assert remove_member(conversation_id, MEMBER, who=STRANGER).status_code == 404
    # 跨租户本人：404
    assert add_member(conversation_id, READER, who=FOREIGN, tenant=TENANT_OTHER).status_code == 404


def test_archived_conversation_rejects_member_changes() -> None:
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER)

    assert client.post(f"/api/v1/conversations/{conversation_id}/archive", headers=headers()).status_code == 200

    assert add_member(conversation_id, READER).status_code == 409
    assert remove_member(conversation_id, MEMBER).status_code == 409
    # 归档不影响既有成员的**读**（消息仍在），只是不能再改成员名单。
    assert list_members(conversation_id, who=MEMBER).status_code == 200


# ------------------------------------------------------------ ②读路径「本人 ∪ 成员」


class _StreamSettings:
    """SSE 读端的极短时序桩（连接上限 1s / 轮询 50ms）：让「无 run 挂起」的流自然结束。"""

    stream_poll_interval_ms = 50
    stream_max_connection_seconds = 1
    stream_retention_days = 7
    stream_max_frames = 2000
    stream_max_bytes = 4 * 1024 * 1024
    stream_stalled_hours = 6


def test_member_can_read_conversation_list_detail_and_stream(monkeypatch) -> None:
    conversation_id = create_conversation()["conversation_id"]
    send(conversation_id, "第一条消息")  # 本人发言，产生消息
    add_member(conversation_id, MEMBER)

    listed = client.get("/api/v1/conversations", headers=headers(user_id=MEMBER)).json()
    assert [item["conversation_id"] for item in listed["items"]] == [conversation_id]

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(user_id=MEMBER))
    assert detail.status_code == 200
    assert detail.json()["messages_total"] == 2

    monkeypatch.setattr(main, "get_settings", lambda: _StreamSettings())
    with client.stream(
        "GET", f"/api/v1/conversations/{conversation_id}/stream", headers=headers(user_id=MEMBER)
    ) as response:
        assert response.status_code == 200
        [line for line in response.iter_lines()]  # 无 run 挂起：由连接上限自然收口


def test_non_member_cannot_read_conversation() -> None:
    conversation_id = create_conversation()["conversation_id"]

    listed = client.get("/api/v1/conversations", headers=headers(user_id=STRANGER)).json()
    assert listed["total"] == 0
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(user_id=STRANGER)).status_code == 404
    assert client.get(
        f"/api/v1/conversations/{conversation_id}/stream", headers=headers(user_id=STRANGER)
    ).status_code == 404
    assert list_members(conversation_id, who=STRANGER).status_code == 404
    # 跨租户同样 404
    assert client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers(user_id=FOREIGN, tenant_id=TENANT_OTHER)
    ).status_code == 404


def test_remove_member_is_idempotent_and_revokes_access() -> None:
    conversation_id = create_conversation()["conversation_id"]
    send(conversation_id, "分享前的消息")
    add_member(conversation_id, MEMBER)
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(user_id=MEMBER)).status_code == 200

    first = remove_member(conversation_id, MEMBER)
    assert first.status_code == 204
    records, total = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_REMOVED])
    assert total == 1
    assert set(records[0].detail) == {"conversation_id", "member_id", "permission"}

    # 已读内容不可撤回：只是新读请求 404（消息本身仍在，撤回不了「看过」）。
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(user_id=MEMBER)).status_code == 404
    assert client.get(
        f"/api/v1/conversations/{conversation_id}/stream", headers=headers(user_id=MEMBER)
    ).status_code == 404

    # 复删 / 目标不是成员（含发起人）一律 204 幂等 no-op，且不重复写审计。
    assert remove_member(conversation_id, MEMBER).status_code == 204
    assert remove_member(conversation_id, OWNER).status_code == 204
    assert remove_member(conversation_id, STRANGER).status_code == 204
    _, total_after = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_REMOVED])
    assert total_after == 1


# ------------------------------------------------------------ ③发言写权限与 sender_id


def test_read_member_cannot_speak_and_writes_nothing(monkeypatch) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, READER)
    content = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})

    # 纯文本（桩路径）
    assert send(conversation_id, "我能说话吗", who=READER).status_code == 403
    # 带键（执行路径）——必须在**任何落库 / 执行之前**拒绝
    blocked = send(conversation_id, content, key="k-read", who=READER)
    assert blocked.status_code == 403, blocked.text
    blocked_stream = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={**headers(user_id=READER), "Idempotency-Key": "k-read-2"},
        json={"content": content},
    )
    assert blocked_stream.status_code == 403

    assert fake.calls == 0
    assert main.store.count_by_employee(TENANT) == {}
    assert main.run_metrics_service.store.list_recent(TENANT, limit=50) == []
    assert main.execution_idempotency_store.get(TENANT, READER, conversation_id, "k-read") is None
    assert main.execution_idempotency_store.get(TENANT, READER, conversation_id, "k-read-2") is None
    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers()).json()
    assert detail["messages_total"] == 0


def test_write_member_speaks_and_sender_id_is_recorded() -> None:
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER, permission="write")

    sent = send(conversation_id, "我来协作", who=MEMBER)
    assert sent.status_code == 201, sent.text

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers()).json()
    messages = detail["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["sender_id"] == MEMBER  # 发言者本人
    assert messages[1]["sender_id"] is None  # 助手 / 工具 / 系统消息恒 null

    records, total = main.audit_service.query(TENANT, actions=[AuditAction.CONVERSATION_MESSAGE_SENT])
    assert total == 2
    user_record = next(item for item in records if item.detail["role"] == "user")
    assert user_record.actor_id == MEMBER  # 审计记发言者本人，不记会话发起人
    assert all("content" not in item.detail for item in records)


def test_member_cannot_use_management_actions() -> None:
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER, permission="write")

    assert client.post(
        f"/api/v1/conversations/{conversation_id}/archive", headers=headers(user_id=MEMBER)
    ).status_code == 404
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/mode", headers=headers(user_id=MEMBER), json={"mode": "ask"}
    ).status_code == 404
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/delete", headers=headers(user_id=MEMBER)
    ).status_code == 404


# ------------------------------------------------------------ ④成员执行按本人身份


def test_write_member_execution_uses_own_identity_and_critical_is_denied(monkeypatch) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER, permission="write")

    ok = send(conversation_id, json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}}), key="k-w", who=MEMBER)
    assert ok.status_code == 201, ok.text
    assert fake.calls == 1
    assert fake.requests[0].requested_by == MEMBER  # 一律以本人身份走闸门
    row = main.execution_idempotency_store.get(TENANT, MEMBER, conversation_id, "k-w")
    assert row is not None and row.actor_id == MEMBER
    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers()).json()
    assert [item["sender_id"] for item in detail["messages"] if item["role"] == "user"] == [MEMBER]

    # `critical` 承载任务：非 CEO / 超管（成员是 employee）⇒ 403（既有闸门不放松）
    critical = send(
        conversation_id, json.dumps({"tool_key": "artifact.export", "params": {}}), key="k-c", who=MEMBER
    )
    assert critical.status_code == 403
    assert fake.calls == 1


# ------------------------------------------------------------ ⑧参与者列表


def test_participants_list_has_owner_first_and_falls_back_honestly(_isolate) -> None:
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, MEMBER, permission="write")

    body = list_members(conversation_id).json()
    assert body["total"] == 2
    owner, member = body["items"]
    assert owner["member_id"] == OWNER
    assert owner["is_owner"] is True
    assert owner["permission"] == "owner"
    assert owner["display_name"] == f"姓名-{OWNER}"
    assert owner["role"] == "employee"
    assert member["member_id"] == MEMBER
    assert member["is_owner"] is False
    assert member["permission"] == "write"
    assert member["display_name"] == f"姓名-{MEMBER}"
    assert member["added_by"] == OWNER
    assert member["created_at"]

    # 账号缺失 ⇒ display_name 回退 member_id、role 为 null（**不编造**）：
    # 直接在成员表造一行「指向不存在的账号」的成员（账号被删 / 迁移留下的悬空引用边界）。
    _isolate["members"].upsert(
        tenant_id=TENANT,
        conversation_id=conversation_id,
        member_id="u-ghost",
        permission="read",
        added_by=OWNER,
    )
    ghost = next(item for item in list_members(conversation_id).json()["items"] if item["member_id"] == "u-ghost")
    assert ghost["display_name"] == "u-ghost"
    assert ghost["role"] is None


# ------------------------------------------------------------ ⑨运行级读路径（裁定 ⑤）


def test_member_can_read_run_endpoints_but_not_control_them(monkeypatch) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation()["conversation_id"]
    add_member(conversation_id, READER)
    sent = send(
        conversation_id, json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}}), key="k-run"
    )
    assert sent.status_code == 201, sent.text
    run_id = sent.json()["run_id"]

    for path in ("metrics", "events", "acceptance", "artifacts", "approvals"):
        member_read = client.get(f"/api/v1/runs/{run_id}/{path}", headers=headers(user_id=READER))
        assert member_read.status_code == 200, f"{path}: {member_read.text}"

    # 非成员：`/events` 沿用 P2b 既有 403 口径（「无权操作此运行」，本批不改）；
    # 其余四个读端点保持「不泄露存在性」的 404。
    assert client.get(f"/api/v1/runs/{run_id}/events", headers=headers(user_id=STRANGER)).status_code == 403
    for path in ("metrics", "acceptance", "artifacts", "approvals"):
        stranger_read = client.get(f"/api/v1/runs/{run_id}/{path}", headers=headers(user_id=STRANGER))
        assert stranger_read.status_code == 404, f"{path}: {stranger_read.text}"

    # 控制类一律不放松：成员 pause / resume / cancel 仍 404
    assert client.post(
        f"/api/v1/runs/{run_id}/pause", headers=headers(user_id=READER), json={"reason": "x"}
    ).status_code == 404
    assert client.post(f"/api/v1/runs/{run_id}/resume", headers=headers(user_id=READER)).status_code == 404
    assert client.post(
        f"/api/v1/runs/{run_id}/cancel", headers=headers(user_id=READER), json={"reason": "x"}
    ).status_code == 404