from pathlib import Path

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
