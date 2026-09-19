from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4


class UsageLedgerError(ValueError):
    pass


@dataclass(frozen=True)
class UsageEntry:
    idempotency_key: str
    tenant_id: str
    units: int
    cost_cents: int
    id: str = field(default_factory=lambda: f"usage-{uuid4().hex[:12]}")
    reversal_of: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryUsageLedger:
    def __init__(self) -> None:
        self._entries: dict[str, UsageEntry] = {}
        self._keys: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def append(self, entry: UsageEntry) -> UsageEntry:
        if entry.units < 0 or entry.cost_cents < 0:
            raise UsageLedgerError("用量和成本不能小于 0")
        with self._lock:
            existing_id = self._keys.get((entry.tenant_id, entry.idempotency_key))
            if existing_id:
                return self._entries[existing_id]
            self._entries[entry.id] = entry
            self._keys[(entry.tenant_id, entry.idempotency_key)] = entry.id
            return entry

    def reverse(self, entry_id: str, *, reason: str, actor_id: str) -> UsageEntry:
        with self._lock:
            original = self._entries.get(entry_id)
            if original is None:
                raise UsageLedgerError("原用量记录不存在")
            if any(item.reversal_of == entry_id for item in self._entries.values()):
                raise UsageLedgerError("该用量记录已经冲正")
            reversal = UsageEntry(
                idempotency_key=f"reversal:{entry_id}",
                tenant_id=original.tenant_id,
                units=-original.units,
                cost_cents=-original.cost_cents,
                reversal_of=entry_id,
            )
            self._entries[reversal.id] = reversal
            self._keys[(reversal.tenant_id, reversal.idempotency_key)] = reversal.id
            return reversal

    def total(self, tenant_id: str) -> int:
        with self._lock:
            return sum(item.units for item in self._entries.values() if item.tenant_id == tenant_id)

    def total_cost_cents(self, tenant_id: str) -> int:
        with self._lock:
            return sum(item.cost_cents for item in self._entries.values() if item.tenant_id == tenant_id)

    def list_for_tenant(self, tenant_id: str, *, limit: int, offset: int) -> tuple[list[UsageEntry], int]:
        """按租户列出账本明细（B-2b 导出读取通道）。

        排序 `(occurred_at, id)` —— 与 PG 实现的 `ORDER BY occurred_at, id` 同口径、顺序确定；
        返回 `(本页条目, 过滤后总数)`。冲正记录以 `reversal_of` 指向原条目（负值），
        与 `total()` / `total_cost_cents()` 的累计口径一致。
        """
        with self._lock:
            rows = sorted(
                (item for item in self._entries.values() if item.tenant_id == tenant_id),
                key=lambda item: (item.occurred_at, item.id),
            )
        return rows[offset : offset + limit], len(rows)


class PostgresUsageLedger:
    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    def _connection(self):
        from contextlib import nullcontext
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            return self.connection.connection()
        return nullcontext(self.connection)

    def append(self, entry: UsageEntry) -> UsageEntry:
        if entry.units < 0 or entry.cost_cents < 0:
            raise UsageLedgerError("用量和成本不能小于 0")
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id, occurred_at",
                        (entry.id, entry.tenant_id, entry.idempotency_key, entry.units, entry.cost_cents, entry.reversal_of, entry.occurred_at),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return entry
                    cursor.execute("SELECT id, units, cost_cents, reversal_of, occurred_at FROM workbench_usage_ledger WHERE tenant_id = %s AND idempotency_key = %s", (entry.tenant_id, entry.idempotency_key))
                    existing = cursor.fetchone()
        if existing is None:
            raise UsageLedgerError("用量记录写入失败")
        return UsageEntry(idempotency_key=entry.idempotency_key, tenant_id=entry.tenant_id, units=int(existing[1]), cost_cents=int(existing[2]), id=str(existing[0]), reversal_of=existing[3], occurred_at=existing[4] if isinstance(existing[4], datetime) else entry.occurred_at)

    def total(self, tenant_id: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(units), 0) FROM workbench_usage_ledger WHERE tenant_id = %s", (tenant_id,))
                row = cursor.fetchone()
        return int(row[0] if row else 0)

    def total_cost_cents(self, tenant_id: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(cost_cents), 0) FROM workbench_usage_ledger WHERE tenant_id = %s", (tenant_id,))
                row = cursor.fetchone()
        return int(row[0] if row else 0)

    def list_for_tenant(self, tenant_id: str, *, limit: int, offset: int) -> tuple[list[UsageEntry], int]:
        """按租户列出账本明细（B-2b 导出读取通道；字段口径同内存实现）。

        `ORDER BY occurred_at, id`（迁移 006 已有 `idx_workbench_usage_tenant_time (tenant_id, occurred_at)`
        支撑本查询）；`COUNT(*)` 为与 `LIMIT/OFFSET` 同条件的过滤后总数。
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, units, cost_cents, reversal_of, occurred_at FROM workbench_usage_ledger "
                    "WHERE tenant_id = %s ORDER BY occurred_at, id LIMIT %s OFFSET %s",
                    (tenant_id, limit, offset),
                )
                rows = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) FROM workbench_usage_ledger WHERE tenant_id = %s", (tenant_id,))
                total = cursor.fetchone()
        return [
            UsageEntry(
                idempotency_key="",  # 明细读出不需要幂等键（调用方也不用它）；导出读取器亦不导出该字段
                tenant_id=tenant_id,
                units=int(row[1]),
                cost_cents=int(row[2]),
                id=str(row[0]),
                reversal_of=row[3],
                occurred_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC),
            )
            for row in rows
        ], int(total[0]) if total is not None else 0

    def reverse(self, entry_id: str, *, reason: str, actor_id: str) -> UsageEntry:
        reversal_id = f"usage-{uuid4().hex[:12]}"
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT tenant_id, units, cost_cents FROM workbench_usage_ledger WHERE id = %s AND reversal_of IS NULL", (entry_id,))
                    original = cursor.fetchone()
                    if original is None:
                        raise UsageLedgerError("原用量记录不存在")
                    cursor.execute("INSERT INTO workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, actor_id) SELECT %s, tenant_id, %s, -units, -cost_cents, id, %s, %s FROM workbench_usage_ledger WHERE id = %s AND reversal_of IS NULL RETURNING id, tenant_id, units, cost_cents, reversal_of, occurred_at", (reversal_id, f"reversal:{entry_id}", reason, actor_id, entry_id))
                    row = cursor.fetchone()
        if row is None:
            raise UsageLedgerError("冲正失败")
        return UsageEntry(idempotency_key=f"reversal:{entry_id}", tenant_id=str(row[1]), units=int(row[2]), cost_cents=int(row[3]), id=str(row[0]), reversal_of=row[4], occurred_at=row[5] if isinstance(row[5], datetime) else datetime.now(UTC))
