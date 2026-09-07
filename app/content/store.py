from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock

from .models import ContentAudit, ContentDraft, ContentStatus, NormalizedBrief


class ContentStoreConflict(RuntimeError):
    """Raised when a persisted content record was changed concurrently."""


@dataclass
class ContentRecord:
    task_id: str
    tenant_id: str
    created_by: str
    idempotency_key: str
    input_fingerprint: str
    brief: NormalizedBrief
    run_ids: list[str] = field(default_factory=list)
    drafts: list[ContentDraft] = field(default_factory=list)
    audits: list[ContentAudit] = field(default_factory=list)

    @property
    def draft(self) -> ContentDraft:
        return self.drafts[-1]

    @property
    def run_id(self) -> str:
        return self.run_ids[-1]


@dataclass(frozen=True)
class ContentTaskSummary:
    task_id: str
    tenant_id: str
    created_by: str
    topic: str
    status: ContentStatus
    run_id: str
    created_at: datetime
    updated_at: datetime


class ContentStore:
    def __init__(self) -> None:
        self._records: dict[str, ContentRecord] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def find_by_idempotency(self, tenant_id: str, user_id: str, key: str) -> ContentRecord | None:
        with self._lock:
            task_id = self._idempotency.get((tenant_id, user_id, key))
            return self._records.get(task_id) if task_id else None

    def add(self, record: ContentRecord) -> ContentRecord:
        with self._lock:
            self._records[record.task_id] = record
            self._idempotency[(record.tenant_id, record.created_by, record.idempotency_key)] = record.task_id
            return record

    def save(self, record: ContentRecord, *, expected_revision: int | None = None) -> ContentRecord:
        with self._lock:
            current = self._records.get(record.task_id)
            if current is None:
                raise KeyError(record.task_id)
            if expected_revision is not None and current is not record and current.draft.revision != expected_revision:
                raise ContentStoreConflict(record.task_id)
            self._records[record.task_id] = record
            return record

    def get(self, tenant_id: str, user_id: str, task_id: str, *, elevated: bool = False) -> ContentRecord:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or record.tenant_id != tenant_id or (record.created_by != user_id and not elevated):
                raise KeyError(task_id)
            return record

    @staticmethod
    def _summary(record: ContentRecord) -> ContentTaskSummary:
        draft = record.draft
        return ContentTaskSummary(
            task_id=record.task_id,
            tenant_id=record.tenant_id,
            created_by=record.created_by,
            topic=record.brief.topic,
            status=draft.status,
            run_id=draft.run_id,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    def list_summaries(
        self,
        tenant_id: str,
        *,
        user_id: str | None,
        status: ContentStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ContentTaskSummary], int]:
        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.tenant_id == tenant_id
                and (user_id is None or record.created_by == user_id)
                and (status is None or record.draft.status == status)
            ]
            records.sort(key=lambda record: (record.draft.updated_at, record.task_id), reverse=True)
            total = len(records)
            return [self._summary(record) for record in records[offset:offset + limit]], total
