from __future__ import annotations

from typing import Any

import pytest

from app.agent_services import (
    ModelGateway,
    ModelNotAllowed,
    ModelRoute,
    ProviderModel,
)
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.classification import PLAN_GENERATION_CAPABILITY
from app.planner.generator import MockPlanGenerator
from app.planner.models import PlanStatus, Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore


class RecordingRuntimeService:
    def start(self, actor, task_id, runtime_key, steps, mode):
        return "run-1", runtime_key, "policy-1"


class StubPlanGenerator:
    """带有真实 model 名的生成器桩，模拟 openai_compatible 后端。"""

    key = "openai_compatible"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        catalog.require_configured()
        read_tools = [name for name in catalog.names() if catalog.resolve(name).kind == "read"]
        return [
            {"step_id": f"step-{index + 1}", "tool": name, "args": {"goal": goal.strip()}}
            for index, name in enumerate(read_tools[:max_steps])
        ]


def catalog() -> ToolCatalog:
    return ToolCatalog((Tool(name="knowledge.search", kind="read"),))


def make_task(task_store: TaskStore, *, risk_level: RiskLevel) -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=risk_level,
        budget=1,
        idempotency_key=f"gateway-{risk_level.value}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", "u-1", "employee"), task)
    return task


def build_planner(
    task_store: TaskStore,
    *,
    generator: Any,
    model_gateway: Any,
    audits: InMemoryAuditStore | None = None,
) -> PlannerService:
    return PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=generator,
        catalog=catalog(),
        runtime_service=RecordingRuntimeService(),
        max_steps=5,
        audit=AuditService(audits or InMemoryAuditStore()),
        model_gateway=model_gateway,
    )


def gateway(*, sensitive_data: bool, model_key: str = "planner-small") -> ModelGateway:
    return ModelGateway(
        [
            ProviderModel(
                model_key=model_key,
                capabilities=frozenset({PLAN_GENERATION_CAPABILITY}),
                sensitive_data=sensitive_data,
            )
        ]
    )


def test_high_risk_task_with_non_sensitive_model_is_rejected_and_not_persisted() -> None:
    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.HIGH)
    service = build_planner(
        task_store,
        generator=StubPlanGenerator("planner-small"),
        model_gateway=gateway(sensitive_data=False),
    )

    with pytest.raises(ModelNotAllowed):
        service.propose(UserContext("t-1", "u-1", "employee"), task.id, "高危目标", "key-1")

    assert service.store.list_for_task("t-1", task.id) == []


def test_high_risk_task_with_sensitive_model_succeeds() -> None:
    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.HIGH)
    service = build_planner(
        task_store,
        generator=StubPlanGenerator("planner-small"),
        model_gateway=gateway(sensitive_data=True),
    )

    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "高危目标", "key-1")

    assert proposal.status is PlanStatus.PENDING_REVIEW
    assert proposal.generator_model == "planner-small"


def test_low_risk_task_with_non_sensitive_model_succeeds() -> None:
    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.LOW)
    service = build_planner(
        task_store,
        generator=StubPlanGenerator("planner-small"),
        model_gateway=gateway(sensitive_data=False),
    )

    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "低危目标", "key-1")

    assert proposal.status is PlanStatus.PENDING_REVIEW


def test_gateway_model_mismatch_is_rejected() -> None:
    class MismatchingGateway:
        def choose(self, *, capability: str, data_classification: str, preferred: str | None = None) -> ModelRoute:
            return ModelRoute(model_key="other-model", reason="stub")

    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.LOW)
    service = build_planner(
        task_store,
        generator=StubPlanGenerator("planner-small"),
        model_gateway=MismatchingGateway(),
    )

    with pytest.raises(ModelNotAllowed, match="不一致"):
        service.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")


def test_mock_generator_without_gateway_keeps_previous_behavior() -> None:
    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.LOW)
    service = build_planner(task_store, generator=MockPlanGenerator(), model_gateway=None)

    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    assert proposal.generator_key == "mock"
    assert proposal.generator_model is None
    assert proposal.steps[0].tool == "knowledge.search"
    assert len(service.store.list_for_task("t-1", task.id)) == 1


def test_propose_audit_detail_records_data_classification() -> None:
    task_store = TaskStore()
    task = make_task(task_store, risk_level=RiskLevel.LOW)
    audits = InMemoryAuditStore()
    service = build_planner(
        task_store, generator=MockPlanGenerator(), model_gateway=None, audits=audits
    )

    service.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    details = [item.detail for item in audits.list_recent(None, limit=100)]
    assert {"step_count": 1, "generator": "mock", "data_classification": "internal"} in details
