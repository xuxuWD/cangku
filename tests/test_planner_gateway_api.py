from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent_services import ModelGateway, ProviderModel
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.planner.classification import PLAN_GENERATION_CAPABILITY
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.service import RuntimeService

client = TestClient(app)


class StubPlanGenerator:
    key = "openai_compatible"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        read_tools = [name for name in catalog.names() if catalog.resolve(name).kind == "read"]
        return [
            {"step_id": f"step-{index + 1}", "tool": name, "args": {"goal": goal.strip()}}
            for index, name in enumerate(read_tools[:max_steps])
        ]


@pytest.fixture(autouse=True)
def _isolate_shared_task_store(monkeypatch) -> None:
    store = TaskStore()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime_service", RuntimeService(store))


def install_gated_planner(monkeypatch, *, sensitive_data: bool, model_name: str = "planner-small") -> None:
    gateway = ModelGateway(
        [
            ProviderModel(
                model_key=model_name,
                capabilities=frozenset({PLAN_GENERATION_CAPABILITY}),
                sensitive_data=sensitive_data,
            )
        ]
    )
    service = PlannerService(
        task_store=main.store,
        store=InMemoryPlanProposalStore(),
        generator=StubPlanGenerator(model_name),
        catalog=ToolCatalog((Tool(name="knowledge.search", kind="read"),)),
        runtime_service=main.runtime_service,
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
        model_gateway=gateway,
    )
    monkeypatch.setattr(main, "planner_service", service)


def create_task(risk_level: RiskLevel) -> str:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=risk_level,
        budget=1,
        idempotency_key=f"api-gateway-{risk_level.value}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    main.store.create(UserContext("t-1", "u-1", "employee"), task)
    return task.id


def headers() -> dict[str, str]:
    return {"X-Tenant-Id": "t-1", "X-User-Id": "u-1", "X-User-Role": "employee"}


def test_gateway_denied_plan_proposal_returns_403(monkeypatch) -> None:
    install_gated_planner(monkeypatch, sensitive_data=False)
    task_id = create_task(RiskLevel.HIGH)

    response = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"goal": "高危目标", "idempotency_key": "key-1"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "没有获准处理当前数据等级的模型"


def test_low_risk_plan_proposal_passes_gate_and_returns_201(monkeypatch) -> None:
    install_gated_planner(monkeypatch, sensitive_data=False)
    task_id = create_task(RiskLevel.LOW)

    response = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"goal": "低危目标", "idempotency_key": "key-1"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
