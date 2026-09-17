"""P2c-4 每会话模式：`ask` 拒执行 / `plan` 强制待批 / 合成取更严 / 权限与审计。

口径（真源）：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.9（含实现期裁定）
与 `docs/api-contract.md`「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」；
迁移 `038_conversation_mode_and_soft_delete`。

本文件覆盖规格 §4「P2c-4（产品项）真库用例」中**接口层可判定**的部分（真库部分见
`tests/test_conversation_lifecycle_postgres.py`）：

  ① `mode=ask` ⇒ 带键结构化调用 `409` + 审计 `conversation.execution.rejected`；
     **不创建**承载任务 / 运行 / 消息；幂等行落 `rejected` ⇒ **重放返回同一 `409`**；
  ② `ask` **不影响缺键桩路径**（「只问答」语义：问答仍可用）；
  ③ `mode=plan` ⇒ **强制待批**（`full_auto` 员工 + 低风险只读工具也 `202`）；
  ④ 合成**取更严**：`plan` **不放松** `critical`（非 CEO / 超管仍 `403`）；`goal` / `craft` 按自治三档不放松；
  ⑤ 模式变更：仅本人（他人 / 跨租户 `404`）；非法值 `422`；归档 `409`；同值**无副作用**（不写审计）；
  ⑥ **推进处拦截**：`ask` 会话的待批运行 ⇒ 决议端点 `409`，**不落决议**（待批动作仍 `pending`）；
     切回 `craft` 后可正常决议并推进执行。
"""

from __future__ import annotations

import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.domain import TaskStore, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.executor import DeterministicFakeExecutor
from app.tool_execution.service import ToolExecutionService
from app.tool_execution.store import InMemoryToolActionStore, ToolActionStatus
from app.tool_execution.workspace import WorkspaceManager
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)
AGENT = "content-writer"
TENANT = "t-mode"
EMPLOYEE = "u-1"
ADMIN = UserContext(TENANT, "admin-1", "super_admin")


def _owner_uid() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    task_store = TaskStore()
    run_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(run_store)
    action_store = InMemoryToolActionStore()
    runtime = RuntimeService(task_store, run_metrics=metrics, tool_actions=action_store)
    audit = AuditService(InMemoryAuditStore())
    conv_store = InMemoryConversationStore()
    conversations = ConversationService(conv_store, audit=audit)
    idempotency = InMemoryExecutionIdempotencyStore()
    directory = InMemoryWorkforceDirectoryStore()
    directory.create_role(ADMIN, role_key="writer", name="内容岗")
    directory.create_employee(ADMIN, agent_key=AGENT, name="内容员工", role_key="writer")
    # 自治三档 = `full_auto`（免批档）：用于证明 `plan` **强制待批**是「取更严」而非继承配置。
    directory.update_agent_config(ADMIN, AGENT, autonomy_level="full_auto", risk_threshold="high")

    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir(exist_ok=True)
    executor = DeterministicFakeExecutor()
    tool_execution = ToolExecutionService(
        catalog=build_tool_spec_catalog(),
        body_cipher=BodyCipher.from_base64(base64.b64encode(os.urandom(32)).decode("ascii")),
        executor=executor,
        workspace=WorkspaceManager(str(workspace_root)),
        tool_actions=action_store,
        run_records=run_store,
        audit=audit,
        authorize_execution=runtime.ensure_execution_authorized,
        trusted_roots=(str(trusted),),
        trusted_uid=_owner_uid(),
    )
    route = ConversationExecutionService(
        conversations=conversations,
        conversation_store=conv_store,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=tool_execution,
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        audit=audit,
        directory_store=directory,
    )
    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "tool_execution_service", tool_execution)
    monkeypatch.setattr(main, "conversation_execution_service", route)
    return {
        "tasks": task_store,
        "runs": run_store,
        "actions": action_store,
        "audit": audit,
        "store": conv_store,
        "idempotency": idempotency,
        "executor": executor,
    }


def headers(user_id: str = EMPLOYEE, role: str = "employee") -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": user_id, "X-User-Role": role}


def _create_conversation() -> str:
    response = client.post("/api/v1/conversations", headers=headers(), json={"agent_key": AGENT})
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def _set_mode(conversation_id: str, mode: str, *, user_id: str = EMPLOYEE, role: str = "employee"):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/mode",
        headers=headers(user_id, role),
        json={"mode": mode},
    )


def _send(conversation_id: str, content: str, *, key: str | None):
    extra = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(), **extra},
        json={"content": content},
    )


def _audit_actions(audit: AuditService) -> list[str]:
    return [record.action.value for record in audit.store.list_recent(TENANT, limit=200)]


def _audit_details(audit: AuditService, action: str) -> list[dict[str, object]]:
    return [
        record.detail
        for record in audit.store.list_recent(TENANT, limit=200)
        if record.action.value == action
    ]


# ------------------------------------------------------- ① ask：拒执行 + 审计 + 幂等 + 零副作用


def test_ask_mode_rejects_structured_execution_with_audit_and_replay(wired) -> None:
    conversation = _create_conversation()
    assert _set_mode(conversation, "ask").status_code == 200
    content = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})

    rejected = _send(conversation, content, key="ask-1")
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == "该会话为只问答模式，已拒绝执行"

    # 零副作用：无承载任务 / 无运行 / 无消息。
    assert wired["tasks"].count_by_employee(TENANT) == {}
    assert wired["runs"].list_recent(TENANT, limit=100) == []
    _conversations, total = wired["store"].list_messages(
        UserContext(TENANT, EMPLOYEE, "employee"), conversation
    )
    assert total == 0

    # 幂等行落 `rejected`（四态都写）：指针为空，重放返回同一 `409`。
    record = wired["idempotency"].get(TENANT, EMPLOYEE, conversation, "ask-1")
    assert record is not None and record.outcome == "rejected" and record.http_status == 409
    assert record.run_id is None and record.message_id is None
    replay = _send(conversation, content, key="ask-1")
    assert replay.status_code == 409

    # 审计：受控键（不落正文 / 不落参数值）。
    details = _audit_details(wired["audit"], "conversation.execution.rejected")
    assert len(details) == 1
    assert details[0] == {
        "conversation_id": conversation,
        "mode": "ask",
        "reason": "mode_ask",
    }
    assert content not in json.dumps(details, ensure_ascii=False)


def test_ask_mode_keeps_plain_stub_qa_available(wired) -> None:
    """`ask` = 只问答：**缺键桩路径不受影响**（问答可用，真实执行被拒）。"""
    conversation = _create_conversation()
    assert _set_mode(conversation, "ask").status_code == 200

    stub = _send(conversation, "你好，请介绍一下这个工作台", key=None)
    assert stub.status_code == 201, stub.text
    assert stub.json()["stub"] is True
    assert wired["runs"].list_recent(TENANT, limit=100) == []


# ------------------------------------------------------- ③④ plan：强制待批 + 合成取更严


def test_plan_mode_forces_approval_even_for_full_auto_read_tool(wired) -> None:
    conversation = _create_conversation()
    assert _set_mode(conversation, "plan").status_code == 200
    content = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})

    pending = _send(conversation, content, key="plan-1")
    assert pending.status_code == 202, pending.text
    body = pending.json()
    assert body["status"] == "pending_approval" and body["approval_id"]
    rows = wired["actions"].list_for_run(TENANT, body["run_id"])
    assert len(rows) == 1 and rows[0].status is ToolActionStatus.PENDING
    # 未落消息（待批分支不执行；消息在 ⑥ 之后才追加）——零副作用可证。
    assert wired["executor"].call_count == 0


def test_plan_mode_does_not_relax_critical_tool_for_employee(wired) -> None:
    """合成**只收紧不放松**：`plan` 不放松 `critical`（非 CEO / 超管仍 `403`）。"""
    conversation = _create_conversation()
    assert _set_mode(conversation, "plan").status_code == 200
    content = json.dumps({"tool_key": "artifact.export", "params": {"path": "/workspace"}})

    denied = _send(conversation, content, key="plan-critical")
    assert denied.status_code == 403, denied.text
    assert wired["tasks"].count_by_employee(TENANT) == {}


def test_goal_and_craft_keep_autonomy_semantics(wired) -> None:
    """`goal` / `craft` **不放松**（按自治三档）：`full_auto` + 低风险 ⇒ 直接执行 `201`。"""
    for index, mode in enumerate(("goal", "craft")):
        conversation = _create_conversation()
        if mode == "goal":
            assert _set_mode(conversation, mode).status_code == 200
        content = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})
        executed = _send(conversation, content, key=f"mode-{index}")
        assert executed.status_code == 201, executed.text
        assert executed.json()["stub"] is False


# ------------------------------------------------------- ⑤ 变更权限 / 取值 / 归档 / 同值无副作用


def test_mode_defaults_to_craft_and_is_visible_in_views(wired) -> None:
    conversation = _create_conversation()
    detail = client.get(f"/api/v1/conversations/{conversation}", headers=headers())
    assert detail.status_code == 200 and detail.json()["mode"] == "craft"
    listed = client.get("/api/v1/conversations", headers=headers()).json()["items"]
    assert listed[0]["mode"] == "craft"


def test_mode_change_only_by_owner_and_audited(wired) -> None:
    conversation = _create_conversation()
    changed = _set_mode(conversation, "plan")
    assert changed.status_code == 200 and changed.json()["mode"] == "plan"
    details = _audit_details(wired["audit"], "conversation.mode.changed")
    assert details == [
        {"conversation_id": conversation, "from_mode": "craft", "to_mode": "plan"}
    ]

    # 他人（含 ceo / super_admin）一律 404（与「修改他人会话 404」一致）。
    for user_id, role in (("u-2", "employee"), ("ceo-1", "ceo"), ("admin-1", "super_admin")):
        assert _set_mode(conversation, "ask", user_id=user_id, role=role).status_code == 404
    # 取值受控：非法值 / 未知字段 422。
    assert _set_mode(conversation, "turbo").status_code == 422
    assert client.post(
        f"/api/v1/conversations/{conversation}/mode",
        headers=headers(),
        json={"mode": "plan", "extra": 1},
    ).status_code == 422


def test_mode_change_is_noop_on_same_value_and_archived_conflicts(wired) -> None:
    conversation = _create_conversation()
    assert _set_mode(conversation, "craft").status_code == 200
    assert _audit_details(wired["audit"], "conversation.mode.changed") == []

    assert client.post(
        f"/api/v1/conversations/{conversation}/archive", headers=headers()
    ).status_code == 200
    archived = _set_mode(conversation, "ask")
    assert archived.status_code == 409, archived.text


# ------------------------------------------------------- ⑥ 推进处拦截（决议入口）


def test_ask_mode_blocks_approval_decision_and_allows_after_switch_back(wired) -> None:
    """`ask` 在**推进处**同样生效：决议整体拒绝（不落决议），切回模式后可再决议。"""
    conversation = _create_conversation()
    assert _set_mode(conversation, "plan").status_code == 200
    content = json.dumps({"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": "x"}})
    pending = _send(conversation, content, key="resume-1")
    assert pending.status_code == 202, pending.text
    run_id, approval_id = pending.json()["run_id"], pending.json()["approval_id"]

    # 待批期间切到 `ask`。
    assert _set_mode(conversation, "ask").status_code == 200
    blocked = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers("ceo-1", "ceo"),
        json={"approved": True},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == "该会话为只问答模式，已拒绝执行"
    # **不落决议**：待批动作仍 pending、执行器未被调用。
    assert wired["actions"].get(TENANT, wired["actions"].list_for_run(TENANT, run_id)[0].action_id).status is ToolActionStatus.PENDING
    assert wired["executor"].call_count == 0
    assert "conversation.execution.rejected" in _audit_actions(wired["audit"])

    # 切回 `craft` 后可正常决议并推进执行（拦截不留死锁）。
    assert _set_mode(conversation, "craft").status_code == 200
    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers("ceo-1", "ceo"),
        json={"approved": True},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["execution"]["outcome"] == "executed"
    assert wired["executor"].call_count == 1