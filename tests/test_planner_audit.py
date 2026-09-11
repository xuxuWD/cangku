from typing import NamedTuple

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.generator import MockPlanGenerator
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore


class RecordingRuntimeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, actor, task_id, runtime_key, steps, mode):
        self.calls.append((task_id, runtime_key, steps, mode))
        return "run-1", runtime_key, "policy-1"


class Harness(NamedTuple):
    service: PlannerService
    audits: InMemoryAuditStore
    runtime: RecordingRuntimeService
    task: Task


def build_harness() -> Harness:
    audits = InMemoryAuditStore()
    task_store = TaskStore()
    runtime = RecordingRuntimeService()
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="plan-audit-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", "u-1", "employee"), task)
    service = PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=ToolCatalog((Tool(name="knowledge.search", kind="read"),)),
        runtime_service=runtime,
        max_steps=5,
        audit=AuditService(audits),
    )
    return Harness(service=service, audits=audits, runtime=runtime, task=task)


def recorded(audits: InMemoryAuditStore) -> list[str]:
    return [item.action.value for item in audits.list_recent(None, limit=100)]


def test_propose_approve_and_run_are_audited() -> None:
    harness = build_harness()

    proposal = harness.service.propose(
        UserContext("t-1", "u-1", "employee"), harness.task.id, "整理选题", "key-1"
    )
    harness.service.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)
    harness.service.start_run(
        UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager"
    )

    actions = recorded(harness.audits)
    assert AuditAction.PLAN_PROPOSED.value in actions
    assert AuditAction.PLAN_APPROVED.value in actions
    assert AuditAction.PLAN_RUN_STARTED.value in actions


def test_reject_is_audited_and_not_approved() -> None:
    harness = build_harness()
    proposal = harness.service.propose(
        UserContext("t-1", "u-1", "employee"), harness.task.id, "整理选题", "key-1"
    )

    harness.service.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "步骤不完整")

    actions = recorded(harness.audits)
    assert AuditAction.PLAN_REJECTED.value in actions
    assert AuditAction.PLAN_APPROVED.value not in actions


def test_propose_audit_detail_has_step_count_and_generator_not_goal_text() -> None:
    harness = build_harness()

    harness.service.propose(UserContext("t-1", "u-1", "employee"), harness.task.id, "机密目标文本", "key-1")

    details = [item.detail for item in harness.audits.list_recent(None, limit=100)]
    assert {"step_count": 1, "generator": "mock", "data_classification": "internal"} in details
    assert "机密目标文本" not in str(details)


def test_run_audit_detail_contains_runtime_key() -> None:
    harness = build_harness()
    proposal = harness.service.propose(
        UserContext("t-1", "u-1", "employee"), harness.task.id, "整理选题", "key-1"
    )
    harness.service.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    harness.service.start_run(
        UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager"
    )

    details = [item.detail for item in harness.audits.list_recent(None, limit=100)]
    assert {"runtime_key": "mock", "run_id": "run-1"} in details


def test_reject_audit_detail_carries_reason() -> None:
    harness = build_harness()
    proposal = harness.service.propose(
        UserContext("t-1", "u-1", "employee"), harness.task.id, "整理选题", "key-1"
    )

    harness.service.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "资料不完整")

    details = [item.detail for item in harness.audits.list_recent(None, limit=100)]
    assert {"reason": "资料不完整"} in details
