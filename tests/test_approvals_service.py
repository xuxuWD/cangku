from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.accounts.models import Account, AccountStatus
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.approvals import ApprovalsService
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.models import PlanProposal
from app.planner.store import InMemoryPlanProposalStore


def build_service() -> tuple[ApprovalsService, TaskStore, InMemoryPlanProposalStore, InMemoryAccountRepository]:
    task_store = TaskStore()
    proposal_store = InMemoryPlanProposalStore()
    account_repository = InMemoryAccountRepository()
    account_service = AccountService(
        account_repository,
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
    service = ApprovalsService(
        task_store=task_store,
        proposal_store=proposal_store,
        account_service=account_service,
    )
    return service, task_store, proposal_store, account_repository


def add_task(
    store: TaskStore,
    *,
    tenant_id: str = "t-1",
    task_id: str = "task-1",
    created_by: str = "u-1",
    status: TaskStatus = TaskStatus.PENDING_APPROVAL,
) -> Task:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="待审批任务",
        risk_level=RiskLevel.HIGH,
        budget=1,
        idempotency_key=f"id-{task_id}",
        request_fingerprint="fp",
        status=status,
        id=task_id,
    )
    store.create(UserContext(tenant_id, created_by, "employee"), task)
    return task


def add_proposal(
    store: InMemoryPlanProposalStore,
    *,
    tenant_id: str = "t-1",
    created_by: str = "u-1",
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
    repository: InMemoryAccountRepository, *, phone: str = "13800000000", position: str = "内容运营"
) -> Account:
    account = Account(
        phone=phone,
        password_hash="hash",
        position=position,
        full_name="张三",
        status=AccountStatus.PENDING,
    )
    repository.add(account)
    return account


def context(role: str, *, user_id: str = "u-1", tenant_id: str = "t-1") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user_id, role=role)


def test_employee_gets_empty_list_and_zero_counts() -> None:
    service, task_store, proposal_store, accounts = build_service()
    add_task(task_store)
    add_proposal(proposal_store)
    add_pending_account(accounts)

    items, counts = service.pending(context("employee", user_id="emp-1"), limit=50)

    assert items == []
    assert counts == {
        "task_approval": 0,
        "plan_proposal": 0,
        "account_registration": 0,
        "run_approval": 0,
        "total": 0,
    }


def test_department_lead_gets_empty_list() -> None:
    service, task_store, _, _ = build_service()
    add_task(task_store)

    items, counts = service.pending(context("department_lead", user_id="lead-1"), limit=50)

    assert items == []
    assert counts["total"] == 0


def test_ceo_sees_tasks_and_proposals_but_not_registrations() -> None:
    service, task_store, proposal_store, accounts = build_service()
    add_task(task_store, task_id="task-1")
    add_proposal(proposal_store, created_by="u-2")
    add_pending_account(accounts)

    items, counts = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert {item.kind for item in items} == {"task_approval", "plan_proposal"}
    assert counts["task_approval"] == 1
    assert counts["plan_proposal"] == 1
    assert counts["account_registration"] == 0
    assert counts["total"] == 2


def test_super_admin_sees_all_three_kinds() -> None:
    service, task_store, proposal_store, accounts = build_service()
    add_task(task_store, task_id="task-1")
    add_proposal(proposal_store, created_by="u-2")
    add_pending_account(accounts)

    items, counts = service.pending(context("super_admin", user_id="admin-1"), limit=50)

    assert {item.kind for item in items} == {
        "task_approval",
        "plan_proposal",
        "account_registration",
    }
    assert counts == {
        "task_approval": 1,
        "plan_proposal": 1,
        "account_registration": 1,
        "run_approval": 0,
        "total": 3,
    }


def test_plan_proposal_self_review_is_excluded() -> None:
    service, _, proposal_store, _ = build_service()
    add_proposal(proposal_store, created_by="ceo-1", key="own")
    add_proposal(proposal_store, created_by="u-2", key="other")

    items, counts = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert counts["plan_proposal"] == 1
    assert [item.requested_by for item in items if item.kind == "plan_proposal"] == ["u-2"]


def test_task_self_review_is_excluded() -> None:
    """任务类与计划提案同口径：发起人 == 当前用户的条目被剔除（避免展示点不动的待办）。"""
    service, task_store, _, _ = build_service()
    add_task(task_store, task_id="task-own", created_by="ceo-1")
    add_task(task_store, task_id="task-other", created_by="u-2")

    items, counts = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert counts["task_approval"] == 1
    assert [item.target_id for item in items if item.kind == "task_approval"] == ["task-other"]


def test_limit_caps_each_kind() -> None:
    service, task_store, proposal_store, accounts = build_service()
    for index in range(3):
        add_task(task_store, task_id=f"task-{index}")
    for index in range(3):
        add_proposal(proposal_store, created_by="u-2", key=f"k-{index}")
    for index in range(3):
        add_pending_account(accounts, phone=f"1380000000{index}")

    items, counts = service.pending(context("super_admin", user_id="admin-1"), limit=2)

    assert counts["task_approval"] == 2
    assert counts["plan_proposal"] == 2
    assert counts["account_registration"] == 2
    assert counts["total"] == 6
    assert len(items) == 6


def test_proposals_are_sorted_by_created_at_descending() -> None:
    service, _, proposal_store, _ = build_service()
    base = datetime(2026, 9, 10, tzinfo=UTC)
    older = add_proposal(proposal_store, created_by="u-2", key="older", created_at=base)
    newer = add_proposal(
        proposal_store, created_by="u-2", key="newer", created_at=base + timedelta(hours=1)
    )

    items, _ = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert [item.target_id for item in items] == [newer.proposal_id, older.proposal_id]


def test_tasks_without_created_at_do_not_raise() -> None:
    service, task_store, proposal_store, _ = build_service()
    add_task(task_store, task_id="task-1")
    add_proposal(proposal_store, created_by="u-2", key="k-1")

    items, counts = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert counts["total"] == 2
    assert all(item.created_at is not None for item in items)
    # 任务无 created_at，兜底后应排在真实时间戳的计划提案之后。
    assert items[-1].kind == "task_approval"


def test_detail_fields_are_whitelisted_and_non_sensitive() -> None:
    service, task_store, proposal_store, accounts = build_service()
    add_task(task_store, task_id="task-1")
    add_proposal(proposal_store, created_by="u-2", key="k-1")
    add_pending_account(accounts, position="内容运营")

    items, _ = service.pending(context("super_admin", user_id="admin-1"), limit=50)
    by_kind = {item.kind: item for item in items}

    assert by_kind["task_approval"].detail == {"risk_level": "high", "employee_key": "content-operator"}
    assert by_kind["plan_proposal"].detail == {"step_count": 0}
    assert by_kind["account_registration"].detail == {"position": "内容运营"}
    rendered = str([item.detail for item in items]).lower()
    assert "password" not in rendered
    assert "13800000000" not in str(items)


def test_registration_title_masks_phone() -> None:
    service, _, _, accounts = build_service()
    add_pending_account(accounts, phone="13800000000")

    items, _ = service.pending(context("super_admin", user_id="admin-1"), limit=50)

    registration = next(item for item in items if item.kind == "account_registration")
    assert "13800000000" not in registration.title
    assert registration.title == "138****0000"
