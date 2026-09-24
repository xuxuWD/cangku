"""推进处（审批决议）的 O3 派生授权重判 —— **TDD 失败测试（先红后绿）**。

真源（**先于实现落定**）：
    `docs/api-contract.md`「会话协作：分享与多端协同（P2c-6）」节
      ・「**使用权的传递上限（O3 · 派生授权 —— 2026-09-24 用户裁决）**」
      ・其末「**⚠️ 推进处（审批决议）同样重判 —— 2026-09-25 补**」条

**修前现象（红）**：归属人 `u-1` 给 `u-9` 加 `use` 档 → `u-9` 自建会话发 `fs.write` 得 `202` 待批 →
`remove_share` 撤销 → 同一 `run` 的待批动作**仍**经 `POST /runs/{run_id}/approvals/{approval_id}/approval`
被 CEO 批准（`200`）且 `executor` 被调用一次（工具**真实执行**）—— 契约「执行期**每次**重判 /
发起人失去 `use` 后成员**立即**失去传递权」在**待批路径**上不成立。

**修后（绿）**：撤销后该决议端点 `403`，`executor` **零**调用，`027` 待批行仍 `PENDING`（不落决议）。

对照（control）：不撤销时同一路径 `200` 且 `executor` 调用一次 —— 证明 `403` 确由**撤销**产生，
而不是别的什么恰好拦住了它（反假）。
"""

from __future__ import annotations

import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import Account, AccountStatus
from app.accounts.repository import InMemoryAccountRepository
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
TENANT = "t-approval"
OWNER = "u-1"     # 归属人：亲手创建了 AGENT（owner_user_id = u-1）
USER = "u-9"      # 拿到 `use` 档共享的人；自建会话绑 AGENT
CEO = "ceo-1"     # 决议人（CEO）

# 需审批的副作用工具（`fs.write`：`requires_approval=True`）⇒ 对话入口带键执行落 `202` 待批。
WRITE_CALL = json.dumps(
    {"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": "机密正文"}}
)


def _owner_uid() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


def owner_context() -> UserContext:
    return UserContext(TENANT, OWNER, "employee")


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """与生产同口径的装配：账号 / 会话 / 运行时 / 目录（AGENT 归属 `OWNER`）＋真实工具执行服务。"""
    accounts = InMemoryAccountRepository()
    for index, (account_id, role) in enumerate(
        [(OWNER, "employee"), (USER, "employee"), (CEO, "ceo")]
    ):
        accounts.add(
            Account(
                phone=f"1390002{index:04d}",
                password_hash="hash",
                position="岗位",
                full_name=f"姓名-{account_id}",
                account_id=account_id,
                role=role,
                tenant_id=TENANT,
                status=AccountStatus.APPROVED,
            )
        )

    task_store = TaskStore()
    run_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(run_store)
    action_store = InMemoryToolActionStore()
    runtime = RuntimeService(task_store, run_metrics=metrics, tool_actions=action_store)
    audit = AuditService(InMemoryAuditStore())
    conv_store = InMemoryConversationStore()
    # `accounts` 是「发起人是否超管」的解析来源 —— 与 `app/main.py` 装配同口径（显式传入，非回落）。
    conversations = ConversationService(conv_store, audit=audit, accounts=accounts)
    idempotency = InMemoryExecutionIdempotencyStore()
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    # O3 派生授权：AGENT 归属人 = `OWNER`（`u-1`）；本文件核心是「授权经会话传递后再撤销」。
    directory.create_employee(owner_context(), agent_key=AGENT, name="内容员工", role_key="writer")

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
        accounts=accounts,
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
        "executor": executor,
        "actions": action_store,
        "directory": directory,
        "idempotency": idempotency,
    }


def headers(user_id: str = OWNER, role: str = "employee") -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": user_id, "X-User-Role": role}


def ceo() -> dict[str, str]:
    return headers(CEO, "ceo")


def _grant_use(directory) -> None:
    directory.add_share(owner_context(), AGENT, grantee_user_id=USER, permission="use")


def _create_pending(wired) -> tuple[str, str, str]:
    """`u-9` 自建会话绑 AGENT（此时持有 `use`）→ 发 `fs.write` ⇒ `202` 待批，返回 (会话, run, approval)。"""
    created = client.post(
        "/api/v1/conversations", headers=headers(USER), json={"agent_key": AGENT}
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation_id"]
    pending = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(USER), "Idempotency-Key": "approval-1"},
        json={"content": WRITE_CALL},
    )
    assert pending.status_code == 202, pending.text
    body = pending.json()
    assert body["status"] == "pending_approval" and body["approval_id"]
    return conversation_id, body["run_id"], body["approval_id"]


# --------------------------------------------------- 对照：不撤销 ⇒ 决议正常推进执行


def test_control_pending_approval_executes_while_initiator_keeps_use(wired) -> None:
    """对照：`u-9` 的 `use` 档未被撤销 ⇒ CEO 决议批准 `200`，工具**真实执行**一次。"""
    _grant_use(wired["directory"])
    _conversation, run_id, approval_id = _create_pending(wired)

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=ceo(),
        json={"approved": True},
    )

    assert decided.status_code == 200, decided.text
    assert decided.json()["execution"] == {"outcome": "executed", "code": 201}
    assert wired["executor"].call_count == 1


# --------------------------------------------------- 反向：撤销 ⇒ 待批不得被批准执行


def test_revoking_use_blocks_pending_approval_decision_and_execution(wired) -> None:
    """撤销 `use` 后，**已挂起**的待批动作不得经决议端点被批准并真实执行工具。

    断言三件事：`403` / `executor` 零调用 / `027` 待批行仍 `PENDING`（**不落决议**）。
    """
    _grant_use(wired["directory"])
    _conversation, run_id, approval_id = _create_pending(wired)

    assert wired["directory"].remove_share(owner_context(), AGENT, USER) is True

    blocked = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=ceo(),
        json={"approved": True},
    )

    assert blocked.status_code == 403, blocked.text
    assert wired["executor"].call_count == 0  # 工具**未被真实执行**
    rows = wired["actions"].list_for_run(TENANT, run_id)
    assert len(rows) == 1 and rows[0].status is ToolActionStatus.PENDING  # 不落决议
