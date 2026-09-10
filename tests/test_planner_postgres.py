from datetime import UTC, datetime

import pytest

from app.bootstrap import build_planner_service
from app.planner.models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)
from app.planner.store import PostgresPlanProposalStore
from app.settings import Settings


def postgres_settings() -> Settings:
    return Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
        content_store_backend="sqlite",
        planner_backend="mock",
        planner_tools='[{"name": "knowledge.search", "kind": "read"}]',
    )


def test_postgres_backend_uses_injected_connection() -> None:
    service, store = build_planner_service(postgres_settings(), connection=object(), migrate=False)

    assert isinstance(store, PostgresPlanProposalStore)
    assert service.store is store


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


def proposal_row(status: str = "pending_review") -> tuple:
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
        datetime(2026, 9, 10, tzinfo=UTC),
        None,
        None,
        None,
    )


def make_proposal() -> PlanProposal:
    return PlanProposal(
        task_id="task-1",
        tenant_id="t-1",
        goal="整理选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by="u-1",
        idempotency_key="key-1",
    )


def test_postgres_add_uses_transaction_and_returns_hydrated_proposal() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresPlanProposalStore(connection)

    saved = store.add(make_proposal())

    assert saved.proposal_id == "plan-1"
    assert saved.status is PlanStatus.PENDING_REVIEW
    assert connection.transaction_count == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_plan_proposals" in statement


def test_postgres_add_passes_parameters_in_column_order() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresPlanProposalStore(connection)
    draft = make_proposal()

    store.add(draft)

    _statement, params = connection.cursor_instance.statements[0]
    assert len(params) == 14
    assert params[0] == draft.proposal_id
    assert params[1] == "task-1"
    assert params[2] == "t-1"


def test_postgres_get_hides_other_tenant() -> None:
    connection = RecordingConnection([None])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalNotFound):
        store.get("t-other", "plan-1")


def test_postgres_mark_approved_guards_pending_state() -> None:
    connection = RecordingConnection([proposal_row("approved")])
    store = PostgresPlanProposalStore(connection)

    approved = store.mark_approved("plan-1", reviewer="ceo-1")

    assert approved.status is PlanStatus.APPROVED
    statement = connection.cursor_instance.statements[0][0]
    assert "status = 'pending_review'" in statement


def test_postgres_mark_approved_conflicts_when_not_pending() -> None:
    connection = RecordingConnection([None, ("plan-1",)])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved("plan-1", reviewer="ceo-1")


def test_postgres_mark_approved_not_found() -> None:
    connection = RecordingConnection([None, None])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalNotFound):
        store.mark_approved("plan-1", reviewer="ceo-1")


def test_postgres_find_by_idempotency_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresPlanProposalStore(connection)

    assert store.find_by_idempotency("t-1", "task-1", "key-1") is None


def test_migration_009_defines_status_check_and_unique_idempotency() -> None:
    from pathlib import Path

    migration = Path("migrations/009_plan_proposals.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_plan_proposals" in migration
    assert "CHECK (status IN ('pending_review', 'approved', 'rejected'))" in migration
    assert "UNIQUE (tenant_id, task_id, idempotency_key)" in migration
