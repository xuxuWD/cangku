"""审批人待办的租户级索引：存储遍历、服务层过滤与终态守卫。

先写测试：只列非终态运行里 status=pending 的审批；终态运行的审批不可再决议（缺陷回归）。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.contracts import AgentPlan, RunNotDecidable, RuntimeContext
from app.runtime.mock import MockRuntime
from app.runtime.service import RuntimeService
from app.runtime.state import RuntimeStateStore

OWNER = UserContext("t-1", "u-1", "employee")
CEO = UserContext("t-1", "ceo-1", "ceo")
TWO_WRITES = [
    {"step_id": "s1", "kind": "write", "tool": "file.write"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]
ONE_WRITE = [{"step_id": "s1", "kind": "write", "tool": "file.write"}]


def runtime_context(*, tenant_id: str = "t-1", user_id: str = "u-1", task_id: str = "task-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role_key="content-operator",
        mode="product_manager",
        project_id=None,
        task_id=task_id,
        device_id=f"device:{user_id}",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def make_task(task_store: TaskStore, *, tenant_id: str = "t-1", created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="待审批运行",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"todo-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext(tenant_id, created_by, "employee"), task)
    return task


def build_service():
    task_store = TaskStore()
    task = make_task(task_store)
    runtime = RuntimeService(task_store)
    return runtime, task_store, task


# ------------------------------------------------------------------ 存储索引


def test_state_store_lists_only_current_tenant() -> None:
    store = RuntimeStateStore()
    mine = store.create(runtime_context(tenant_id="t-1"), AgentPlan.from_steps(ONE_WRITE))
    store.create(runtime_context(tenant_id="t-2", user_id="u-9"), AgentPlan.from_steps(ONE_WRITE))

    found = store.list_for_tenant("t-1")

    assert [state.run_id for state in found] == [mine.run_id]
    assert store.list_for_tenant("t-3") == []


def test_state_records_creation_time() -> None:
    store = RuntimeStateStore()
    state = store.create(runtime_context(), AgentPlan.from_steps(ONE_WRITE))

    assert state.created_at.tzinfo is not None
    assert state.created_at <= datetime.now(UTC)


# ------------------------------------------------------------ 服务层过滤


def test_list_only_covers_active_runs_with_pending_items() -> None:
    runtime, _store, task = build_service()
    pending_run, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_WRITES, "product_manager")
    rejected_run, _key2, _policy2 = runtime.start(OWNER, task.id, "mock", TWO_WRITES, "product_manager")
    runtime.decide_approval(CEO, rejected_run, "s1", False)

    items = runtime.list_pending_approvals(CEO, limit=50)

    assert [(item.run_id, item.approval_id) for item in items] == [
        (pending_run, "s1"),
        (pending_run, "s2"),
    ]
    # 终态运行的剩余 pending 不再出现（列出来也点不了）。
    assert all(item.run_id != rejected_run for item in items)


def test_list_skips_decided_items_and_respects_limit() -> None:
    runtime, _store, task = build_service()
    first, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_WRITES, "product_manager")
    second, _key2, _policy2 = runtime.start(OWNER, task.id, "mock", TWO_WRITES, "product_manager")
    runtime.decide_approval(CEO, first, "s1", True)

    items = runtime.list_pending_approvals(CEO, limit=1)

    assert len(items) == 1
    assert (items[0].run_id, items[0].approval_id) == (second, "s1")


def test_list_orders_by_creation_desc_and_carries_context() -> None:
    runtime, _store, task = build_service()
    older, _key, _policy = runtime.start(OWNER, task.id, "mock", ONE_WRITE, "product_manager")
    newer, _key2, _policy2 = runtime.start(OWNER, task.id, "mock", ONE_WRITE, "product_manager")
    runtime.state_store.get(older).created_at = datetime(2026, 9, 10, tzinfo=UTC)
    runtime.state_store.get(newer).created_at = datetime(2026, 9, 11, tzinfo=UTC)

    items = runtime.list_pending_approvals(CEO, limit=10)

    assert [item.run_id for item in items] == [newer, older]
    assert items[0].task_id == task.id
    assert items[0].requested_by == "u-1"
    assert items[0].step_id == "s1"
    assert items[0].tool == "file.write"
    assert items[0].created_at == datetime(2026, 9, 11, tzinfo=UTC)


def test_list_is_scoped_to_the_calling_tenant() -> None:
    runtime, task_store, _task = build_service()
    other_task = make_task(task_store, tenant_id="t-2", created_by="u-9")
    other_owner = UserContext("t-2", "u-9", "employee")
    runtime.start(other_owner, other_task.id, "mock", ONE_WRITE, "product_manager")

    assert runtime.list_pending_approvals(UserContext("t-1", "ceo-1", "ceo"), limit=50) == []
    assert len(runtime.list_pending_approvals(UserContext("t-2", "ceo-2", "ceo"), limit=50)) == 1


# -------------------------------------------------------------- 终态守卫


def test_deciding_after_terminal_state_is_rejected_and_keeps_status() -> None:
    store = RuntimeStateStore()
    mock = MockRuntime(store)
    run_id = mock.start_run(runtime_context(), AgentPlan.from_steps(TWO_WRITES))
    mock.decide_approval(run_id, "s1", False)
    assert store.get(run_id).status == "failed"

    with pytest.raises(RunNotDecidable):
        mock.decide_approval(run_id, "s2", True)

    state = store.get(run_id)
    assert state.status == "failed"
    assert state.approvals["s2"] == "pending"


def test_service_rejects_deciding_on_terminal_run() -> None:
    runtime, _store, task = build_service()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_WRITES, "product_manager")
    runtime.decide_approval(CEO, run_id, "s1", True)
    runtime.cancel(CEO, run_id, "测试取消")

    with pytest.raises(RunNotDecidable):
        runtime.decide_approval(CEO, run_id, "s2", True)
