from pathlib import Path
from datetime import UTC, datetime

from app.commercial.lifecycle import (
    ExportPackage,
    LifecycleJob,
    PostgresExportPackageStore,
    PostgresLifecycleJobStore,
    PostgresRetentionPolicyStore,
)
from app.commercial.repository import PostgresCommercialRepository
from app.commercial.tenant import TenantStatus
from app.commercial.usage import PostgresUsageLedger, UsageEntry


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows.pop(0) if self.rows else []


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transactions += 1
        return self

    def __exit__(self, *_args):
        return False


class Connection:
    def __init__(self, rows):
        self.cursor_instance = Cursor(rows)
        self.transactions = 0

    def transaction(self):
        return Transaction(self)

    def cursor(self):
        return self.cursor_instance


def test_commercial_migration_has_tenant_scoped_tables_and_usage_idempotency():
    migration = Path("migrations/006_commercial_g0.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS workbench_tenants" in migration
    assert "CREATE TABLE IF NOT EXISTS workbench_usage_ledger" in migration
    assert "UNIQUE (tenant_id, idempotency_key)" in migration
    assert "CREATE TABLE IF NOT EXISTS workbench_lifecycle_jobs" in migration


def test_postgres_repository_creates_tenant_in_transaction():
    connection = Connection([("tenant-1", "客户 A", "owner-1", "trial", None)])
    repository = PostgresCommercialRepository(connection)
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")

    assert tenant.id == "tenant-1"
    assert tenant.status == TenantStatus.TRIAL
    assert connection.transactions == 1
    assert any("INSERT INTO workbench_tenants" in sql for sql, _ in connection.cursor_instance.statements)
    assert any("workbench_customer_admins" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_usage_append_uses_tenant_idempotency_and_reversal_insert():
    connection = Connection([("usage-1",)])
    repository = PostgresCommercialRepository(connection)
    entry = UsageEntry("run-1", "tenant-1", 2, 20)
    stored = repository.append_usage(entry)
    assert stored.id == "usage-1"
    assert any("ON CONFLICT (tenant_id, idempotency_key)" in sql for sql, _ in connection.cursor_instance.statements)

    repository.reverse_usage("tenant-1", "usage-1", reason="重复", actor_id="admin-1")
    assert any("INSERT INTO workbench_usage_ledger" in sql and "reversal_of" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_repository_reads_tenant_and_customer_admin_with_scope():
    connection = Connection([
        ("tenant-1", "客户 A", "owner-1", "active", None),
        ("tenant-1", "admin-1"),
    ])
    repository = PostgresCommercialRepository(connection)

    tenant = repository.get_tenant("tenant-1")

    assert tenant.id == "tenant-1"
    assert tenant.status == TenantStatus.ACTIVE
    assert repository.is_customer_admin("tenant-1", "admin-1") is True
    assert any("WHERE tenant_id = %s" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_usage_ledger_totals_are_tenant_scoped():
    connection = Connection([(12,), (345,)])
    ledger = PostgresUsageLedger(connection)

    assert ledger.total("tenant-1") == 12
    assert ledger.total_cost_cents("tenant-1") == 345
    assert all("WHERE tenant_id = %s" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_usage_ledger_list_for_tenant_scopes_orders_and_counts():
    """B-2b：导出读取通道——租户过滤 + `occurred_at, id` 稳定排序 + 计数与分页。"""
    occurred = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    # 列序 = `PostgresUsageLedger.list_for_tenant` 的 SELECT（B-4 选项 C 起追加 `reason` 列）。
    rows = [("usage-1", 2, 20, None, occurred, None)]
    connection = Connection([rows, (7,)])
    ledger = PostgresUsageLedger(connection)

    entries, total = ledger.list_for_tenant("tenant-1", limit=10, offset=20)

    assert total == 7 and [entry.id for entry in entries] == ["usage-1"]
    statements = connection.cursor_instance.statements
    assert "WHERE tenant_id = %s" in statements[0][0]
    assert "ORDER BY occurred_at, id" in statements[0][0]
    assert statements[0][1] == ("tenant-1", 10, 20)
    assert "COUNT(*)" in statements[1][0]
    assert statements[1][1] == ("tenant-1",)


def test_postgres_lifecycle_store_scopes_reads_and_updates_by_tenant():
    created_at = datetime.now(UTC)
    # 列序 = `PostgresLifecycleJobStore._COLUMNS`（B-3 增 confirmed_by / confirmed_at 两列）。
    row = (
        "job-1", "tenant-1", "delete", "cooling_down", created_at, "admin-1", created_at, False, None, None,
    )
    connection = Connection([row, [row]])
    store = PostgresLifecycleJobStore(connection)
    job = store.get("job-1", tenant_id="tenant-1")

    assert job.tenant_id == "tenant-1"
    assert job.confirmed_by is None
    job.final_exported = True
    job.confirmed_by = "admin-1"
    store.save(job)
    listed = store.list_for_tenant("tenant-1", kind="delete")

    assert listed[0].id == "job-1"
    statements = connection.cursor_instance.statements
    assert any("WHERE id = %s AND tenant_id = %s" in sql for sql, _ in statements)
    assert any("WHERE tenant_id = %s AND kind = %s" in sql for sql, _ in statements)
    # 排序确定性（E2+E3 真库演练暴露）：list_for_tenant 必须带确定性 ORDER BY，与 list_pending 同口径。
    assert any("ORDER BY created_at, id" in sql for sql, _ in statements)
    assert any("WHERE id = %s AND tenant_id = %s" in sql for sql, _ in statements if sql.startswith("UPDATE"))
    # B-3：确认人两列必须真的进 SELECT 与 UPDATE（漏列会让确认人读了就丢）。
    select_sql = next(sql for sql, _ in statements if sql.startswith("SELECT") and "confirmed_by" in sql)
    assert "confirmed_at" in select_sql
    update_sql, update_params = next(
        (sql, params) for sql, params in statements if sql.startswith("UPDATE")
    )
    assert "confirmed_by = %s" in update_sql and "confirmed_at = %s" in update_sql
    assert "admin-1" in update_params


def test_postgres_retention_store_persists_tenant_scoped_policy():
    connection = Connection([({"tasks": 90},)])
    store = PostgresRetentionPolicyStore(connection)

    store.set("tenant-1", {"tasks": 90}, actor_id="admin-1")
    assert store.get("tenant-1") == {"tasks": 90}
    assert connection.transactions == 1
    assert any("WHERE tenant_id = %s" in sql for sql, _ in connection.cursor_instance.statements)
    assert any("(tenant_id, policy, updated_by)" in sql for sql, _ in connection.cursor_instance.statements)


def test_commercial_retention_migration_adds_persistent_policy_and_export_marker():
    migration = Path("migrations/007_commercial_retention.sql").read_text(encoding="utf-8")
    assert "workbench_retention_policies" in migration
    assert "ADD COLUMN IF NOT EXISTS final_exported" in migration


def test_export_packages_migration_declares_columns_and_indexes():
    migration = Path("migrations/028_workbench_export_packages.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS workbench_export_packages (" in migration
    for column in ("id", "tenant_id", "job_id", "payload", "created_at", "expires_at"):
        assert column in migration, f"workbench_export_packages 缺少列 {column}"
    assert "REFERENCES workbench_tenants(id)" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_workbench_export_packages_tenant" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_workbench_export_packages_expires" in migration


def test_postgres_export_package_store_scopes_reads_by_tenant():
    created_at = datetime.now(UTC)
    row = ("export-1", "tenant-1", "job-1", {"tenant_id": "tenant-1"}, created_at, created_at)
    connection = Connection([row])
    store = PostgresExportPackageStore(connection)

    package = store.get("export-1", tenant_id="tenant-1")

    assert package.tenant_id == "tenant-1"
    assert package.job_id == "job-1"
    assert package.expires_at == created_at
    assert any("WHERE id = %s AND tenant_id = %s" in sql for sql, _ in connection.cursor_instance.statements)


def test_postgres_export_package_store_inserts_payload_with_expiry():
    connection = Connection([])
    store = PostgresExportPackageStore(connection)
    package = ExportPackage(
        tenant_id="tenant-1",
        job_id="job-1",
        payload={"tenant_id": "tenant-1", "resources": {"users": []}},
        expires_at=datetime.now(UTC),
    )

    store.save(package)

    assert connection.transactions == 1
    assert any("INSERT INTO workbench_export_packages" in sql for sql, _ in connection.cursor_instance.statements)
