from datetime import UTC, datetime

import pytest

from app.orchestration.models import (
    OrchestrationProposal,
    OrchestrationProposalKind,
    OrchestrationProposalNotFound,
    OrchestrationProposalStateConflict,
    OrchestrationProposalStatus,
)
from app.orchestration.store import PostgresOrchestrationProposalStore


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
        "orch-1",
        "t-1",
        "runtime_default",
        "mock",
        "agentscope",
        "理由",
        {"current": {"runtime_key": "mock"}, "proposed": {"runtime_key": "agentscope"}},
        status,
        "ceo-1",
        datetime(2026, 9, 11, tzinfo=UTC),
        None,
        None,
        None,
    )


def make_proposal() -> OrchestrationProposal:
    return OrchestrationProposal(
        tenant_id="t-1",
        kind=OrchestrationProposalKind.RUNTIME_DEFAULT,
        current_value="mock",
        proposed_value="agentscope",
        rationale="理由",
        metrics_snapshot={},
        created_by="ceo-1",
    )


def test_postgres_get_scopes_by_tenant() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresOrchestrationProposalStore(connection)

    found = store.get("t-1", "orch-1")

    assert found.proposal_id == "orch-1"
    assert found.tenant_id == "t-1"
    assert found.kind is OrchestrationProposalKind.RUNTIME_DEFAULT
    assert found.status is OrchestrationProposalStatus.PENDING_REVIEW
    statement, params = connection.cursor_instance.statements[0]
    assert "FROM workbench_orchestration_proposals" in statement
    assert "tenant_id = %s" in statement
    assert params == ("orch-1", "t-1")


def test_postgres_get_hides_other_tenant() -> None:
    connection = RecordingConnection([None])
    store = PostgresOrchestrationProposalStore(connection)

    with pytest.raises(OrchestrationProposalNotFound):
        store.get("t-other", "orch-1")


def test_postgres_list_scopes_by_tenant_and_limits() -> None:
    connection = RecordingConnection([[proposal_row()]])
    store = PostgresOrchestrationProposalStore(connection)

    items = store.list_for_tenant("t-1", limit=5)

    assert [item.proposal_id for item in items] == ["orch-1"]
    statement, params = connection.cursor_instance.statements[0]
    assert "tenant_id = %s" in statement
    assert "ORDER BY created_at DESC" in statement
    assert "LIMIT %s" in statement
    assert params == ("t-1", 5)


def test_postgres_find_pending_scopes_and_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresOrchestrationProposalStore(connection)

    result = store.find_pending("t-1", OrchestrationProposalKind.RUNTIME_DEFAULT, "agentscope")

    assert result is None
    statement, params = connection.cursor_instance.statements[0]
    assert "status = 'pending_review'" in statement
    assert params == ("t-1", "runtime_default", "agentscope")


def test_postgres_add_serializes_snapshot_and_returns_row() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresOrchestrationProposalStore(connection)
    draft = make_proposal()

    saved = store.add(draft)

    assert saved.proposal_id == "orch-1"
    assert connection.transaction_count == 1
    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO workbench_orchestration_proposals" in statement
    assert "%s::jsonb" in statement
    assert params[0] == draft.proposal_id


def test_postgres_mark_approved_guards_pending_state() -> None:
    connection = RecordingConnection([proposal_row("approved")])
    store = PostgresOrchestrationProposalStore(connection)

    approved = store.mark_approved("orch-1", reviewer="ceo-1")

    assert approved.status is OrchestrationProposalStatus.APPROVED
    statement = connection.cursor_instance.statements[0][0]
    assert "UPDATE workbench_orchestration_proposals" in statement
    assert "status = 'pending_review'" in statement


def test_postgres_mark_approved_conflicts_when_not_pending() -> None:
    connection = RecordingConnection([None, ("orch-1",)])
    store = PostgresOrchestrationProposalStore(connection)

    with pytest.raises(OrchestrationProposalStateConflict):
        store.mark_approved("orch-1", reviewer="ceo-1")


def test_postgres_mark_approved_not_found() -> None:
    connection = RecordingConnection([None, None])
    store = PostgresOrchestrationProposalStore(connection)

    with pytest.raises(OrchestrationProposalNotFound):
        store.mark_approved("orch-1", reviewer="ceo-1")


def test_postgres_mark_rejected_passes_reason_and_guards_state() -> None:
    connection = RecordingConnection([proposal_row("rejected")])
    store = PostgresOrchestrationProposalStore(connection)

    rejected = store.mark_rejected("orch-1", reason="信息不足", reviewer="ceo-1")

    assert rejected.status is OrchestrationProposalStatus.REJECTED
    statement, params = connection.cursor_instance.statements[0]
    assert "status = 'pending_review'" in statement
    assert params == ("rejected", "ceo-1", "信息不足", "orch-1")


def test_postgres_hydrate_parses_string_snapshot() -> None:
    row = list(proposal_row())
    row[6] = '{"current": {"runtime_key": "mock"}}'

    hydrated = PostgresOrchestrationProposalStore._hydrate(tuple(row))

    assert hydrated.metrics_snapshot == {"current": {"runtime_key": "mock"}}
