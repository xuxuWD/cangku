"""段二-4 对话入口路由的接口层用例（规格 §3.7 Y2 / §3.2 第四条 / §4.1.3）。

覆盖：缺键 ⇒ 既有 `stub=true` 通路（不创建任何东西）、带键 ⇒ 承载任务 + Run + 工具执行、
四态幂等（`201 executed` / `202 pending_approval` / `rejected` / `failed`）、重放返回既有结果且
**不二次执行**、`agent_key` 校验收紧（执行入口 `422`）、`503` 不写幂等表。

真源：
    docs/superpowers/specs/2026-09-12-dsh-integration-design.md §3.7 Y2 / §3.2 / §4.1.3
    docs/api-contract.md「工具执行（P2a 段二）」变更点 1/2/4/5
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.domain import TaskStore, TaskStatus, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.errors import ToolExecutionError
from app.tool_execution.service import ToolExecutionResult
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

AGENT = "content-writer"
TENANT = "t-1"
EMPLOYEE = "u-1"


class FakeToolExecution:
    """打桩的工具执行入口：记录 `execute` 调用次数并返回受控结果 / 抛受控异常。"""

    def __init__(self, *, result=None, error: ToolExecutionError | None = None) -> None:
        self.calls = 0
        self.requests = []
        self._result = result if result is not None else ToolExecutionResult(outcome="executed", code=201)
        self._error = error

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    task_store = TaskStore()
    run_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(run_store)
    runtime = RuntimeService(task_store, run_metrics=metrics)
    conv_store = InMemoryConversationStore()
    audit = AuditService(InMemoryAuditStore())
    conversations = ConversationService(conv_store, audit=audit)
    idempotency = InMemoryExecutionIdempotencyStore()
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    directory.create_employee(admin, agent_key=AGENT, name="内容员工", role_key="writer")

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    return {
        "tasks": task_store,
        "runs": run_store,
        "conversations": conversations,
        "conv_store": conv_store,
        "idempotency": idempotency,
        "directory": directory,
    }


def wire_execution(monkeypatch, tool_execution, directory) -> ConversationExecutionService:
    service = ConversationExecutionService(
        conversations=main.conversation_service,
        conversation_store=main.conversation_store,
        task_store=main.store,
        runtime_service=main.runtime_service,
        tool_execution=tool_execution,
        idempotency=main.execution_idempotency_store,
        catalog=build_tool_spec_catalog(),
        audit=main.audit_service,
        directory_store=directory,
    )
    monkeypatch.setattr(main, "conversation_execution_service", service)
    return service


def headers(role: str = "employee", user_id: str = EMPLOYEE) -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(agent_key: str | None = AGENT) -> str:
    response = client.post("/api/v1/conversations", headers=headers(), json={"agent_key": agent_key})
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def invocation(tool_key: str, params: dict) -> str:
    return json.dumps({"tool_key": tool_key, "params": params})


def send(conversation_id: str, content: str, *, key: str | None = None, who: str = EMPLOYEE):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(user_id=who), **extra},
        json={"content": content},
    )


# ------------------------------------------------------------------ 缺键 ⇒ 既有 stub 通路


def test_missing_key_uses_stub_and_creates_nothing(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()

    response = send(conversation_id, "帮我看看今天的安排")  # 不带 Idempotency-Key

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stub"] is True
    assert body["reply"]["stub"] is True
    # 缺键 ⇒ 不触发真实执行：执行器 0 次调用、无承载任务 / 运行 / 幂等行。
    assert fake.calls == 0
    assert main.store.count_by_employee(TENANT) == {}
    assert main.run_metrics_service.store.list_recent(TENANT, limit=50) == []
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-1") is None


def test_missing_key_stub_is_unchanged_regression(monkeypatch, _isolate) -> None:
    """缺键路径必须是**既有** stub 通路：不带 `run_id: null` 之外不新增对外可见副作用。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()

    body = send(conversation_id, "你好").json()

    assert fake.calls == 0
    assert body["reply"]["role"] == "assistant"
    assert body["reply"]["content"].startswith("（P1 桩回复）")


# ------------------------------------------------------------------ 201 executed


def test_executed_creates_task_run_and_writes_idempotency(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()  # 默认 outcome=executed
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.list", {"path": "/workspace"})

    response = send(conversation_id, content, key="k-1")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stub"] is False
    assert body["run_id"]  # 承载运行的 run_id
    assert body["reply"]["role"] == "assistant"
    # 承载任务：employee_key = 会话绑定 agent_key，budget 0，幂等键 conv-{conv}-{key}。
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}
    runs = main.run_metrics_service.store.list_recent(TENANT, limit=50)
    assert len(runs) == 1
    assert runs[0].task_id == fake.requests[0].task_id
    # 幂等行：四态之一（executed / 201），message_id / run_id 均已落。
    row = main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-1")
    assert row is not None
    assert (row.outcome, row.http_status) == ("executed", 201)
    assert row.message_id == body["message_id"]
    assert row.run_id == body["run_id"]


def test_replay_returns_same_result_without_second_execution(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.list", {"path": "/workspace"})

    first = send(conversation_id, content, key="k-1")
    second = send(conversation_id, content, key="k-1")

    assert second.status_code == first.status_code == 201
    assert second.json() == first.json()  # 重放返回既有结果（逐字段相等）
    # 「不二次执行」：执行器只被调用一次；不新增承载任务 / 运行。
    assert fake.calls == 1
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}
    assert len(main.run_metrics_service.store.list_recent(TENANT, limit=50)) == 1


# ------------------------------------------------------------------ 202 pending_approval


def test_pending_approval_returns_202_and_is_replayable(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution(result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="appr-x"))
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    response = send(conversation_id, content, key="k-2")

    assert response.status_code == 202, response.text
    body = response.json()
    # 202 响应体：conversation_id / message_id / stub=false / status / run_id / approval_id（契约 :642）。
    assert body["stub"] is False
    assert body["status"] == "pending_approval"
    assert body["run_id"]
    assert body["approval_id"] == "appr-x"
    assert set(body) == {"conversation_id", "message_id", "stub", "status", "run_id", "approval_id"}

    replay = send(conversation_id, content, key="k-2")
    assert replay.status_code == 202
    assert replay.json() == body
    assert fake.calls == 1  # 重放不二次执行

    row = main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-2")
    assert (row.outcome, row.http_status) == ("pending_approval", 202)
    assert row.approval_id == "appr-x"


# ------------------------------------------------------------------ rejected / failed


@pytest.mark.parametrize("status", [403, 409, 422])
def test_rejected_writes_idempotency_and_replays_same_code(monkeypatch, _isolate, status: int) -> None:
    fake = FakeToolExecution(error=ToolExecutionError("执行被拒绝", http_status=status))
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    first = send(conversation_id, content, key="k-3")
    assert first.status_code == status

    row = main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-3")
    assert (row.outcome, row.http_status) == ("rejected", status)
    assert row.message_id is None

    replay = send(conversation_id, content, key="k-3")
    assert replay.status_code == status  # 重放返回既有结果码
    assert fake.calls == 1  # 重放不二次执行


@pytest.mark.parametrize("status", [502, 504])
def test_failed_writes_idempotency_and_replays_same_code(monkeypatch, _isolate, status: int) -> None:
    fake = FakeToolExecution(error=ToolExecutionError("执行失败", http_status=status))
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    first = send(conversation_id, content, key="k-4")
    assert first.status_code == status

    row = main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-4")
    assert (row.outcome, row.http_status) == ("failed", status)

    replay = send(conversation_id, content, key="k-4")
    assert replay.status_code == status
    assert fake.calls == 1


# ------------------------------------------------------------------ ⑥ 503 不写本表


def test_persist_failure_503_does_not_write_idempotency(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution(error=ToolExecutionError("审批请求暂时无法登记，请稍后重试", http_status=503))
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    first = send(conversation_id, content, key="k-5")
    assert first.status_code == 503
    # ⑥ 落库失败不写幂等表（同事务回滚，故不存在「首次 503」的行）。
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-5") is None

    # 重放该键会**重新走一遍闸门**（未产生任何消息 / 任务 / 运行 / 副作用，不违反幂等）。
    second = send(conversation_id, content, key="k-5")
    assert second.status_code == 503
    assert fake.calls == 2


def test_persist_failure_503_leaves_zero_residue_and_replays_gates(monkeypatch, _isolate) -> None:
    """⑥ 落库失败（`503`）：一次失败请求结束后**四项全零残留**（§4.1.3 J-5）。

    规格口径：⑥ 与本行属**同一事务**，⑥ 失败即整体回滚 ⇒ **不得**留下承载任务 / Run / 消息 / 幂等行
    中的任何一个；重放该键因幂等表确无该键而**重新走一遍闸门**（不违反幂等）。
    """
    fake = FakeToolExecution(error=ToolExecutionError("审批请求暂时无法登记，请稍后重试", http_status=503))
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    first = send(conversation_id, content, key="k-503")

    assert first.status_code == 503, first.text
    # ① 承载任务：0（本次新建的记录已被补偿撤销）
    assert main.store.count_by_employee(TENANT) == {}
    # ② Run：0（运行记录 + 进程内运行状态均被撤销）
    assert main.run_metrics_service.store.list_recent(TENANT, limit=50) == []
    assert main.runtime_service.state_store.list_for_tenant(TENANT) == []
    # ③ 消息：0（首次执行的消息只在 ⑥ 成功后才追加）
    context = UserContext(TENANT, EMPLOYEE, "employee")
    assert main.conversation_store.list_messages(context, conversation_id)[1] == 0
    # ④ 幂等行：0（故不存在「首次 503」的行）
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-503") is None

    # 重放同一键：幂等表确无该键 ⇒ **重新走一遍闸门**（执行器再被调用一次，仍零残留）。
    second = send(conversation_id, content, key="k-503")
    assert second.status_code == 503
    assert fake.calls == 2
    assert main.store.count_by_employee(TENANT) == {}
    assert main.run_metrics_service.store.list_recent(TENANT, limit=50) == []
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-503") is None


# ------------------------------------------------------------------ 承载任务 status 置 pending_approval


def test_pending_approval_sets_carrying_task_pending_approval(monkeypatch, _isolate) -> None:
    """§3.7 Y2：⑥ 落库成功（该动作进入等待审批）后，承载任务由建时的 `queued` 置 `pending_approval`。"""
    fake = FakeToolExecution(
        result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="appr-x")
    )
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("fs.write", {"path": "/workspace/a.txt", "content": "x"})

    response = send(conversation_id, content, key="k-pa")

    assert response.status_code == 202, response.text
    task_id = fake.requests[0].task_id
    task = main.store.get(UserContext(TENANT, EMPLOYEE, "employee"), task_id)
    assert task.status is TaskStatus.PENDING_APPROVAL


# ------------------------------------------------------------------ agent_key 收紧 / 输入非法


def test_agent_key_disabled_or_unknown_is_422(monkeypatch, _isolate) -> None:
    directory = _isolate["directory"]
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, directory)
    # 会话绑定一个**不存在**的员工（历史会话在员工停用后仍可读，但执行入口必须收紧）。
    conversation_id = create_conversation(agent_key="ghost-agent")
    content = invocation("fs.list", {"path": "/workspace"})

    response = send(conversation_id, content, key="k-6")

    assert response.status_code == 422, response.text
    assert fake.calls == 0  # 在创建任何东西之前拒绝
    assert main.store.count_by_employee(TENANT) == {}
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-6") is None


def test_agent_with_disabled_role_is_rejected_at_execution_entry(monkeypatch, _isolate) -> None:
    """岗位停用连带（§15 #11 / 段二 §1.4）：岗位停用后，绑定该岗位的 `agent_key` 在执行入口被拒。"""
    directory = _isolate["directory"]
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, directory)
    conversation_id = create_conversation()

    directory.update_role(UserContext(TENANT, "admin-1", "super_admin"), "writer", status="disabled")

    response = send(conversation_id, invocation("fs.list", {"path": "/workspace"}), key="k-role")

    assert response.status_code == 422, response.text
    assert fake.calls == 0  # 在创建任何东西之前拒绝
    assert main.store.count_by_employee(TENANT) == {}
    assert main.execution_idempotency_store.get(TENANT, EMPLOYEE, conversation_id, "k-role") is None


def test_conversation_without_agent_cannot_trigger_execution(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation(agent_key=None)
    content = invocation("fs.list", {"path": "/workspace"})

    response = send(conversation_id, content, key="k-7")

    assert response.status_code == 422
    assert fake.calls == 0


def test_non_structured_content_is_422(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()

    response = send(conversation_id, "就把这句话当命令执行吧", key="k-8")

    assert response.status_code == 422
    assert fake.calls == 0


def test_critical_tool_by_employee_is_403_before_creating(monkeypatch, _isolate) -> None:
    """§3.7 Y2 末行：`critical` 承载任务非 CEO/超管必须在 ① 之前 `403`，不得先建任务再拒。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate["directory"])
    conversation_id = create_conversation()
    content = invocation("artifact.export", {"path": "/workspace/a", "target": "x"})

    response = send(conversation_id, content, key="k-9")

    assert response.status_code == 403
    assert fake.calls == 0
    assert main.store.count_by_employee(TENANT) == {}
