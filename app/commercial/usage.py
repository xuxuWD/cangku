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
