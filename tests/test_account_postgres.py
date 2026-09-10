from datetime import UTC, datetime

import pytest

from app.accounts.models import (
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
)
from app.accounts.repository import PostgresAccountRepository
from app.bootstrap import build_account_service
from app.settings import Settings


def postgres_settings() -> Settings:
    return Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
        content_store_backend="sqlite",
    )


def test_postgres_backend_uses_injected_connection() -> None:
    service, repository = build_account_service(postgres_settings(), connection=object(), migrate=False)

    assert isinstance(repository, PostgresAccountRepository)
    assert service.repository is repository


def test_postgres_backend_exposes_account_repository_contract() -> None:
    _service, repository = build_account_service(postgres_settings(), connection=object(), migrate=False)

    for name in (
        "add",
        "find_by_phone",
        "get",
        "list_by_status",
        "mark_approved",
        "mark_rejected",
        "update_password",
        "has_approved_admin",
    ):
        assert callable(getattr(repository, name))


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


def account_row(status: str = "pending") -> tuple:
    return (
        "acct-1", "13800000001", "scrypt$hash", "内容运营", "张三", None,
        None, None, status, datetime(2026, 9, 10, tzinfo=UTC), None, None, None,
    )


def test_postgres_add_uses_on_conflict_and_transaction() -> None:
    connection = RecordingConnection([account_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.add(
        Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
    )

    assert account.account_id == "acct-1"
    assert connection.transaction_count == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_accounts" in statement
    assert "ON CONFLICT (phone) DO NOTHING" in statement


def test_postgres_add_conflict_raises_when_no_row_returned() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountConflict, match="手机号"):
        repository.add(
            Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
        )


def test_postgres_mark_approved_uses_pending_guard() -> None:
    connection = RecordingConnection([account_row("approved")])
    repository = PostgresAccountRepository(connection)

    account = repository.mark_approved(
        "acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin"
    )

    assert account.status is AccountStatus.APPROVED
    statement = connection.cursor_instance.statements[0][0]
    assert "WHERE account_id = %s AND status = 'pending'" in statement


def test_postgres_mark_approved_conflicts_when_row_missing() -> None:
    connection = RecordingConnection([None, ("acct-1",)])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountStateConflict):
        repository.mark_approved("acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin")


def test_postgres_mark_approved_raises_not_found_when_account_missing() -> None:
    connection = RecordingConnection([None, None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.mark_approved("acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin")


def test_postgres_has_approved_admin_queries_super_admin() -> None:
    connection = RecordingConnection([(1,)])
    repository = PostgresAccountRepository(connection)

    assert repository.has_approved_admin() is True
    assert "role = 'super_admin'" in connection.cursor_instance.statements[0][0]


def test_postgres_find_by_phone_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    assert repository.find_by_phone("13800000001") is None


def test_migration_008_defines_unique_phone_and_status_check() -> None:
    from pathlib import Path

    migration = Path("migrations/008_accounts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_accounts" in migration
    assert "phone TEXT NOT NULL UNIQUE" in migration
    assert "CHECK (status IN ('pending', 'approved', 'rejected'))" in migration
