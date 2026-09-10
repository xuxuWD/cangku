from __future__ import annotations

from threading import RLock
from typing import Protocol

from .models import AuditRecord


class AuditStore(Protocol):
    def append(self, record: AuditRecord) -> AuditRecord: ...
    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]: ...


class InMemoryAuditStore:
    """开发期内存审计仓储；仅保留最近若干条。"""

    def __init__(self, *, max_items: int = 1_000) -> None:
        self._items: list[AuditRecord] = []
        self._max_items = max_items
        self._lock = RLock()

    def append(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self._items.append(record)
            if len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]
            return record

    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]:
        """按租户过滤；`tenant_id` 为 None 时返回全部（供测试与后续管理端排查使用）。"""
        with self._lock:
            matched = [
                item for item in self._items if tenant_id is None or item.tenant_id == tenant_id
            ]
            return matched[-limit:]
