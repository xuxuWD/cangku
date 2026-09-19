"""运行生命周期 → 运行记录的回写，以及 Mock 运行时的确定性失败路径。

先写测试：`RuntimeService` 在 start / pause / resume / cancel 后都回写记录；`fail.` 前缀工具必定失败。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.authorization import ExecutionNotAuthorized
from app.runtime.contracts import AgentPlan, RunNotActionable, RuntimeContext
from app.runtime.mock import MockRuntime
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RunAccessDenied, RuntimeService
from app.runtime.state import RuntimeStateStore

OWNER = UserContext("t-1", "u-1", "employee")
READ_STEPS = [{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]
# 待审批步骤：运行停在「运行中」（终态不可再干预，故干预类用例必须用非终态运行）。
PENDING_STEPS = [{"step_id": "s1", "kind": "write", "tool": "fs.write", "requires_approval": True}]


def runtime_context() -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id="u-1",
        role_key="content-operator",
        mode="product_manager",
        project_id=None,
        task_id="task-1",
        device_id="device:u-1",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def make_task(task_store: TaskStore, *, created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"run-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", created_by, "employee"), task)
    return task


def build(*, with_metrics: bool = True):
    task_store = TaskStore()
    task = make_task(task_store)
    record_store = InMemoryRunRecordStore() if with_metrics else None
    metrics = RunMetricsService(record_store) if record_store is not None else None
    runtime = RuntimeService(task_store, run_metrics=metrics)
    return runtime, record_store, task_store, task


def test_start_writes_run_record_with_finish_reason() -> None:
    runtime, records, _store, task = build()

    run_id, runtime_key, _policy = runtime.start(
        OWNER, task.id, "mock", READ_STEPS, "product_manager"
    )

    record = records.get("t-1", run_id)
    assert runtime_key == "mock"
    assert record.task_id == task.id
    assert record.status == "completed"
    assert record.finish_reason == "run_completed"
    assert record.proposal_id is None
    assert record.finished_at is not None


def test_start_passes_proposal_id_through() -> None:
    runtime, records, _store, task = build()

    run_id, _key, _policy = runtime.start(
        OWNER, task.id, "mock", READ_STEPS, "product_manager", proposal_id="plan-1"
    )

    assert records.get("t-1", run_id).proposal_id == "plan-1"


def test_pause_and_resume_rewrite_the_same_record() -> None:
    runtime, records, _store, task = build()
    # 终态不可再干预 ⇒ 用「停在运行中」的运行（待审批步骤）验证暂停 / 恢复。
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", PENDING_STEPS, "product_manager")
    started_at = records.get("t-1", run_id).started_at

    runtime.pause(OWNER, run_id, "等待确认")
    paused = records.get("t-1", run_id)

    assert paused.status == "paused"
    assert paused.finish_reason is None
    assert paused.finished_at is None
    assert paused.started_at == started_at

    runtime.resume(OWNER, run_id)

    assert records.get("t-1", run_id).status == "running"


def test_cancel_records_terminal_state() -> None:
    runtime, records, _store, task = build()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", PENDING_STEPS, "product_manager")

    runtime.cancel(OWNER, run_id, "测试取消")

    record = records.get("t-1", run_id)
    assert record.status == "cancelled"
    assert record.finish_reason == "cancelled_by_user"
    assert record.finished_at is not None


def test_terminal_run_cannot_be_intervened_again() -> None:
    """终态即终态：已完成的运行上暂停 / 恢复 / 取消一律拒绝（RunNotActionable）。"""
    runtime, records, _store, task = build()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", READ_STEPS, "product_manager")

    with pytest.raises(RunNotActionable):
        runtime.pause(OWNER, run_id, "再暂停")
    with pytest.raises(RunNotActionable):
        runtime.resume(OWNER, run_id)
    with pytest.raises(RunNotActionable):
        runtime.cancel(OWNER, run_id, "再取消")

    assert records.get("t-1", run_id).status == "completed"


def test_control_actions_are_denied_for_other_users() -> None:
    runtime, _records, _store, task = build()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", READ_STEPS, "product_manager")

    with pytest.raises(RunAccessDenied):
        runtime.cancel(UserContext("t-1", "u-2", "employee"), run_id, "越权")


def test_runtime_without_metrics_still_works() -> None:
    runtime, records, _store, task = build(with_metrics=False)

    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", PENDING_STEPS, "product_manager")
    runtime.pause(OWNER, run_id, "等待确认")
    # 段二 §3.2 收窄：未装配运行记录仓储时，启动执行闸门必须 fail-closed（不再静默放行）。
    with pytest.raises(ExecutionNotAuthorized):
        runtime.resume(OWNER, run_id)
    runtime.cancel(OWNER, run_id, "测试取消")

    assert records is None


def test_mock_fail_tool_fails_immediately_and_stops() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    steps = [
        {"step_id": "s1", "kind": "read", "tool": "fail.step"},
        {"step_id": "s2", "kind": "read", "tool": "knowledge.search"},
    ]

    run_id = runtime.start_run(runtime_context(), AgentPlan.from_steps(steps))
    state = store.get(run_id)
    events = store.list_events(run_id)

    assert state.status == "failed"
    assert state.usage == {"tool_calls": 1, "successful_tools": 0}
    assert state.completed_steps == []
    # 事件已迁到 append-only 表（2026-09-16 改造）：从存储读取，而非状态行内的数组。
    assert [event.event_type.value for event in events][-1] == "run.failed"
    assert all(event.payload.get("step_id") != "s2" for event in events)
    assert store.get(run_id).checkpoint["status"] == "failed"


def test_mock_read_only_plan_still_completes() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)

    run_id = runtime.start_run(runtime_context(), AgentPlan.from_steps(READ_STEPS))

    assert store.get(run_id).status == "completed"
