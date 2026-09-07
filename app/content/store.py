from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from .models import ContentAudit, ContentDraft, NormalizedBrief


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

    def get(self, tenant_id: str, user_id: str, task_id: str, *, elevated: bool = False) -> ContentRecord:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or record.tenant_id != tenant_id or (record.created_by != user_id and not elevated):
                raise KeyError(task_id)
            return record
