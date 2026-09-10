import pytest

from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, RiskLevel, Task, TaskStatus, UserContext
from app.planner.generator import MockPlanGenerator
from app.planner.models import (
    PlanGenerationError,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
    PlannerAccessDenied,
    PlannerNotConfigured,
    Tool,
    ToolCatalog,
)
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.service import RuntimeService


class RecordingRuntimeService(RuntimeService):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict], str]] = []

    def start(self, actor, task_id, runtime_key, steps, mode):  # type: ignore[override]
        self.calls.append((task_id, runtime_key, steps, mode))
        return "run-1", runtime_key, "policy-1"


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )


def make_task(task_store, *, created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"id-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    owner = UserContext("t-1", created_by, "employee")
    task_store.create(owner, task)
    return task


def service(task_store, runtime=None, *, tools: ToolCatalog | None = None) -> PlannerService:
    return PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=tools if tools is not None else catalog(),
        runtime_service=runtime or RecordingRuntimeService(),
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
    )


def test_propose_generates_pending_proposal_with_server_derived_steps() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)

    proposal = planner.propose(
        UserContext("t-1", "u-1", "employee"), task.id, "整理本周公众号选题", "key-1"
    )

    assert proposal.status is PlanStatus.PENDING_REVIEW
    assert proposal.steps[0].tool == "knowledge.search"
    assert proposal.steps[0].requires_approval is False
    assert proposal.generator_key == "mock"


def test_propose_is_idempotent_per_task_and_key() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    actor = UserContext("t-1", "u-1", "employee")

    first = planner.propose(actor, task.id, "目标", "key-1")
    second = planner.propose(actor, task.id, "另一个目标", "key-1")

    assert first.proposal_id == second.proposal_id
    assert len(planner.store.list_for_task("t-1", task.id)) == 1


def test_propose_hides_task_from_other_employee() -> None:
    from app.domain import TaskNotFound, TaskStore

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(TaskNotFound):
        service(task_store).propose(UserContext("t-1", "u-9", "employee"), task.id, "目标", "key-1")


def test_propose_requires_configured_tools() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(PlannerNotConfigured, match="未配置任何可用工具"):
        service(task_store, tools=ToolCatalog()).propose(
            UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1"
        )


def test_propose_hides_cross_tenant_task() -> None:
    from app.domain import TaskStore, TaskNotFound

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(TaskNotFound):
        service(task_store).propose(UserContext("t-other", "u-1", "employee"), task.id, "目标", "key-1")


def test_only_ceo_or_super_admin_can_approve_and_creator_cannot_self_approve() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PolicyError):
        planner.approve(UserContext("t-1", "u-1", "employee"), proposal.proposal_id)
    with pytest.raises(PolicyError, match="发起人"):
        planner.approve(UserContext("t-1", "u-1", "ceo"), proposal.proposal_id)
    approved = planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    assert approved.status is PlanStatus.APPROVED
    assert approved.reviewed_by == "ceo-1"


def test_reject_requires_ceo_and_records_reason() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    rejected = planner.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "步骤不完整")

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.rejection_reason == "步骤不完整"


def test_run_requires_approved_status_and_uses_runtime_service() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    runtime = RecordingRuntimeService()
    planner = service(task_store, runtime)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PlanProposalStateConflict, match="审批"):
        planner.start_run(UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager")

    planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)
    run_id, runtime_key, policy_version = planner.start_run(
        UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager"
    )

    assert (run_id, runtime_key, policy_version) == ("run-1", "mock", "policy-1")
    assert runtime.calls[0][0] == task.id
    assert runtime.calls[0][2] == [{"step_id": "step-1", "tool": "knowledge.search", "kind": "read"}]


def test_get_hides_other_tenant_proposal() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PlanProposalNotFound):
        planner.get(UserContext("t-other", "u-1", "employee"), proposal.proposal_id)


def test_approval_of_unknown_proposal_is_not_found() -> None:
    from app.domain import TaskStore

    planner = service(TaskStore())

    with pytest.raises(PlanProposalNotFound):
        planner.approve(UserContext("t-1", "ceo-1", "ceo"), "plan-missing")


def test_generation_failure_does_not_persist_a_proposal() -> None:
    from app.domain import TaskStore

    class ExplodingGenerator:
        key = "mock"
        model_name = None

        def generate(self, goal, *, catalog, max_steps):
            raise PlanGenerationError("模型调用失败")

    task_store = TaskStore()
    task = make_task(task_store)
    planner = PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=ExplodingGenerator(),
        catalog=catalog(),
        runtime_service=RecordingRuntimeService(),
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
    )

    with pytest.raises(PlanGenerationError):
        planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    assert planner.store.list_for_task("t-1", task.id) == []


def test_propose_rejects_blank_goal() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(ValueError, match="目标不能为空"):
        service(task_store).propose(UserContext("t-1", "u-1", "employee"), task.id, "   ", "key-1")


def test_reject_requires_reason_and_non_ceo_is_rejected() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PolicyError):
        planner.reject(UserContext("t-1", "u-2", "employee"), proposal.proposal_id, "原因")
    with pytest.raises(ValueError, match="驳回原因不能为空"):
        planner.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "   ")


def test_duplicate_approval_conflicts() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")
    planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    with pytest.raises(PlanProposalStateConflict):
        planner.approve(UserContext("t-1", "ceo-2", "ceo"), proposal.proposal_id)


def test_get_and_run_deny_other_employee_on_same_tenant_proposal() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PlannerAccessDenied):
        planner.get(UserContext("t-1", "u-2", "employee"), proposal.proposal_id)
    with pytest.raises(PlannerAccessDenied):
        planner.start_run(UserContext("t-1", "u-2", "employee"), proposal.proposal_id, "mock", "product_manager")
