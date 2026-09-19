from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4


class UsageLedgerError(ValueError):
    pass


# 保留策略结转的**服务端受控标记**（B-4 选项 C，2026-09-19）：
# `reason` 列标记「这一行是过期明细的净额结转」，`actor_id` 标记写入方为 worker（平台身份）。
# 判据与口径见 `docs/api-contract.md`「保留策略执行口径」。
CARRYOVER_REASON = "retention_carryover"
CARRYOVER_ACTOR = "system:worker"


def carryover_idempotency_key(cutoff: datetime) -> str:
    """结转行的幂等键：**由确定性时刻派生**（同一轮重放收敛为同一行，不重复结转）。"""
    return f"retention-carryover:{cutoff.isoformat()}"


@dataclass(frozen=True)
class UsageEntry:
    idempotency_key: str
    tenant_id: str
    units: int
    cost_cents: int
    id: str = field(default_factory=lambda: f"usage-{uuid4().hex[:12]}")
    reversal_of: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # 服务端写入的标记列（迁移 006 已有该列）：结转行为 `retention_carryover`、冲正行为调用方给的原因、
    # 普通明细为 None。导出包 `usage` 类别含该列 ⇒ 结转行在包内可识别（2026-09-19 契约口径）。
    reason: str | None = None


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
                reason=reason,
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

    def carry_over_before(self, tenant_id: str, *, cutoff: datetime) -> dict[str, int]:
        """保留策略结转（B-4 选项 C）：把 `occurred_at < cutoff` 的明细**净额成一行**再删除明细。

        恒等式：插入净额 `S = SUM(过期明细)`、删除明细集合本身 ⇒ `SUM(新表) = SUM(旧表)` **逐分不变**
        （与是否含冲正对无关）。三条实现纪律（与 PG 实现同语义）：
        ① **按行删除**（不是按时间谓词重删）——`S` 与「删掉的集合」由同一份行清单派生，天然一致；
        ② 只有存在过期行时才写结转行（**不写零额行**，避免空转污染账本）；
        ③ 结转行幂等键由 `cutoff` 派生：同轮重放把后到的过期行**并入**既有结转行（累加），不重复删。
        返回 `{"rows", "units", "cost_cents"}`（本轮删除行数 / 结转净额），供服务层写审计。
        """
        with self._lock:
            expired = [
                item
                for item in self._entries.values()
                if item.tenant_id == tenant_id and item.occurred_at < cutoff
            ]
            if not expired:
                return {"rows": 0, "units": 0, "cost_cents": 0}
            units = sum(item.units for item in expired)
            cost_cents = sum(item.cost_cents for item in expired)
            key = carryover_idempotency_key(cutoff)
            existing_id = self._keys.get((tenant_id, key))
            if existing_id is not None:
                existing = self._entries[existing_id]
                self._entries[existing_id] = replace(
                    existing,
                    units=existing.units + units,
                    cost_cents=existing.cost_cents + cost_cents,
                )
            else:
                entry = UsageEntry(
                    idempotency_key=key,
                    tenant_id=tenant_id,
                    units=units,
                    cost_cents=cost_cents,
                    reason=CARRYOVER_REASON,
                    occurred_at=cutoff,
                )
                self._entries[entry.id] = entry
                self._keys[(tenant_id, key)] = entry.id
            for item in expired:
                del self._entries[item.id]
                # 幂等键随行一起释放（与 PG 删除行后唯一键可复用同语义）：
                # 否则重放一条已被结转的旧明细会命中悬挂键 ⇒ KeyError，而不是「新写入一行」。
                self._keys.pop((item.tenant_id, item.idempotency_key), None)
        return {"rows": len(expired), "units": units, "cost_cents": cost_cents}

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
                        "INSERT INTO workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id, occurred_at",
                        (entry.id, entry.tenant_id, entry.idempotency_key, entry.units, entry.cost_cents, entry.reversal_of, entry.reason, entry.occurred_at),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return entry
                    cursor.execute("SELECT id, units, cost_cents, reversal_of, occurred_at, reason FROM workbench_usage_ledger WHERE tenant_id = %s AND idempotency_key = %s", (entry.tenant_id, entry.idempotency_key))
                    existing = cursor.fetchone()
        if existing is None:
            raise UsageLedgerError("用量记录写入失败")
        return UsageEntry(idempotency_key=entry.idempotency_key, tenant_id=entry.tenant_id, units=int(existing[1]), cost_cents=int(existing[2]), id=str(existing[0]), reversal_of=existing[3], occurred_at=existing[4] if isinstance(existing[4], datetime) else entry.occurred_at, reason=existing[5])

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
                    "SELECT id, units, cost_cents, reversal_of, occurred_at, reason FROM workbench_usage_ledger "
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
                reason=row[5],
            )
            for row in rows
        ], int(total[0]) if total is not None else 0

    def carry_over_before(self, tenant_id: str, *, cutoff: datetime) -> dict[str, int]:
        """保留策略结转（B-4 选项 C；语义与内存实现逐条一致，见 `InMemoryUsageLedger.carry_over_before`）。

        **同一事务**内：① `SELECT ... FOR UPDATE` 锁定过期明细（并发执行器在此串行化）；
        ② 有行才写结转行（`ON CONFLICT ... DO UPDATE` 把同 `cutoff` 重放时后到的过期行**累加**进净额）；
        ③ **按行 id 删除**（不是按时间谓词重删）——净额与删除集合由同一份行清单派生 ⇒
        `SUM(新表) = SUM(旧表)` 逐分不变。
        """
        key = carryover_idempotency_key(cutoff)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, units, cost_cents FROM workbench_usage_ledger "
                        "WHERE tenant_id = %s AND occurred_at < %s ORDER BY occurred_at, id FOR UPDATE",
                        (tenant_id, cutoff),
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        return {"rows": 0, "units": 0, "cost_cents": 0}
                    units = sum(int(row[1]) for row in rows)
                    cost_cents = sum(int(row[2]) for row in rows)
                    cursor.execute(
                        """
                        INSERT INTO workbench_usage_ledger
                            (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, actor_id, occurred_at)
                        VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s)
                        ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
                            SET units = workbench_usage_ledger.units + EXCLUDED.units,
                                cost_cents = workbench_usage_ledger.cost_cents + EXCLUDED.cost_cents
                        """,
                        (
                            f"usage-{uuid4().hex[:12]}",
                            tenant_id,
                            key,
                            units,
                            cost_cents,
                            CARRYOVER_REASON,
                            CARRYOVER_ACTOR,
                            cutoff,
                        ),
                    )
                    cursor.execute(
                        "DELETE FROM workbench_usage_ledger WHERE tenant_id = %s AND id = ANY(%s)",
                        (tenant_id, [str(row[0]) for row in rows]),
                    )
                    deleted = int(cursor.rowcount)
        return {"rows": deleted, "units": units, "cost_cents": cost_cents}

    def reverse(self, entry_id: str, *, reason: str, actor_id: str) -> UsageEntry:
        reversal_id = f"usage-{uuid4().hex[:12]}"
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT tenant_id, units, cost_cents FROM workbench_usage_ledger WHERE id = %s AND reversal_of IS NULL", (entry_id,))
                    original = cursor.fetchone()
                    if original is None:
                        raise UsageLedgerError("原用量记录不存在")
                    cursor.execute("INSERT INTO workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, reason, actor_id) SELECT %s, tenant_id, %s, -units, -cost_cents, id, %s, %s FROM workbench_usage_ledger WHERE id = %s AND reversal_of IS NULL RETURNING id, tenant_id, units, cost_cents, reversal_of, occurred_at, reason", (reversal_id, f"reversal:{entry_id}", reason, actor_id, entry_id))
                    row = cursor.fetchone()
        if row is None:
            raise UsageLedgerError("冲正失败")
        return UsageEntry(idempotency_key=f"reversal:{entry_id}", tenant_id=str(row[1]), units=int(row[2]), cost_cents=int(row[3]), id=str(row[0]), reversal_of=row[4], occurred_at=row[5] if isinstance(row[5], datetime) else datetime.now(UTC), reason=row[6])
