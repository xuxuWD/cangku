from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import AuditAction, AuditRecord


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


class PostgresAuditStore:
    """审计持久化；写入在事务内完成，失败向上抛出。"""

    _COLUMNS = "id, action, actor_id, tenant_id, target_type, target_id, phone_masked, detail, occurred_at"

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

    @staticmethod
    def _hydrate(row: tuple) -> AuditRecord:
        raw_detail = row[7]
        if isinstance(raw_detail, str):
            raw_detail = json.loads(raw_detail)
        return AuditRecord(
            action=AuditAction(str(row[1])),
            actor_id=row[2],
            tenant_id=row[3],
            target_type=row[4],
            target_id=row[5],
            phone_masked=row[6],
            detail=dict(raw_detail or {}),
            record_id=str(row[0]),
            occurred_at=row[8] if isinstance(row[8], datetime) else datetime.now(UTC),
        )

    def append(self, record: AuditRecord) -> AuditRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_audit_log (action, actor_id, tenant_id, target_type, target_id, phone_masked, detail, occurred_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            record.action.value,
                            record.actor_id,
                            record.tenant_id,
                            record.target_type,
                            record.target_id,
                            record.phone_masked,
                            json.dumps(record.detail, ensure_ascii=False),
                            record.occurred_at,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RuntimeError("审计写入失败")
        return self._hydrate(row)

    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]:
        """按租户过滤；`tenant_id` 为 None 时返回全部（供测试与后续管理端排查使用）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                if tenant_id is None:
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_audit_log
                        ORDER BY id DESC LIMIT %s
                        """,
                        (limit,),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_audit_log
                        WHERE tenant_id = %s ORDER BY id DESC LIMIT %s
                        """,
                        (tenant_id, limit),
                    )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in reversed(rows)]
