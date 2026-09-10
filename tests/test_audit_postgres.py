from datetime import UTC, datetime

import pytest

from app.accounts.rate_limit import PostgresLoginAttemptStore
from app.audit.models import AuditAction, build_record
from app.audit.store import PostgresAuditStore


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


def audit_row() -> tuple:
    return (
        1,
        "account.login.succeeded",
        "u-1",
        "t-1",
        "account",
        "u-1",
        "138****0001",
        '{"step_count": 2}',
        datetime(2026, 9, 10, tzinfo=UTC),
    )


def test_audit_append_uses_transaction_and_parses_detail() -> None:
    connection = RecordingConnection([audit_row()])
    store = PostgresAuditStore(connection)

    saved = store.append(
        build_record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id="t-1", actor_id="u-1")
    )

    assert saved.action is AuditAction.ACCOUNT_LOGIN_SUCCEEDED
    assert saved.detail == {"step_count": 2}
    assert saved.phone_masked == "138****0001"
    assert connection.transaction_count == 1
    assert "INSERT INTO workbench_audit_log" in connection.cursor_instance.statements[0][0]


def test_audit_append_passes_columns_in_order() -> None:
    connection = RecordingConnection([audit_row()])
    store = PostgresAuditStore(connection)
    draft = build_record(
        AuditAction.PLAN_PROPOSED, tenant_id="t-1", actor_id="u-1", detail={"step_count": 2}
    )

    store.append(draft)

    _statement, params = connection.cursor_instance.statements[0]
    assert len(params) == 8
    assert params[0] == draft.action.value
    assert params[1] == "u-1"
    assert params[2] == "t-1"


def test_audit_list_recent_is_tenant_scoped() -> None:
    connection = RecordingConnection([[audit_row()]])
    store = PostgresAuditStore(connection)

    items = store.list_recent("t-1", limit=10)

    assert len(items) == 1
    statement, params = connection.cursor_instance.statements[0]
    assert "tenant_id = %s" in statement
    assert params == ("t-1", 10)


def test_audit_list_recent_without_tenant_does_not_filter() -> None:
    connection = RecordingConnection([[audit_row()]])
    store = PostgresAuditStore(connection)

    store.list_recent(None, limit=10)

    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE" not in statement
    assert params == (10,)


def test_rate_limit_store_round_trip() -> None:
    connection = RecordingConnection(
        [("hash-1", 3, datetime(2026, 9, 10, tzinfo=UTC), None)]
    )
    store = PostgresLoginAttemptStore(connection)

    state = store.load("hash-1")

    assert state is not None
    assert state.failure_count == 3
    assert state.locked_until is None


def test_rate_limit_store_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresLoginAttemptStore(connection)

    assert store.load("hash-missing") is None


def test_rate_limit_store_record_failure_uses_single_statement() -> None:
    connection = RecordingConnection(
        [("hash-1", 3, datetime(2026, 9, 10, tzinfo=UTC), None)]
    )
    store = PostgresLoginAttemptStore(connection)

    state = store.record_failure(
        "hash-1",
        now=datetime(2026, 9, 10, tzinfo=UTC),
        window_seconds=300,
        max_failures=5,
        lock_seconds=900,
    )

    assert state.failure_count == 3
    assert connection.transaction_count == 1
    assert len(connection.cursor_instance.statements) == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_login_attempts" in statement
    assert "ON CONFLICT (phone_hash) DO UPDATE" in statement
    assert "CASE WHEN 1 >= %s THEN %s ELSE NULL END" in statement


def test_rate_limit_store_clear_deletes() -> None:
    connection = RecordingConnection([])
    store = PostgresLoginAttemptStore(connection)

    store.clear("hash-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "DELETE FROM workbench_login_attempts" in statement
    assert params == ("hash-1",)


def test_migrations_010_and_011_define_expected_constraints() -> None:
    from pathlib import Path

    audit_sql = Path("migrations/010_audit_log.sql").read_text(encoding="utf-8")
    throttle_sql = Path("migrations/011_login_attempts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_audit_log" in audit_sql
    assert "detail JSONB NOT NULL DEFAULT '{}'::jsonb" in audit_sql
    assert "occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()" in audit_sql

    assert "CREATE TABLE IF NOT EXISTS workbench_login_attempts" in throttle_sql
    assert "phone_hash TEXT PRIMARY KEY" in throttle_sql
    assert "failure_count INTEGER NOT NULL DEFAULT 0" in throttle_sql
