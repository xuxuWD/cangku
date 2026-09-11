from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.generator import MockPlanGenerator
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService


def build_harness():
    task_store = TaskStore()
    audits = InMemoryAuditStore()
    metric_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(metric_store)
    runtime = RuntimeService(task_store, run_metrics=metrics)
    planner = PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=ToolCatalog((Tool(name="knowledge.search", kind="read"),)),
        runtime_service=runtime,
        max_steps=5,
        audit=AuditService(audits),
    )
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="run-wiring-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", "u-1", "employee"), task)
    return planner, metric_store, audits, task


def test_start_run_records_metrics_backfills_run_id_and_audits_run_id() -> None:
    planner, metric_store, audits, task = build_harness()
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "整理选题", "key-1")
    planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    run_id, runtime_key, _policy = planner.start_run(
        UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager"
    )

    assert runtime_key == "mock"
    reloaded = planner.store.get("t-1", proposal.proposal_id)
    assert reloaded.run_id == run_id

    record = metric_store.get("t-1", run_id)
    assert record.runtime_key == "mock"
    assert record.task_id == task.id
    assert record.proposal_id == proposal.proposal_id
    assert record.status == "completed"
    assert record.step_count == 1
    assert record.completed_step_count == 1

    details = [item.detail for item in audits.list_recent(None, limit=100)]
    assert {"runtime_key": "mock", "run_id": run_id} in details
    actions = [item.action for item in audits.list_recent(None, limit=100)]
    assert AuditAction.PLAN_RUN_STARTED in actions
