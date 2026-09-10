from datetime import UTC, datetime

import pytest

from app.accounts.models import (
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
    TotpInvalid,
    TotpNotEnrolled,
)
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import PostgresAccountRepository
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_account_service
from app.settings import Settings


def _audit() -> AuditService:
    return AuditService(InMemoryAuditStore())


def _login_limiter() -> LoginRateLimiter:
    return LoginRateLimiter(
        InMemoryLoginAttemptStore(),
        secret="s" * 40,
        max_failures=5,
        window_seconds=300,
        lock_seconds=900,
    )


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
    service, repository = build_account_service(
        postgres_settings(), audit=_audit(), login_limiter=_login_limiter(), connection=object(), migrate=False
    )

    assert isinstance(repository, PostgresAccountRepository)
    assert service.repository is repository


def test_postgres_backend_exposes_account_repository_contract() -> None:
    _service, repository = build_account_service(
        postgres_settings(), audit=_audit(), login_limiter=_login_limiter(), connection=object(), migrate=False
    )

    for name in (
        "add",
        "find_by_phone",
        "get",
        "list_by_status",
        "mark_approved",
        "mark_rejected",
        "update_password",
        "has_approved_admin",
        "set_totp",
        "confirm_totp",
        "clear_totp",
        "record_totp_step",
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
        None, None, None,
    )


def totp_row(
    *,
    secret: str | None = "JBSWY3DPEHPK3PXP",
    confirmed_at: datetime | None = None,
    last_step: int | None = None,
    status: str = "approved",
) -> tuple:
    return (
        "acct-1", "13800000001", "scrypt$hash", "内容运营", "张三", None,
        None, None, status, datetime(2026, 9, 10, tzinfo=UTC), None, None, None,
        secret, confirmed_at, last_step,
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


def full_account_row() -> tuple:
    return (
        "acct-9", "13800000009", "scrypt$full", "技术", "王五", "w@example.com",
        "employee", "t-9", "approved", datetime(2026, 9, 10, tzinfo=UTC),
        datetime(2026, 9, 11, tzinfo=UTC), "acct-admin", None,
        "JBSWY3DPEHPK3PXP", datetime(2026, 9, 12, tzinfo=UTC), 4242,
    )


def test_postgres_hydrate_maps_every_column() -> None:
    connection = RecordingConnection([full_account_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.get("acct-9")

    assert account.account_id == "acct-9"
    assert account.phone == "13800000009"
    assert account.password_hash == "scrypt$full"
    assert account.position == "技术"
    assert account.full_name == "王五"
    assert account.email == "w@example.com"
    assert account.role == "employee"
    assert account.tenant_id == "t-9"
    assert account.status is AccountStatus.APPROVED
    assert account.requested_at == datetime(2026, 9, 10, tzinfo=UTC)
    assert account.reviewed_at == datetime(2026, 9, 11, tzinfo=UTC)
    assert account.reviewed_by == "acct-admin"
    assert account.rejection_reason is None
    assert account.totp_secret == "JBSWY3DPEHPK3PXP"
    assert account.totp_confirmed_at == datetime(2026, 9, 12, tzinfo=UTC)
    assert account.totp_last_step == 4242


def test_postgres_add_passes_all_columns_in_order() -> None:
    connection = RecordingConnection([account_row()])
    repository = PostgresAccountRepository(connection)
    draft = Account(
        phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三"
    )

    repository.add(draft)

    _statement, params = connection.cursor_instance.statements[0]
    assert len(params) == 16
    assert params[0] == draft.account_id
    assert params[1] == "13800000001"
    assert params[2] == "scrypt$hash"
    assert params[3] == "内容运营"
    assert params[4] == "张三"
    assert params[8] == "pending"
    assert params[13] is None
    assert params[14] is None
    assert params[15] is None


def test_postgres_mark_approved_passes_parameters_in_order() -> None:
    connection = RecordingConnection([account_row("approved")])
    repository = PostgresAccountRepository(connection)

    repository.mark_approved("acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin")

    assert connection.cursor_instance.statements[0][1] == ("employee", "t-1", "acct-admin", "acct-1")


def test_postgres_mark_rejected_updates_pending_account() -> None:
    connection = RecordingConnection([account_row("rejected")])
    repository = PostgresAccountRepository(connection)

    account = repository.mark_rejected("acct-1", reason="资料不完整", reviewed_by="acct-admin")

    assert account.status is AccountStatus.REJECTED
    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE account_id = %s AND status = 'pending'" in statement
    assert params == ("acct-admin", "资料不完整", "acct-1")


def test_postgres_mark_rejected_conflicts_when_not_pending() -> None:
    connection = RecordingConnection([None, ("acct-1",)])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountStateConflict):
        repository.mark_rejected("acct-1", reason="反悔", reviewed_by="acct-admin")


def test_postgres_update_password_passes_parameters_in_order() -> None:
    connection = RecordingConnection([account_row("approved")])
    repository = PostgresAccountRepository(connection)

    repository.update_password("acct-1", "scrypt$new")

    assert connection.cursor_instance.statements[0][1] == ("scrypt$new", "acct-1")


def test_postgres_update_password_raises_when_missing() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.update_password("acct-missing", "scrypt$new")


def test_postgres_list_by_status_hydrates_all_rows() -> None:
    connection = RecordingConnection([[account_row("pending"), full_account_row()]])
    repository = PostgresAccountRepository(connection)

    accounts = repository.list_by_status(AccountStatus.PENDING)

    assert [item.account_id for item in accounts] == ["acct-1", "acct-9"]
    assert connection.cursor_instance.statements[0][1] == ("pending",)


def test_columns_constant_matches_hydrate_order() -> None:
    columns = [name.strip() for name in PostgresAccountRepository._COLUMNS.split(",")]

    assert columns == [
        "account_id",
        "phone",
        "password_hash",
        "position",
        "full_name",
        "email",
        "role",
        "tenant_id",
        "status",
        "requested_at",
        "reviewed_at",
        "reviewed_by",
        "rejection_reason",
        "totp_secret",
        "totp_confirmed_at",
        "totp_last_step",
    ]


def test_postgres_set_totp_resets_confirmation_columns() -> None:
    connection = RecordingConnection([totp_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.set_totp("acct-1", "JBSWY3DPEHPK3PXP")

    assert account.totp_secret == "JBSWY3DPEHPK3PXP"
    statement, params = connection.cursor_instance.statements[0]
    assert "UPDATE workbench_accounts" in statement
    assert "RETURNING account_id, phone" in statement
    assert "totp_confirmed_at = NULL" in statement
    assert "totp_last_step = NULL" in statement
    assert params == ("JBSWY3DPEHPK3PXP", "acct-1")
    assert connection.transaction_count == 1


def test_postgres_set_totp_raises_when_account_missing() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.set_totp("acct-missing", "JBSWY3DPEHPK3PXP")


def test_postgres_confirm_totp_guards_enrolment_and_passes_step() -> None:
    connection = RecordingConnection(
        [totp_row(confirmed_at=datetime(2026, 9, 11, tzinfo=UTC), last_step=42)]
    )
    repository = PostgresAccountRepository(connection)

    account = repository.confirm_totp("acct-1", step=42)

    assert account.totp_confirmed_at == datetime(2026, 9, 11, tzinfo=UTC)
    assert account.totp_last_step == 42
    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE account_id = %s AND totp_secret IS NOT NULL" in statement
    assert params == (42, "acct-1")


def test_postgres_confirm_totp_raises_not_enrolled_when_secret_missing() -> None:
    connection = RecordingConnection([None, ("acct-1",)])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(TotpNotEnrolled):
        repository.confirm_totp("acct-1", step=42)


def test_postgres_confirm_totp_raises_not_found_when_account_missing() -> None:
    connection = RecordingConnection([None, None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.confirm_totp("acct-1", step=42)


def test_postgres_clear_totp_nulls_all_columns() -> None:
    connection = RecordingConnection([account_row("approved")])
    repository = PostgresAccountRepository(connection)

    account = repository.clear_totp("acct-1")

    assert account.totp_secret is None
    statement, params = connection.cursor_instance.statements[0]
    assert "UPDATE workbench_accounts" in statement
    assert "totp_secret = NULL" in statement
    assert "totp_confirmed_at = NULL" in statement
    assert "totp_last_step = NULL" in statement
    assert params == ("acct-1",)


def test_postgres_clear_totp_raises_when_account_missing() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.clear_totp("acct-missing")


def test_postgres_record_totp_step_guards_replay_with_ordered_params() -> None:
    connection = RecordingConnection([totp_row(last_step=100)])
    repository = PostgresAccountRepository(connection)

    account = repository.record_totp_step("acct-1", 100)

    assert account.totp_last_step == 100
    statement, params = connection.cursor_instance.statements[0]
    assert "UPDATE workbench_accounts" in statement
    assert "totp_last_step IS NULL OR totp_last_step < %s" in statement
    assert params == (100, "acct-1", 100)


def test_postgres_record_totp_step_rejects_replay() -> None:
    connection = RecordingConnection([None, ("acct-1",)])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(TotpInvalid):
        repository.record_totp_step("acct-1", 100)


def test_postgres_record_totp_step_raises_not_found_when_account_missing() -> None:
    connection = RecordingConnection([None, None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.record_totp_step("acct-1", 100)
