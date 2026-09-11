from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import Account, AccountStatus
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.approvals import ApprovalsService
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.planner.models import PlanProposal
from app.planner.store import InMemoryPlanProposalStore

client = TestClient(app)


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def build_account_service() -> tuple[AccountService, InMemoryAccountRepository]:
    repository = InMemoryAccountRepository()
    service = AccountService(
        repository,
        bootstrap_token="",
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 32,
            max_failures=5,
            window_seconds=300,
            lock_seconds=300,
        ),
        require_admin_totp=False,
    )
    return service, repository


@pytest.fixture
def approvals_env(monkeypatch):
    task_store = TaskStore()
    proposal_store = InMemoryPlanProposalStore()
    account_service, account_repository = build_account_service()
    service = ApprovalsService(
        task_store=task_store,
        proposal_store=proposal_store,
        account_service=account_service,
    )
    monkeypatch.setattr(main, "approvals_service", service)
    return task_store, proposal_store, account_repository


def add_task(
    store: TaskStore,
    *,
    tenant_id: str = "t-1",
    task_id: str = "task-1",
    status: TaskStatus = TaskStatus.PENDING_APPROVAL,
) -> Task:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="待审批任务",
        risk_level=RiskLevel.HIGH,
        budget=1,
        idempotency_key=f"id-{task_id}",
        request_fingerprint="fp",
        status=status,
        id=task_id,
    )
    store.create(UserContext(tenant_id, task.created_by, "employee"), task)
    return task


def add_proposal(
    store: InMemoryPlanProposalStore,
    *,
    tenant_id: str = "t-1",
    created_by: str = "u-2",
    key: str = "k-1",
    created_at: datetime | None = None,
) -> PlanProposal:
    proposal = PlanProposal(
        task_id="task-1",
        tenant_id=tenant_id,
        goal="整理本周选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by=created_by,
        idempotency_key=key,
        created_at=created_at or datetime.now(UTC),
    )
    store.add(proposal)
    return proposal


def add_pending_account(
    repository: InMemoryAccountRepository, *, phone: str = "13800000000"
) -> Account:
    account = Account(
        phone=phone,
        password_hash="hash",
        position="内容运营",
        full_name="张三",
        status=AccountStatus.PENDING,
    )
    repository.add(account)
    return account


def test_unauthenticated_request_returns_401() -> None:
    response = client.get("/api/v1/approvals/pending")

    assert response.status_code == 401


def test_employee_gets_empty_items_and_zero_counts(approvals_env) -> None:
    task_store, proposal_store, accounts = approvals_env
    add_task(task_store)
    add_proposal(proposal_store)
    add_pending_account(accounts)

    response = client.get("/api/v1/approvals/pending", headers=headers(role="employee"))

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "counts": {
            "task_approval": 0,
            "plan_proposal": 0,
            "account_registration": 0,
            "total": 0,
        },
    }


def test_department_lead_gets_empty_items(approvals_env) -> None:
    task_store, _, _ = approvals_env
    add_task(task_store)

    response = client.get("/api/v1/approvals/pending", headers=headers(role="department_lead"))

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_ceo_sees_tasks_and_proposals_but_not_registrations(approvals_env) -> None:
    task_store, proposal_store, accounts = approvals_env
    add_task(task_store)
    add_proposal(proposal_store, created_by="u-2")
    add_pending_account(accounts)

    response = client.get(
        "/api/v1/approvals/pending", headers=headers(role="ceo", user_id="ceo-1")
    )

    body = response.json()
    assert response.status_code == 200
    assert {item["kind"] for item in body["items"]} == {"task_approval", "plan_proposal"}
    assert body["counts"]["account_registration"] == 0


def test_super_admin_sees_all_three_kinds(approvals_env) -> None:
    task_store, proposal_store, accounts = approvals_env
    add_task(task_store)
    add_proposal(proposal_store, created_by="u-2")
    add_pending_account(accounts)

    response = client.get(
        "/api/v1/approvals/pending", headers=headers(role="super_admin", user_id="admin-1")
    )

    body = response.json()
    assert response.status_code == 200
    assert {item["kind"] for item in body["items"]} == {
        "task_approval",
        "plan_proposal",
        "account_registration",
    }


def test_cross_tenant_data_is_hidden(approvals_env) -> None:
    task_store, proposal_store, _ = approvals_env
    add_task(task_store, tenant_id="t-b", task_id="task-b")
    add_proposal(proposal_store, tenant_id="t-b", created_by="u-b", key="k-b")

    response = client.get(
        "/api/v1/approvals/pending", headers=headers(role="ceo", user_id="ceo-1", tenant_id="t-a")
    )

    body = response.json()
    assert response.status_code == 200
    assert body["items"] == []
    assert body["counts"]["total"] == 0


def test_limit_is_applied(approvals_env) -> None:
    task_store, _, _ = approvals_env
    for index in range(3):
        add_task(task_store, task_id=f"task-{index}")

    response = client.get(
        "/api/v1/approvals/pending?limit=2",
        headers=headers(role="ceo", user_id="ceo-1"),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["counts"]["task_approval"] == 2
    assert len(body["items"]) == 2


@pytest.mark.parametrize("limit", [0, 201])
def test_limit_out_of_range_returns_422(approvals_env, limit: int) -> None:
    response = client.get(
        f"/api/v1/approvals/pending?limit={limit}",
        headers=headers(role="ceo", user_id="ceo-1"),
    )

    assert response.status_code == 422


def test_registration_title_masks_phone(approvals_env) -> None:
    _, _, accounts = approvals_env
    add_pending_account(accounts, phone="13800000000")

    response = client.get(
        "/api/v1/approvals/pending", headers=headers(role="super_admin", user_id="admin-1")
    )

    registration = next(
        item for item in response.json()["items"] if item["kind"] == "account_registration"
    )
    assert "13800000000" not in registration["title"]


def test_plan_proposal_self_review_is_excluded_for_ceo(approvals_env) -> None:
    _, proposal_store, _ = approvals_env
    add_proposal(proposal_store, created_by="ceo-1", key="own")
    add_proposal(proposal_store, created_by="u-2", key="other")

    response = client.get(
        "/api/v1/approvals/pending", headers=headers(role="ceo", user_id="ceo-1")
    )

    body = response.json()
    assert body["counts"]["plan_proposal"] == 1
    assert [
        item["requested_by"] for item in body["items"] if item["kind"] == "plan_proposal"
    ] == ["u-2"]
