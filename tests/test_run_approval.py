"""运行内审批决议：Mock 语义、权限校验与运行记录回写。

先写测试：决议通过要执行被批准的步骤并落到 completed；驳回要立即 failed 且不再执行。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.contracts import (
    AgentPlan,
    ApprovalAlreadyDecided,
    ApprovalNotFound,
    RuntimeContext,
)
from app.runtime.mock import MockRuntime
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RunApprovalDenied, RuntimeService
from app.runtime.state import RuntimeStateStore

OWNER = UserContext("t-1", "u-1", "employee")
DECIDER = UserContext("t-1", "ceo-1", "ceo")
TWO_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]


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


def plan(steps: list[dict] | None = None) -> AgentPlan:
    return AgentPlan.from_steps(steps or TWO_STEPS)


def make_task(task_store: TaskStore, *, created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"approval-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", created_by, "employee"), task)
    return task


def build_service(with_metrics: bool = True):
    task_store = TaskStore()
    task = make_task(task_store)
    record_store = InMemoryRunRecordStore() if with_metrics else None
    metrics = RunMetricsService(record_store) if record_store is not None else None
    return RuntimeService(task_store, run_metrics=metrics), record_store, task


# --------------------------------------------------------------- Mock 语义


def test_approving_step_executes_it_and_completes_the_run() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(runtime_context(), plan())
    assert store.get(run_id).status == "running"

    runtime.decide_approval(run_id, "s2", True)

    state = store.get(run_id)
    assert state.status == "completed"
    assert state.approvals["s2"] == "approved"
    assert state.completed_steps == ["s1", "s2"]
    assert state.usage == {"tool_calls": 2, "successful_tools": 2}
    assert [event.event_type.value for event in state.events][-1] == "run.completed"
    assert store.get(run_id).checkpoint["status"] == "completed"


def test_rejecting_approval_fails_the_run_without_executing_the_step() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(runtime_context(), plan())

    runtime.decide_approval(run_id, "s2", False)

    state = store.get(run_id)
    assert state.status == "failed"
    assert state.approvals["s2"] == "rejected"
    assert "s2" not in state.completed_steps
    assert not any(event.event_type.value == "run.completed" for event in state.events)
    failed = [event for event in state.events if event.event_type.value == "run.failed"]
    assert failed[-1].payload["approval_id"] == "s2"
    assert failed[-1].payload["reason"] == "approval_rejected"


def test_approval_requires_leaving_no_pending_items_before_completing() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    steps = [
        {"step_id": "s1", "kind": "write", "tool": "file.write"},
        {"step_id": "s2", "kind": "write", "tool": "file.write"},
    ]
    run_id = runtime.start_run(runtime_context(), plan(steps))

    runtime.decide_approval(run_id, "s1", True)
    assert store.get(run_id).status == "running"

    runtime.decide_approval(run_id, "s2", True)
    assert store.get(run_id).status == "completed"


def test_unknown_or_repeated_decision_is_rejected() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(runtime_context(), plan())

    with pytest.raises(ApprovalNotFound):
        runtime.decide_approval(run_id, "nope", True)

    runtime.decide_approval(run_id, "s2", True)
    with pytest.raises(ApprovalAlreadyDecided):
        runtime.decide_approval(run_id, "s2", False)


# ------------------------------------------------------- 权限与记录回写


def test_decider_must_be_elevated_and_not_the_author() -> None:
    runtime, _records, task = build_service()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_STEPS, "product_manager")

    with pytest.raises(RunApprovalDenied):
        runtime.decide_approval(OWNER, run_id, "s2", True)

    author_as_ceo = UserContext("t-1", "u-1", "ceo")
    with pytest.raises(RunApprovalDenied):
        runtime.decide_approval(author_as_ceo, run_id, "s2", True)


def test_approval_rewrites_run_record_as_completed() -> None:
    runtime, records, task = build_service()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_STEPS, "product_manager")
    assert records.get("t-1", run_id).status == "running"
    started_at = records.get("t-1", run_id).started_at

    runtime.decide_approval(DECIDER, run_id, "s2", True)

    record = records.get("t-1", run_id)
    assert record.status == "completed"
    assert record.finish_reason == "run_completed"
    assert record.finished_at is not None
    assert record.started_at == started_at


def test_rejected_approval_lands_on_approval_rejected() -> None:
    runtime, records, task = build_service()
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_STEPS, "product_manager")

    runtime.decide_approval(DECIDER, run_id, "s2", False)

    record = records.get("t-1", run_id)
    assert record.status == "failed"
    assert record.finish_reason == "approval_rejected"


def test_step_failure_still_maps_to_step_failed() -> None:
    runtime, records, task = build_service()
    run_id, _key, _policy = runtime.start(
        OWNER, task.id, "mock", [{"step_id": "s1", "kind": "read", "tool": "fail.step"}], "product_manager"
    )

    assert records.get("t-1", run_id).finish_reason == "step_failed"


def test_service_without_metrics_still_decides() -> None:
    runtime, records, task = build_service(with_metrics=False)
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_STEPS, "product_manager")

    runtime.decide_approval(DECIDER, run_id, "s2", True)

    assert records is None
    assert runtime.snapshot(DECIDER, run_id).status == "completed"
