from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import uuid4


class PublicationNotFound(LookupError):
    pass


@dataclass
class PublicationRecord:
    tenant_id: str
    task_id: str
    revision: int
    target: str
    idempotency_key: str
    created_by: str
    publication_id: str = field(default_factory=lambda: f"pub-{uuid4().hex[:12]}")
    status: str = "pending"
    receipt_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    verified_at: datetime | None = None


class PublicationStore(Protocol):
    def add(self, record: PublicationRecord) -> PublicationRecord: ...
    def get(self, tenant_id: str, publication_id: str) -> PublicationRecord: ...
    def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> PublicationRecord | None: ...
    def list_for_task(self, tenant_id: str, task_id: str) -> list[PublicationRecord]: ...
    def mark_result(
        self,
        publication_id: str,
        *,
        status: str,
        receipt_id: str | None = None,
        error: str | None = None,
    ) -> PublicationRecord: ...
    def mark_verified(self, publication_id: str, *, status: str) -> PublicationRecord: ...


class InMemoryPublicationStore:
    """开发期内存仓储；同租户同幂等键的写入返回既有记录，不重复写入。"""

    def __init__(self) -> None:
        self._items: dict[str, PublicationRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def add(self, record: PublicationRecord) -> PublicationRecord:
        key = (record.tenant_id, record.idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                return self._items[existing_id]
            self._items[record.publication_id] = record
            self._idempotency[key] = record.publication_id
            return record

    def get(self, tenant_id: str, publication_id: str) -> PublicationRecord:
        with self._lock:
            item = self._items.get(publication_id)
            if item is None or item.tenant_id != tenant_id:
                raise PublicationNotFound(publication_id)
            return item

    def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> PublicationRecord | None:
        with self._lock:
            publication_id = self._idempotency.get((tenant_id, idempotency_key))
            return self._items.get(publication_id) if publication_id else None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PublicationRecord]:
        with self._lock:
            items = [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.task_id == task_id
            ]
        items.sort(key=lambda item: (item.created_at, item.publication_id), reverse=True)
        return items

    def mark_result(
        self,
        publication_id: str,
        *,
        status: str,
        receipt_id: str | None = None,
        error: str | None = None,
    ) -> PublicationRecord:
        with self._lock:
            item = self._by_id(publication_id)
            item.status = status
            item.receipt_id = receipt_id
            item.error = error
            return item

    def mark_verified(self, publication_id: str, *, status: str) -> PublicationRecord:
        with self._lock:
            item = self._by_id(publication_id)
            item.status = status
            item.verified_at = datetime.now(UTC)
            return item

    def _by_id(self, publication_id: str) -> PublicationRecord:
        item = self._items.get(publication_id)
        if item is None:
            raise PublicationNotFound(publication_id)
        return item


class PostgresPublicationStore:
    """发布记录持久化；以数据库唯一约束保证幂等，所有查询都带 tenant_id。"""

    _COLUMNS = (
        "publication_id, tenant_id, task_id, revision, target, idempotency_key, "
        "status, receipt_id, error, created_by, created_at, verified_at"
    )

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
    def _hydrate(row: tuple) -> PublicationRecord:
        return PublicationRecord(
            publication_id=str(row[0]),
            tenant_id=str(row[1]),
            task_id=str(row[2]),
            revision=int(row[3]),
            target=str(row[4]),
            idempotency_key=str(row[5]),
            status=str(row[6]),
            receipt_id=row[7],
            error=row[8],
            created_by=str(row[9]),
            created_at=row[10] if isinstance(row[10], datetime) else datetime.now(UTC),
            verified_at=row[11],
        )

    def add(self, record: PublicationRecord) -> PublicationRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_content_publications ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            record.publication_id,
                            record.tenant_id,
                            record.task_id,
                            record.revision,
                            record.target,
                            record.idempotency_key,
                            record.status,
                            record.receipt_id,
                            record.error,
                            record.created_by,
                            record.created_at,
                            record.verified_at,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            f"""
                            SELECT {self._COLUMNS} FROM workbench_content_publications
                            WHERE tenant_id = %s AND idempotency_key = %s
                            """,
                            (record.tenant_id, record.idempotency_key),
                        )
                        row = cursor.fetchone()
        if row is None:
            raise PublicationNotFound(record.publication_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, publication_id: str) -> PublicationRecord:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_content_publications
                    WHERE publication_id = %s AND tenant_id = %s
                    """,
                    (publication_id, tenant_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise PublicationNotFound(publication_id)
        return self._hydrate(row)

    def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> PublicationRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_content_publications
                    WHERE tenant_id = %s AND idempotency_key = %s
                    """,
                    (tenant_id, idempotency_key),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PublicationRecord]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_content_publications
                    WHERE tenant_id = %s AND task_id = %s
                    ORDER BY created_at DESC
                    """,
                    (tenant_id, task_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def mark_result(
        self,
        publication_id: str,
        *,
        status: str,
        receipt_id: str | None = None,
        error: str | None = None,
    ) -> PublicationRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_content_publications
                        SET status = %s, receipt_id = %s, error = %s
                        WHERE publication_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (status, receipt_id, error, publication_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise PublicationNotFound(publication_id)
        return self._hydrate(row)

    def mark_verified(self, publication_id: str, *, status: str) -> PublicationRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_content_publications
                        SET status = %s, verified_at = now()
                        WHERE publication_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (status, publication_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise PublicationNotFound(publication_id)
        return self._hydrate(row)
