"""段二-4 端到端：从对话入口走通「202 待批 → 决议 → 审批后重跑执行」主流程。

验证：对话入口带 `Idempotency-Key` 触发 `fs.write`（需审批）→ 落 `027` 待批动作 → 决议端点
批准后在同一请求内 `resume` 执行（假执行器），响应体带 `execution`；且**审批后的执行不回写
幂等行**（重放该键仍返回首次的 `202`，规格 §4.1.3 R5-2）。
"""

from __future__ import annotations

import base64
import json
import logging
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
TENANT = "t-1"
EMPLOYEE = "u-1"


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
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    directory.create_employee(admin, agent_key=AGENT, name="内容员工", role_key="writer")

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
    return {"executor": executor, "actions": action_store, "idempotency": idempotency, "runtime": runtime}


def headers(user_id: str = EMPLOYEE, role: str = "employee") -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": user_id, "X-User-Role": role}


def test_conversation_to_approval_to_execution_full_flow(wired) -> None:
    conversation = client.post(
        "/api/v1/conversations", headers=headers(), json={"agent_key": AGENT}
    ).json()["conversation_id"]
    content = json.dumps({"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": "机密正文"}})

    pending = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers={**headers(), "Idempotency-Key": "flow-1"},
        json={"content": content},
    )
    assert pending.status_code == 202, pending.text
    body = pending.json()
    run_id, approval_id = body["run_id"], body["approval_id"]
    assert approval_id
    # ⑥ 已先落库：027 存在一条 pending 待批动作，且正文以密文承载（明文不落 args_json）。
    rows = wired["actions"].list_for_run(TENANT, run_id)
    assert len(rows) == 1 and rows[0].status is ToolActionStatus.PENDING
    assert rows[0].approval_id == approval_id
    assert rows[0].args_json == {"path": "/workspace/a.txt", "content": "«body»"}

    # 决议端点：CEO 批准 → 同一请求内重跑并执行（假执行器被调用一次）。
    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers("ceo-1", "ceo"),
        json={"approved": True},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["execution"] == {"outcome": "executed", "code": 201}
    assert wired["executor"].call_count == 1
    # 027 行被置 approved（唯一授权权威）。
    assert wired["actions"].get(TENANT, rows[0].action_id).status is ToolActionStatus.APPROVED

    # 审批后的执行**不回写**幂等行：重放该键仍返回首次的 202。
    replay = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers={**headers(), "Idempotency-Key": "flow-1"},
        json={"content": content},
    )
    assert replay.status_code == 202
    assert replay.json() == body
    assert wired["executor"].call_count == 1  # 重放不二次执行


# ------------------------- 用例 33②：响应体不含正文 / 密文 / 宿主路径 / 凭据（P0）


def _create_conversation() -> str:
    return client.post(
        "/api/v1/conversations", headers=headers(), json={"agent_key": AGENT}
    ).json()["conversation_id"]


def _send(conversation_id: str, body: str, *, key: str):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(), "Idempotency-Key": key},
        json={"content": body},
    )


def _assert_clean(text: str, *forbidden: str) -> None:
    for item in forbidden:
        assert item not in text, item


def test_usecase_33_2_bodies_carry_no_body_cipher_or_host_path(wired, tmp_path) -> None:
    """用例 33②（§3.4 约束 3 / 契约「审计与落库口径」）：`202` / `201` / 决议响应体均不泄密。

    逐条断言：**正文原文**、**密文（hex）**、**宿主路径**、**凭据**都不得出现在任何响应体里。
    """
    conversation = _create_conversation()
    body_text = "机密正文-用例33②"
    invocation = json.dumps(
        {"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": body_text}}
    )

    pending = _send(conversation, invocation, key="leak-1")
    assert pending.status_code == 202, pending.text
    run_id, approval_id = pending.json()["run_id"], pending.json()["approval_id"]
    row = wired["actions"].list_for_run(TENANT, run_id)[0]
    cipher_hex = bytes(row.body_ciphertext).hex()

    # 202 响应体：不含正文 / 密文 / 宿主路径 / 凭据。
    _assert_clean(pending.text, body_text, cipher_hex, str(tmp_path), "api_key", "secret")

    # 决议端点响应体（审批通过 → 同一请求内重跑执行）。
    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers("ceo-1", "ceo"),
        json={"approved": True},
    )
    assert decided.status_code == 200, decided.text
    _assert_clean(decided.text, body_text, cipher_hex, str(tmp_path), "api_key", "secret")

    # 201 响应体（无需审批、同请求内执行完成的工具）。
    executed = _send(
        conversation,
        json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}}),
        key="leak-2",
    )
    assert executed.status_code == 201, executed.text
    _assert_clean(executed.text, body_text, cipher_hex, str(tmp_path), "api_key", "secret")


# ------------------------------- 用例 33④：日志中 grep 不到正文与密文（P0）


def test_usecase_33_4_logs_contain_no_body_or_ciphertext(wired, caplog) -> None:
    """用例 33④（§3.4 约束 1）：跑完整条链路后，**日志里查不到正文原文与密文**。"""
    conversation = _create_conversation()
    body_text = "机密正文-用例33④"
    invocation = json.dumps(
        {"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": body_text}}
    )

    with caplog.at_level(logging.DEBUG):
        pending = _send(conversation, invocation, key="log-1")
        assert pending.status_code == 202, pending.text
        run_id, approval_id = pending.json()["run_id"], pending.json()["approval_id"]
        row = wired["actions"].list_for_run(TENANT, run_id)[0]
        cipher_hex = bytes(row.body_ciphertext).hex()
        decided = client.post(
            f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
            headers=headers("ceo-1", "ceo"),
            json={"approved": True},
        )
        assert decided.status_code == 200, decided.text

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert body_text not in logs
    assert cipher_hex not in logs
