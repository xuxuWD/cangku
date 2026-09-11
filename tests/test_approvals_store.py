from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.planner.models import PlanProposal, PlanStatus
from app.planner.store import InMemoryPlanProposalStore, PostgresPlanProposalStore
from app.repository import PostgresTaskRepository


def make_task(
    *,
    tenant_id: str = "t-1",
    task_id: str = "task-1",
    status: TaskStatus = TaskStatus.PENDING_APPROVAL,
) -> Task:
    return Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="日报",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"id-{task_id}",
        request_fingerprint="fp",
        status=status,
        id=task_id,
    )


def seed_task(store: TaskStore, task: Task) -> Task:
    store.create(UserContext(task.tenant_id, task.created_by, "employee"), task)
    return task


# ---------------------------------------------------------------------------
# 内存任务仓储
# ---------------------------------------------------------------------------


def test_memory_list_pending_approval_filters_tenant_and_status() -> None:
    store = TaskStore()
    pending = seed_task(store, make_task(task_id="task-1"))
    seed_task(store, make_task(task_id="task-2", status=TaskStatus.QUEUED))
    seed_task(store, make_task(task_id="task-b", tenant_id="t-other"))

    items = store.list_pending_approval("t-1", limit=50)

    assert [item.id for item in items] == [pending.id]


def test_memory_list_pending_approval_is_sorted_by_id() -> None:
    store = TaskStore()
    for task_id in ("task-3", "task-1", "task-2"):
        seed_task(store, make_task(task_id=task_id))

    items = store.list_pending_approval("t-1", limit=50)

    assert [item.id for item in items] == ["task-1", "task-2", "task-3"]


def test_memory_list_pending_approval_respects_limit() -> None:
    store = TaskStore()
    for task_id in ("task-1", "task-2", "task-3"):
        seed_task(store, make_task(task_id=task_id))

    items = store.list_pending_approval("t-1", limit=2)

    assert [item.id for item in items] == ["task-1", "task-2"]


# ---------------------------------------------------------------------------
# 内存计划提案仓储
# ---------------------------------------------------------------------------


def make_proposal(
    *,
    tenant_id: str = "t-1",
    key: str = "k-1",
    status: PlanStatus = PlanStatus.PENDING_REVIEW,
    created_at: datetime | None = None,
) -> PlanProposal:
    return PlanProposal(
        task_id="task-1",
        tenant_id=tenant_id,
        goal="整理选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by="u-1",
        idempotency_key=key,
        status=status,
        created_at=created_at or datetime.now(UTC),
    )


def test_memory_list_pending_review_filters_tenant_and_status() -> None:
    store = InMemoryPlanProposalStore()
    pending = store.add(make_proposal(key="k-1"))
    store.add(make_proposal(key="k-2", status=PlanStatus.APPROVED))
    store.add(make_proposal(key="k-3", tenant_id="t-other"))

    items = store.list_pending_review("t-1", limit=50)

    assert [item.proposal_id for item in items] == [pending.proposal_id]


def test_memory_list_pending_review_is_sorted_by_created_at_desc() -> None:
    store = InMemoryPlanProposalStore()
    base = datetime(2026, 9, 10, tzinfo=UTC)
    older = store.add(make_proposal(key="older", created_at=base))
    newer = store.add(make_proposal(key="newer", created_at=base + timedelta(hours=1)))

    items = store.list_pending_review("t-1", limit=50)

    assert [item.proposal_id for item in items] == [newer.proposal_id, older.proposal_id]


def test_memory_list_pending_review_respects_limit() -> None:
    store = InMemoryPlanProposalStore()
    base = datetime(2026, 9, 10, tzinfo=UTC)
    store.add(make_proposal(key="k-1", created_at=base))
    store.add(make_proposal(key="k-2", created_at=base + timedelta(hours=1)))

    items = store.list_pending_review("t-1", limit=1)

    assert len(items) == 1
    assert items[0].idempotency_key == "k-2"


# ---------------------------------------------------------------------------
# PostgreSQL 任务仓储（假连接）
# ---------------------------------------------------------------------------


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        return self.rows.pop(0)


class RecordingTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_count += 1
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)
        self.transaction_count = 0

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def task_row(status: str = "pending_approval") -> tuple:
    return (
        "task-1",
        "t-1",
        "p-1",
        "u-1",
        "content-operator",
        "日报",
        "high",
        1,
        "id-1",
        "fingerprint",
        status,
    )


def test_postgres_list_pending_approval_scopes_tenant_and_status() -> None:
    connection = RecordingConnection([[task_row()]])
    repository = PostgresTaskRepository(connection)

    items = repository.list_pending_approval("t-1", limit=50)

    assert [item.id for item in items] == ["task-1"]
    statement, params = connection.cursor_instance.statements[0]
    assert "FROM workbench_tasks" in statement
    assert "tenant_id = %s" in statement
    assert "status = 'pending_approval'" in statement
    assert "ORDER BY id" in statement
    assert "LIMIT %s" in statement
    assert params == ("t-1", 50)


def test_postgres_list_pending_approval_hydrates_status_and_risk() -> None:
    connection = RecordingConnection([[task_row()]])
    repository = PostgresTaskRepository(connection)

    items = repository.list_pending_approval("t-1", limit=10)

    assert items[0].status is TaskStatus.PENDING_APPROVAL
    assert items[0].risk_level is RiskLevel.HIGH


def proposal_row(status: str = "pending_review", created_at: datetime | None = None) -> tuple:
    return (
        "plan-1",
        "task-1",
        "t-1",
        "整理选题",
        '[{"step_id": "s1", "tool": "knowledge.search", "kind": "read", "requires_approval": false, "args": {}}]',
        "mock",
        None,
        "u-1",
        "key-1",
        status,
        created_at or datetime(2026, 9, 10, tzinfo=UTC),
        None,
        None,
        None,
        None,
    )


def test_postgres_list_pending_review_scopes_tenant_and_status() -> None:
    connection = RecordingConnection([[proposal_row()]])
    store = PostgresPlanProposalStore(connection)

    items = store.list_pending_review("t-1", limit=50)

    assert [item.proposal_id for item in items] == ["plan-1"]
    statement, params = connection.cursor_instance.statements[0]
    assert "FROM workbench_plan_proposals" in statement
    assert "tenant_id = %s" in statement
    assert "status = 'pending_review'" in statement
    assert "ORDER BY created_at DESC" in statement
    assert "LIMIT %s" in statement
    assert params == ("t-1", 50)
