import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.planner.generator import MockPlanGenerator
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch) -> None:
    store = TaskStore()
    runtime = RuntimeService(store)
    metrics = RunMetricsService(InMemoryRunRecordStore())
    planner = PlannerService(
        task_store=store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=ToolCatalog((Tool(name="knowledge.search", kind="read"),)),
        runtime_service=runtime,
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
        run_metrics=metrics,
    )
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "planner_service", planner)


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_task() -> str:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="metrics-api-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    main.store.create(UserContext("t-1", "u-1", "employee"), task)
    return task.id


def start_approved_run() -> str:
    task_id = create_task()
    proposal = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"goal": "整理本周公众号选题", "idempotency_key": "key-1"},
    )
    proposal_id = proposal.json()["proposal_id"]
    client.post(
        f"/api/v1/plan-proposals/{proposal_id}/approval",
        headers=headers(role="ceo", user_id="ceo-1"),
    )
    started = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )
    assert started.status_code == 201
    return started.json()["run_id"]


def test_run_metrics_endpoint_returns_record_for_owner() -> None:
    run_id = start_approved_run()

    response = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers())

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["runtime_key"] == "mock"
    assert body["status"] == "completed"
    assert body["proposal_id"] is not None
    assert "tenant_id" not in body


def test_run_metrics_endpoint_hides_unknown_and_cross_tenant() -> None:
    run_id = start_approved_run()

    assert client.get("/api/v1/runs/run-missing/metrics", headers=headers()).status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers(tenant_id="t-other")).status_code == 404


def test_metrics_summary_requires_ceo_or_super_admin() -> None:
    start_approved_run()

    forbidden = client.get("/api/v1/metrics/summary", headers=headers())
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "只有 CEO 或超级管理员可以查看运行指标"

    allowed = client.get("/api/v1/metrics/summary", headers=headers(role="ceo", user_id="ceo-1"))
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["tenant_id"] == "t-1"
    assert body["run_count"] == 1
    assert body["task_completion_rate"] == 1.0
    assert body["by_runtime"][0]["runtime_key"] == "mock"
