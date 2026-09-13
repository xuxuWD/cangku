"""执行授权位：写入、撤销、执行前比对，以及「状态回写不得抹掉授权」（段一规格 §2.3）。

先写测试：授权位是**针对某一个具体计划**的凭证，计划在批准后变更即视为失效。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.authorization import (
    AUTHORIZATION_SOURCES,
    ExecutionAuthorization,
    ExecutionNotAuthorized,
    InvalidAuthorizationSource,
    ensure_source_allowed,
    plan_digest,
)
from app.runtime.contracts import AgentPlan
from app.runtime.records import InMemoryRunRecordStore, RunRecord, RunRecordNotFound
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService

OWNER = UserContext("t-1", "u-1", "employee")
DECIDER = UserContext("t-1", "ceo-1", "ceo")
TWO_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]
MODE = "product_manager"


def make_task(task_store: TaskStore) -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="授权位用例",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="authorization-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(OWNER, task)
    return task


def build_service() -> tuple[RuntimeService, InMemoryRunRecordStore, Task]:
    task_store = TaskStore()
    task = make_task(task_store)
    record_store = InMemoryRunRecordStore()
    return RuntimeService(task_store, run_metrics=RunMetricsService(record_store)), record_store, task


def start_run(service: RuntimeService, task: Task) -> str:
    run_id, _key, _version = service.start(OWNER, task.id, "mock", TWO_STEPS, MODE)
    return run_id


def authorization(plan_digest_value: str = "a" * 64) -> ExecutionAuthorization:
    return ExecutionAuthorization(
        authorized_by="u-ceo", plan_digest=plan_digest_value, authorized_at=datetime.now(UTC)
    )


# --------------------------------------------------------------- 授权来源白名单


def test_all_whitelisted_sources_are_accepted() -> None:
    for source in AUTHORIZATION_SOURCES:
        assert ensure_source_allowed(source) == source


@pytest.mark.parametrize("source", ["agent", "employee", "digital_employee", "", "USER"])
def test_agent_and_unknown_sources_are_rejected(source: str) -> None:
    """`agent` 被显式拒绝：数字员工不能批准自己要执行的动作。"""
    with pytest.raises(InvalidAuthorizationSource):
        ensure_source_allowed(source)


def test_decide_approval_rejects_agent_source_without_writing_authorization() -> None:
    service, record_store, task = build_service()
    run_id = start_run(service, task)

    with pytest.raises(InvalidAuthorizationSource):
        service.decide_approval(DECIDER, run_id, "s2", True, source="agent")

    assert record_store.get("t-1", run_id).execution_authorization is None


# --------------------------------------------------------------- 计划摘要


def test_plan_digest_is_stable_and_sensitive_to_every_executed_field() -> None:
    base = AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}])
    same = AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}])
    other_tool = AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "web.search"}])
    other_kind = AgentPlan.from_steps([{"step_id": "s1", "kind": "write", "tool": "knowledge.search"}])
    other_step = AgentPlan.from_steps([{"step_id": "s9", "kind": "read", "tool": "knowledge.search"}])
    approval_flipped = AgentPlan.from_steps(
        [{"step_id": "s1", "kind": "read", "tool": "knowledge.search", "requires_approval": True}]
    )

    digest = plan_digest(base)
    assert len(digest) == 64
    assert digest == plan_digest(same)
    for changed in (other_tool, other_kind, other_step, approval_flipped):
        assert plan_digest(changed) != digest


# --------------------------------------------------------------- 仓储语义


def test_upsert_does_not_clobber_existing_authorization() -> None:
    """状态回写（upsert 一份不含授权的记录）不得抹掉授权位。"""
    store = InMemoryRunRecordStore()
    record = RunRecord(
        run_id="run-1",
        tenant_id="t-1",
        task_id="task-1",
        runtime_key="mock",
        status="running",
        started_at=datetime.now(UTC),
    )
    store.upsert(record)
    saved = authorization()
    store.set_execution_authorization("t-1", "run-1", saved)

    store.upsert(replace(record, status="completed"))

    assert store.get("t-1", "run-1").execution_authorization == saved


def test_set_execution_authorization_revokes_and_is_tenant_scoped() -> None:
    store = InMemoryRunRecordStore()
    store.upsert(
        RunRecord(
            run_id="run-1",
            tenant_id="t-1",
            task_id="task-1",
            runtime_key="mock",
            status="running",
            started_at=datetime.now(UTC),
        )
    )
    store.set_execution_authorization("t-1", "run-1", authorization())
    assert store.get("t-1", "run-1").execution_authorization is not None

    revoked = store.set_execution_authorization("t-1", "run-1", None)
    assert revoked.execution_authorization is None

    with pytest.raises(RunRecordNotFound):
        store.set_execution_authorization("t-other", "run-1", authorization())
    with pytest.raises(RunRecordNotFound):
        store.set_execution_authorization("t-1", "run-missing", authorization())


# --------------------------------------------------------------- 审批写入 / 驳回撤销


def test_approval_writes_authorization_for_the_approved_plan() -> None:
    service, record_store, task = build_service()
    run_id = start_run(service, task)
    expected_digest = plan_digest(service.snapshot(DECIDER, run_id).plan)

    service.decide_approval(DECIDER, run_id, "s2", True)

    saved = record_store.get("t-1", run_id).execution_authorization
    assert saved is not None
    assert saved.authorized_by == DECIDER.user_id
    assert saved.plan_digest == expected_digest
    assert saved.authorized_at.tzinfo is not None


def test_rejection_revokes_any_existing_authorization() -> None:
    """两个待审批项：通过第一个会写入授权，驳回第二个必须把它撤销。"""
    three_steps = [
        {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
        {"step_id": "s2", "kind": "write", "tool": "file.write"},
        {"step_id": "s3", "kind": "delete", "tool": "file.delete"},
    ]
    task_store = TaskStore()
    task = make_task(task_store)
    record_store = InMemoryRunRecordStore()
    service = RuntimeService(task_store, run_metrics=RunMetricsService(record_store))
    run_id, _key, _version = service.start(OWNER, task.id, "mock", three_steps, MODE)

    service.decide_approval(DECIDER, run_id, "s2", True)
    assert record_store.get("t-1", run_id).execution_authorization is not None

    service.decide_approval(DECIDER, run_id, "s3", False)

    assert record_store.get("t-1", run_id).execution_authorization is None


# --------------------------------------------------------------- 执行前闸门


def test_resume_passes_when_plan_matches_authorization() -> None:
    service, _record_store, task = build_service()
    run_id = start_run(service, task)
    service.decide_approval(DECIDER, run_id, "s2", True)

    service.resume(DECIDER, run_id)  # 不抛即通过


def test_resume_is_refused_when_plan_changed_after_approval() -> None:
    """反假测试：把「比对摘要」改成「只比对是否授权过」，本用例必须变红。"""
    service, _record_store, task = build_service()
    run_id = start_run(service, task)
    service.decide_approval(DECIDER, run_id, "s2", True)

    state = service.snapshot(DECIDER, run_id)
    state.plan = AgentPlan.from_steps(
        [
            {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "s2", "kind": "delete", "tool": "file.delete"},
        ]
    )

    with pytest.raises(ExecutionNotAuthorized):
        service.resume(DECIDER, run_id)


def test_guard_passes_for_run_without_authorization() -> None:
    """计划里没有需要审批的步骤 → 非「审批驱动」的运行，闸门不拦（保持既有行为）。"""
    service, _record_store, task = build_service()
    run_id = start_run(service, task)
    state = service.snapshot(DECIDER, run_id)

    service.ensure_execution_authorized(DECIDER, run_id, state.plan)


def test_guard_refuses_when_run_record_is_missing() -> None:
    service, _record_store, _task = build_service()

    with pytest.raises(ExecutionNotAuthorized):
        service.ensure_execution_authorized(DECIDER, "run-missing", AgentPlan.from_steps([]))


def test_guard_is_fail_closed_when_run_records_are_not_wired() -> None:
    """段二规格 §3.2「两条必须收窄的既有实现」：`run_records is None` 必须**拒绝**（不得静默放行）。"""
    service = RuntimeService(TaskStore())

    with pytest.raises(ExecutionNotAuthorized):
        service.ensure_execution_authorized(DECIDER, "run-x", AgentPlan.from_steps([]))
