from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.runtime.records import (
    InMemoryRunRecordStore,
    PostgresRunRecordStore,
    RunRecord,
    RunRecordNotFound,
)


def record(
    run_id: str = "run-1",
    *,
    tenant_id: str = "t-1",
    task_id: str = "task-1",
    status: str = "completed",
    started_at: datetime | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        task_id=task_id,
        runtime_key="mock",
        status=status,
        started_at=started_at or datetime(2026, 9, 11, tzinfo=UTC),
    )


def test_migration_013_defines_run_records_table_indexes_and_proposal_column() -> None:
    migration = Path("migrations/013_run_records.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_run_records" in migration
    assert "run_id TEXT PRIMARY KEY" in migration
    assert "tenant_id TEXT NOT NULL" in migration
    assert "task_id TEXT NOT NULL" in migration
    assert "proposal_id TEXT" in migration
    assert "runtime_key TEXT NOT NULL" in migration
    assert "status TEXT NOT NULL" in migration
    assert "knowledge_hits INTEGER NOT NULL DEFAULT 0" in migration
    assert "latency_ms INTEGER NOT NULL DEFAULT 0" in migration
    assert "started_at TIMESTAMPTZ NOT NULL DEFAULT now()" in migration
    assert "finished_at TIMESTAMPTZ" in migration

    assert "CREATE INDEX IF NOT EXISTS" in migration
    assert "(tenant_id, task_id, started_at DESC)" in migration
    assert "(tenant_id, runtime_key)" in migration

    assert "ALTER TABLE workbench_plan_proposals" in migration
    assert "ADD COLUMN IF NOT EXISTS run_id TEXT" in migration


def test_in_memory_upsert_overwrites_by_run_id() -> None:
    store = InMemoryRunRecordStore()
    store.upsert(record())
    updated = store.upsert(record(status="failed"))

    assert store.get("t-1", "run-1").status == "failed"
    assert updated.status == "failed"
    assert store.list_for_task("t-1", "task-1") == [updated]


def test_in_memory_get_rejects_cross_tenant() -> None:
    store = InMemoryRunRecordStore()
    store.upsert(record())

    with pytest.raises(RunRecordNotFound):
        store.get("t-other", "run-1")


def test_in_memory_get_rejects_unknown_run() -> None:
    store = InMemoryRunRecordStore()

    with pytest.raises(RunRecordNotFound):
        store.get("t-1", "run-missing")


def test_in_memory_list_for_task_is_tenant_scoped() -> None:
    store = InMemoryRunRecordStore()
    store.upsert(record("run-1"))
    store.upsert(record("run-2"))
    store.upsert(record("run-3", tenant_id="t-other"))

    assert {item.run_id for item in store.list_for_task("t-1", "task-1")} == {"run-1", "run-2"}
    assert store.list_for_task("t-1", "task-other") == []


def test_in_memory_list_recent_is_newest_first_and_respects_limit() -> None:
    store = InMemoryRunRecordStore()
    base = datetime(2026, 9, 11, tzinfo=UTC)
    store.upsert(record("run-1", started_at=base))
    store.upsert(record("run-2", started_at=base + timedelta(minutes=1)))
    store.upsert(record("run-3", started_at=base + timedelta(minutes=2)))

    recent = store.list_recent("t-1", limit=2)

    assert [item.run_id for item in recent] == ["run-3", "run-2"]


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


def run_row(status: str = "completed") -> tuple:
    # 列顺序与 `PostgresRunRecordStore._COLUMNS` 一致；最后三列是授权位（026），
    # 本文件不涉及授权，一律给 None（数据库侧由 CHECK 保证三列同生同灭）。
    return (
        "run-1",
        "t-1",
        "task-1",
        "plan-1",
        "mock",
        status,
        3,
        2,
        5,
        4,
        1,
        120,
        datetime(2026, 9, 11, tzinfo=UTC),
        None,
        None,
        None,
        None,
        None,
    )


def test_postgres_get_scopes_by_tenant() -> None:
    connection = RecordingConnection([run_row()])
    store = PostgresRunRecordStore(connection)

    found = store.get("t-1", "run-1")

    assert found.run_id == "run-1"
    assert found.runtime_key == "mock"
    assert found.step_count == 3
    assert found.knowledge_hits == 1
    statement, params = connection.cursor_instance.statements[0]
    assert "tenant_id = %s" in statement
    assert params == ("t-1", "run-1")


def test_postgres_get_missing_run_is_not_found() -> None:
    connection = RecordingConnection([None])
    store = PostgresRunRecordStore(connection)

    with pytest.raises(RunRecordNotFound):
        store.get("t-1", "run-missing")


def test_postgres_upsert_uses_on_conflict() -> None:
    connection = RecordingConnection([run_row()])
    store = PostgresRunRecordStore(connection)

    saved = store.upsert(record())

    assert saved.run_id == "run-1"
    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO workbench_run_records" in statement
    assert "ON CONFLICT (run_id) DO UPDATE" in statement
    assert params[0] == "run-1"
    assert params[1] == "t-1"


def test_postgres_list_for_task_scopes_by_task() -> None:
    connection = RecordingConnection([[run_row()]])
    store = PostgresRunRecordStore(connection)

    items = store.list_for_task("t-1", "task-1")

    assert [item.run_id for item in items] == ["run-1"]
    statement, params = connection.cursor_instance.statements[0]
    assert "task_id = %s" in statement
    assert params == ("t-1", "task-1")


def test_postgres_list_recent_orders_and_limits() -> None:
    connection = RecordingConnection([[run_row()]])
    store = PostgresRunRecordStore(connection)

    store.list_recent("t-1", limit=5)

    statement, params = connection.cursor_instance.statements[0]
    assert "ORDER BY started_at DESC" in statement
    assert "LIMIT %s" in statement
    assert params == ("t-1", 5)


def test_build_run_metrics_uses_memory_store_in_development() -> None:
    from app.bootstrap import build_run_metrics
    from app.runtime.run_metrics import RunMetricsService
    from app.settings import Settings

    service = build_run_metrics(Settings(env="development", storage_backend="memory"))

    assert isinstance(service, RunMetricsService)
    assert isinstance(service.store, InMemoryRunRecordStore)


def test_build_run_metrics_selects_postgres_with_injected_connection() -> None:
    from app.bootstrap import build_run_metrics
    from app.settings import Settings

    service = build_run_metrics(
        Settings(
            env="development",
            storage_backend="postgres",
            database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        ),
        connection=object(),
        migrate=False,
    )

    assert isinstance(service.store, PostgresRunRecordStore)
