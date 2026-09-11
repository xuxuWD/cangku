"""「待我审批」聚合的第 4 类：运行审批（run_approval）。

先写测试：审批角色可见、发起人自审被剔除、counts 含 run_approval。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.approvals import ApprovalsService
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.contracts import AgentPlan, RuntimeContext
from app.runtime.service import RuntimeService

TWO_WRITES = [
    {"step_id": "s1", "kind": "write", "tool": "file.write"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]


def runtime_context(*, task_id: str = "task-1", user_id: str = "u-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id=user_id,
        role_key="content-operator",
        mode="product_manager",
        project_id=None,
        task_id=task_id,
        device_id=f"device:{user_id}",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def build_service() -> tuple[ApprovalsService, TaskStore, RuntimeService]:
    task_store = TaskStore()
    runtime = RuntimeService(task_store)
    account_service = AccountService(
        InMemoryAccountRepository(),
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
        proposal_store=InMemoryPlanProposalStore(),
        account_service=account_service,
        run_approvals=runtime,
    )
    return service, task_store, runtime


def add_task(task_store: TaskStore, *, created_by: str = "u-1", title: str = "整理本周选题") -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title=title,
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"run-kind-{created_by}-{title}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext("t-1", created_by, "employee"), task)
    return task


def context(role: str, *, user_id: str = "ceo-1", tenant_id: str = "t-1") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user_id, role=role)


def test_ceo_sees_pending_run_approval_with_detail() -> None:
    service, task_store, runtime = build_service()
    task = add_task(task_store)
    run_id, _key, _policy = runtime.start(
        context("employee", user_id="u-1"), task.id, "mock", TWO_WRITES, "product_manager"
    )

    items, counts = service.pending(context("ceo"), limit=50)

    assert [item.kind for item in items] == ["run_approval", "run_approval"]
    first = items[0]
    assert first.target_id == run_id
    assert first.title == "整理本周选题"
    assert first.requested_by == "u-1"
    assert first.detail == {
        "run_id": run_id,
        "approval_id": "s1",
        "step_id": "s1",
        "tool": "file.write",
    }
    assert counts["run_approval"] == 2
    assert counts["total"] == 2


def test_run_approval_falls_back_to_generic_title_when_task_hidden() -> None:
    service, _task_store, runtime = build_service()
    # 直接构造一个指向不存在任务的运行时状态：任务取不到时应回落为通用标题。
    state = runtime.state_store.create(
        runtime_context(task_id="task-missing"), AgentPlan.from_steps(TWO_WRITES)
    )
    state.approvals["s1"] = "pending"

    items, counts = service.pending(context("ceo"), limit=50)

    assert [item.title for item in items] == ["运行审批"]
    assert counts["run_approval"] == 1


def test_employee_sees_nothing_and_zero_counts() -> None:
    service, task_store, runtime = build_service()
    task = add_task(task_store)
    runtime.start(context("employee", user_id="u-1"), task.id, "mock", TWO_WRITES, "product_manager")

    items, counts = service.pending(context("employee", user_id="emp-1"), limit=50)

    assert items == []
    assert counts == {
        "task_approval": 0,
        "plan_proposal": 0,
        "account_registration": 0,
        "run_approval": 0,
        "total": 0,
    }


def test_initiator_self_approval_is_excluded() -> None:
    service, task_store, runtime = build_service()
    task = add_task(task_store, created_by="ceo-1")
    runtime.start(
        context("ceo", user_id="ceo-1"), task.id, "mock", TWO_WRITES, "product_manager"
    )

    items, counts = service.pending(context("ceo", user_id="ceo-1"), limit=50)

    assert items == []
    assert counts["run_approval"] == 0


def test_decided_run_approval_leaves_the_list() -> None:
    service, task_store, runtime = build_service()
    task = add_task(task_store)
    run_id, _key, _policy = runtime.start(
        context("employee", user_id="u-1"), task.id, "mock", TWO_WRITES, "product_manager"
    )
    runtime.decide_approval(context("ceo"), run_id, "s1", True)

    items, counts = service.pending(context("ceo"), limit=50)

    assert [(item.detail["approval_id"], item.detail["step_id"]) for item in items] == [("s2", "s2")]
    assert counts["run_approval"] == 1


def test_pending_approvals_created_at_is_used_for_ordering() -> None:
    service, task_store, runtime = build_service()
    task = add_task(task_store, created_by="u-1")
    run_id, _key, _policy = runtime.start(
        context("employee", user_id="u-1"), task.id, "mock", TWO_WRITES, "product_manager"
    )
    runtime.state_store.get(run_id).created_at = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)

    items, _counts = service.pending(context("ceo"), limit=50)

    assert items[0].created_at == datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
