from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol, Sequence

from .models import AuditAction, AuditRecord


class AuditStore(Protocol):
    def append(self, record: AuditRecord) -> AuditRecord: ...
    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]: ...
    def query(
        self,
        tenant_id: str,
        *,
        actions: Sequence[AuditAction] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]: ...


def _matches(
    item: AuditRecord,
    *,
    actions: frozenset[AuditAction] | None,
    target_type: str | None,
    target_id: str | None,
    actor_id: str | None,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if actions is not None and item.action not in actions:
        return False
    if target_type is not None and item.target_type != target_type:
        return False
    if target_id is not None and item.target_id != target_id:
        return False
    if actor_id is not None and item.actor_id != actor_id:
        return False
    if since is not None and item.occurred_at < since:
        return False
    if until is not None and item.occurred_at > until:
        return False
    return True


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

    def query(
        self,
        tenant_id: str,
        *,
        actions: Sequence[AuditAction] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]:
        """按条件查询，返回 (时间倒序的本页记录, 命中总数)。

        与 `list_recent` 的顺序语义不同：`list_recent` 保持插入顺序，本方法固定「新 → 旧」，
        并以插入位置作为同秒记录的次级排序键，保证结果稳定。
        """
        selected = frozenset(actions) if actions is not None else None
        with self._lock:
            matched = [
                (index, item)
                for index, item in enumerate(self._items)
                if item.tenant_id == tenant_id
                and _matches(
                    item,
                    actions=selected,
                    target_type=target_type,
                    target_id=target_id,
                    actor_id=actor_id,
                    since=since,
                    until=until,
                )
            ]
        matched.sort(key=lambda pair: (pair[1].occurred_at, pair[0]), reverse=True)
        ordered = [item for _index, item in matched]
        return ordered[offset : offset + limit], len(ordered)


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

    @staticmethod
    def _conditions(
        tenant_id: str,
        *,
        actions: Sequence[AuditAction] | None,
        target_type: str | None,
        target_id: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[str, list[object]]:
        conditions = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if actions:
            conditions.append("action = ANY(%s)")
            params.append([item.value if isinstance(item, AuditAction) else str(item) for item in actions])
        if target_type is not None:
            conditions.append("target_type = %s")
            params.append(target_type)
        if target_id is not None:
            conditions.append("target_id = %s")
            params.append(target_id)
        if actor_id is not None:
            conditions.append("actor_id = %s")
            params.append(actor_id)
        if since is not None:
            conditions.append("occurred_at >= %s")
            params.append(since)
        if until is not None:
            conditions.append("occurred_at <= %s")
            params.append(until)
        return " AND ".join(conditions), params

    def query(
        self,
        tenant_id: str,
        *,
        actions: Sequence[AuditAction] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]:
        """按条件查询（新 → 旧），附带命中总数；租户条件强制生效。"""
        where, params = self._conditions(
            tenant_id,
            actions=actions,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_audit_log
                    WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s
                    """,
                    (*params, limit, offset),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_audit_log WHERE {where}", tuple(params)
                )
                total_row = cursor.fetchone()
        total = int(total_row[0]) if total_row else 0
        return [self._hydrate(row) for row in rows], total
