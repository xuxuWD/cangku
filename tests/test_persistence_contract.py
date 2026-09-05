from pathlib import Path

import pytest

from app.settings import Settings, validate_runtime_settings
from app.bootstrap import build_task_repository
from app.domain import TaskNotFound, TaskStore
from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.repository import PostgresTaskRepository
from app.migrations import apply_migrations


def test_production_requires_postgres_and_a_real_auth_secret() -> None:
    with pytest.raises(ValueError, match="生产环境必须使用 PostgreSQL"):
        validate_runtime_settings(
            Settings(env="production", storage_backend="memory", auth_secret="long-enough-secret")
        )

    with pytest.raises(ValueError, match="认证密钥至少需要 32 个字符"):
        validate_runtime_settings(
            Settings(
                env="production",
                storage_backend="postgres",
                database_url="postgresql://localhost/workbench",
                auth_secret="short",
            )
        )


def test_initial_migration_has_tenant_scoped_idempotency_and_atomic_approval_constraint() -> None:
    migration = Path("migrations/001_initial.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_tasks" in migration
    assert "UNIQUE (tenant_id, created_by, idempotency_key)" in migration
    assert "FOREIGN KEY (id, tenant_id) REFERENCES workbench_tasks(id, tenant_id)" in migration
    assert "CHECK (status IN ('queued', 'pending_approval', 'cancelled'))" in migration
    assert "UPDATE workbench_tasks" in migration
    assert "WHERE id = %s AND tenant_id = %s AND status = 'pending_approval'" in migration


class RecordingCursor:
    def __init__(self, rows: list[tuple | None]) -> None:
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
    def __init__(self, rows: list[tuple | None]) -> None:
        self.cursor_instance = RecordingCursor(rows)
        self.transaction_count = 0

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def task() -> Task:
    return Task(
        tenant_id="t-1",
        project_id="p-1",
        created_by="u-1",
        employee_key="content-operator",
        title="日报",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="id-1",
        request_fingerprint="fingerprint",
        status=TaskStatus.QUEUED,
    )


def test_postgres_create_runs_in_transaction_and_writes_audit() -> None:
    row = ("task-1", "t-1", "p-1", "u-1", "content-operator", "日报", "low", 1, "id-1", "fingerprint", "queued")
    connection = RecordingConnection([row])
    repository = PostgresTaskRepository(connection)

    created, is_new = repository.create(UserContext("t-1", "u-1", "employee"), task())

    assert is_new is True
    assert created.id == "task-1"
    assert connection.transaction_count == 1
    assert any("INSERT INTO workbench_audit_events" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_approval_writes_audit_and_hydrates_history() -> None:
    queued = ("task-1", "t-1", "p-1", "u-1", "content-operator", "日报", "high", 1, "id-1", "fingerprint", "queued")
    audits = [("task.created", "u-1", "employee", None), ("task.approved", "ceo-1", "ceo", None)]
    connection = RecordingConnection([queued, queued, audits])
    repository = PostgresTaskRepository(connection)

    approved = repository.approve(UserContext("t-1", "ceo-1", "ceo"), "task-1")

    assert approved.status == TaskStatus.QUEUED
    assert [event.action for event in approved.audits] == ["task.created", "task.approved"]
    assert any("INSERT INTO workbench_audit_events" in sql and "task.approved" in params for sql, params in connection.cursor_instance.statements)


def test_postgres_approval_missing_task_is_not_found() -> None:
    connection = RecordingConnection([None, None])
    repository = PostgresTaskRepository(connection)

    with pytest.raises(TaskNotFound):
        repository.approve(UserContext("t-1", "ceo-1", "ceo"), "missing")


def test_migration_runner_applies_new_sql_once() -> None:
    migration_sql = "CREATE TABLE example (id TEXT);"

    class MigrationCursor(RecordingCursor):
        def __init__(self):
            super().__init__([[]])

        def fetchall(self):
            return self.rows.pop(0)

    class MigrationConnection(RecordingConnection):
        def __init__(self):
            self.cursor_instance = MigrationCursor()
            self.transaction_count = 0

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "001_example.sql").write_text(migration_sql, encoding="utf-8")
        connection = MigrationConnection()

        applied = apply_migrations(connection, Path(directory))

    assert applied == ["001_example"]
    assert any(migration_sql in sql for sql, _ in connection.cursor_instance.statements)
    assert any("pg_advisory_xact_lock" in sql for sql, _ in connection.cursor_instance.statements)


def test_development_bootstrap_uses_memory_store() -> None:
    repository = build_task_repository(Settings(env="development", storage_backend="memory"))

    assert isinstance(repository, TaskStore)


def test_production_bootstrap_requires_postgres_repository() -> None:
    from app.repository import PostgresTaskRepository

    settings = Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://localhost/workbench",
        auth_secret="x" * 32,
    )
    repository = build_task_repository(settings, connection=object(), migrate=False)

    assert isinstance(repository, PostgresTaskRepository)
