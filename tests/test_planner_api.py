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
from app.runtime.service import RuntimeService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_shared_task_store(monkeypatch) -> None:
    store = TaskStore()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime_service", RuntimeService(store))


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


@pytest.fixture
def planner(monkeypatch) -> PlannerService:
    catalog = ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )
    service = PlannerService(
        task_store=main.store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=catalog,
        runtime_service=main.runtime_service,
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
    )
    monkeypatch.setattr(main, "planner_service", service)
    return service


def create_task(created_by: str = "u-1") -> str:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"api-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    main.store.create(UserContext("t-1", created_by, "employee"), task)
    return task.id


def propose(task_id: str, *, key: str = "key-1", actor: str = "u-1") -> dict[str, object]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(user_id=actor),
        json={"goal": "整理本周公众号选题", "idempotency_key": key},
    )
    assert response.status_code == 201
    return response.json()


def test_propose_returns_server_derived_steps(planner: PlannerService) -> None:
    task_id = create_task()

    body = propose(task_id)

    assert body["status"] == "pending_review"
    assert body["steps"][0]["tool"] == "knowledge.search"
    assert body["steps"][0]["kind"] == "read"
    assert body["steps"][0]["requires_approval"] is False
    assert "generator" in body


def test_propose_is_idempotent(planner: PlannerService) -> None:
    task_id = create_task()

    first = propose(task_id, key="same-key")
    second = propose(task_id, key="same-key")

    assert first["proposal_id"] == second["proposal_id"]


def test_propose_requires_goal_and_idempotency_key(planner: PlannerService) -> None:
    task_id = create_task()

    missing_goal = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"idempotency_key": "k"},
    )
    missing_key = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"goal": "目标"},
    )

    assert missing_goal.status_code == 422
    assert missing_key.status_code == 422


def test_employee_cannot_approve_and_ceo_cannot_approve_own_proposal(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    assert (
        client.post(f"/api/v1/plan-proposals/{proposal_id}/approval", headers=headers()).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/plan-proposals/{proposal_id}/approval", headers=headers(role="ceo", user_id="u-1")
        ).status_code
        == 403
    )


def test_ceo_approves_then_execution_starts(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    approved = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/approval",
        headers=headers(role="ceo", user_id="ceo-1"),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    blocked = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(user_id="u-9"),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )
    assert blocked.status_code == 404

    started = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )
    assert started.status_code == 201
    assert started.json()["status"] == "running"


def test_execution_before_approval_conflicts(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    response = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )

    assert response.status_code == 409


def test_rejection_records_reason(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    response = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/rejection",
        headers=headers(role="ceo", user_id="ceo-1"),
        json={"reason": "步骤不完整"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["rejection_reason"] == "步骤不完整"


def test_get_hides_cross_tenant_proposal(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    hidden = client.get(
        f"/api/v1/plan-proposals/{proposal_id}",
        headers=headers(tenant_id="t-other"),
    )

    assert hidden.status_code == 404


def test_approval_of_unknown_proposal_is_not_found(planner: PlannerService) -> None:
    response = client.post(
        "/api/v1/plan-proposals/plan-missing/approval",
        headers=headers(role="ceo", user_id="ceo-1"),
    )

    assert response.status_code == 404


def test_proposal_view_does_not_leak_model_secrets(planner: PlannerService) -> None:
    task_id = create_task()

    body = propose(task_id)

    rendered = str(body).lower()
    for leaked in ("api_key", "authorization", "secret-key", "password", "token"):
        assert leaked not in rendered
    assert set(body) == {
        "proposal_id",
        "task_id",
        "goal",
        "status",
        "steps",
        "generator",
        "created_by",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "rejection_reason",
    }
