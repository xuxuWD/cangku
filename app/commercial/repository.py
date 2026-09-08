from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from .tenant import Actor, CustomerAdmin, Tenant, TenantStatus, Workspace, transition_tenant
from .usage import UsageEntry


class ResourceNotFound(LookupError):
    pass


class InMemoryCommercialRepository:
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._workspaces: dict[str, Workspace] = {}
        self._admins: set[tuple[str, str]] = set()
        self._lock = RLock()

    def create_tenant(self, name: str, *, owner_id: str) -> Tenant:
        tenant = Tenant(name=name, owner_id=owner_id)
        with self._lock:
            self._tenants[tenant.id] = tenant
            self._admins.add((tenant.id, owner_id))
        return tenant

    def ensure_test_tenant(self, tenant_id: str, *, owner_id: str, admins: set[str]) -> Tenant:
        """为开发期接口测试准备一个固定 ID 的租户；生产代码不依赖此方法。"""
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None:
                tenant = Tenant(id=tenant_id, name=tenant_id, owner_id=owner_id)
                self._tenants[tenant_id] = tenant
            self._admins.add((tenant_id, owner_id))
            for user_id in admins:
                self._admins.add((tenant_id, user_id))
            return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        with self._lock:
            try:
                return self._tenants[tenant_id]
            except KeyError as exc:
                raise ResourceNotFound(tenant_id) from exc

    def activate_tenant(self, tenant_id: str, *, actor: Actor) -> Tenant:
        return transition_tenant(self.get_tenant(tenant_id), TenantStatus.ACTIVE, actor)

    def suspend_tenant(self, tenant_id: str, *, actor: Actor) -> Tenant:
        return transition_tenant(self.get_tenant(tenant_id), TenantStatus.SUSPENDED, actor)

    def create_workspace(self, tenant_id: str, name: str) -> Workspace:
        if tenant_id not in self._tenants:
            tenant = self.create_tenant(tenant_id, owner_id=tenant_id)
        workspace = Workspace(tenant_id=tenant_id, name=name)
        with self._lock:
            self._workspaces[workspace.id] = workspace
        return workspace

    def get_workspace(self, tenant_id: str, workspace_id: str) -> Workspace:
        with self._lock:
            workspace = self._workspaces.get(workspace_id)
            if workspace is None or workspace.tenant_id != tenant_id:
                raise ResourceNotFound(workspace_id)
            return workspace

    def add_customer_admin(self, tenant_id: str, user_id: str) -> CustomerAdmin:
        if tenant_id not in self._tenants:
            raise ResourceNotFound(tenant_id)
        self._admins.add((tenant_id, user_id))
        return CustomerAdmin(tenant_id=tenant_id, user_id=user_id)

    def is_customer_admin(self, tenant_id: str, user_id: str) -> bool:
        return (tenant_id, user_id) in self._admins


class PostgresCommercialRepository:
    """私有部署版商业化数据的 PostgreSQL 适配器。"""

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    def get_tenant(self, tenant_id: str) -> Tenant:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, owner_id, status, created_at FROM workbench_tenants WHERE id = %s", (tenant_id,))
                row = cursor.fetchone()
        if row is None: raise ResourceNotFound(tenant_id)
        return Tenant(id=str(row[0]), name=str(row[1]), owner_id=str(row[2]), status=TenantStatus(str(row[3])), created_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC))

    def is_customer_admin(self, tenant_id: str, user_id: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM workbench_customer_admins WHERE tenant_id = %s AND user_id = %s", (tenant_id, user_id))
                return cursor.fetchone() is not None

    def get_workspace(self, tenant_id: str, workspace_id: str) -> Workspace:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, tenant_id, name, created_at FROM workbench_workspaces WHERE tenant_id = %s AND id = %s", (tenant_id, workspace_id))
                row = cursor.fetchone()
        if row is None: raise ResourceNotFound(workspace_id)
        return Workspace(id=str(row[0]), tenant_id=str(row[1]), name=str(row[2]), created_at=row[3] if isinstance(row[3], datetime) else datetime.now(UTC))

    def add_customer_admin(self, tenant_id: str, user_id: str) -> CustomerAdmin:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM workbench_tenants WHERE id = %s", (tenant_id,))
                    if cursor.fetchone() is None:
                        raise ResourceNotFound(tenant_id)
                    cursor.execute("INSERT INTO workbench_customer_admins (tenant_id, user_id) VALUES (%s, %s) ON CONFLICT (tenant_id, user_id) DO NOTHING", (tenant_id, user_id))
        return CustomerAdmin(tenant_id=tenant_id, user_id=user_id)

    def set_tenant_status(self, tenant_id: str, status: TenantStatus) -> Tenant:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE workbench_tenants SET status = %s, updated_at = now() WHERE id = %s RETURNING id, name, owner_id, status, created_at",
                        (status.value, tenant_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise ResourceNotFound(tenant_id)
        return Tenant(
            id=str(row[0]), name=str(row[1]), owner_id=str(row[2]),
            status=TenantStatus(str(row[3])),
            created_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC),
        )

    def create_tenant(self, name: str, *, owner_id: str) -> Tenant:
        tenant_id = f"tenant-{uuid4().hex[:12]}"
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_tenants (id, name, owner_id, status)
                        VALUES (%s, %s, %s, 'trial')
                        RETURNING id, name, owner_id, status, created_at
                        """,
                        (tenant_id, name, owner_id),
                    )
                    row = cursor.fetchone()
                    cursor.execute(
                        "INSERT INTO workbench_customer_admins (tenant_id, user_id) VALUES (%s, %s) ON CONFLICT (tenant_id, user_id) DO NOTHING",
                        (tenant_id, owner_id),
                    )
        if row is None:
            raise ResourceNotFound(tenant_id)
        return Tenant(
            id=str(row[0]), name=str(row[1]), owner_id=str(row[2]),
            status=TenantStatus(str(row[3])),
            created_at=row[4] if len(row) > 4 and isinstance(row[4], datetime) else datetime.now(UTC),
        )

    def append_usage(self, entry: UsageEntry) -> UsageEntry:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_usage_ledger
                            (id, tenant_id, idempotency_key, units, cost_cents, reversal_of)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                        RETURNING id
                        """,
                        (entry.id, entry.tenant_id, entry.idempotency_key, entry.units,
                         entry.cost_cents, entry.reversal_of),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return UsageEntry(
                            idempotency_key=entry.idempotency_key,
                            tenant_id=entry.tenant_id,
                            units=entry.units,
                            cost_cents=entry.cost_cents,
                            id=str(row[0]),
                            reversal_of=entry.reversal_of,
                            occurred_at=entry.occurred_at,
                        )
                    cursor.execute(
                        """
                        SELECT id, units, cost_cents, reversal_of, occurred_at
                        FROM workbench_usage_ledger
                        WHERE tenant_id = %s AND idempotency_key = %s
                        """,
                        (entry.tenant_id, entry.idempotency_key),
                    )
                    existing = cursor.fetchone()
        if existing is None:
            raise ResourceNotFound(entry.id)
        return UsageEntry(
            idempotency_key=entry.idempotency_key,
            tenant_id=entry.tenant_id,
            units=int(existing[1]),
            cost_cents=int(existing[2]),
            id=str(existing[0]),
            reversal_of=existing[3],
            occurred_at=existing[4] if isinstance(existing[4], datetime) else entry.occurred_at,
        )

    def reverse_usage(self, tenant_id: str, entry_id: str, *, reason: str, actor_id: str) -> str:
        reversal_id = f"usage-{uuid4().hex[:12]}"
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_usage_ledger
                            (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, actor_id)
                        SELECT %s, tenant_id, %s, -units, -cost_cents, id, %s, %s
                        FROM workbench_usage_ledger
                        WHERE tenant_id = %s AND id = %s AND reversal_of IS NULL
                        """,
                        (reversal_id, f"reversal:{entry_id}", reason, actor_id, tenant_id, entry_id),
                    )
        return reversal_id
