from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .models import ContentAudit, ContentDraft, ContentStatus, NormalizedBrief, NormalizedSource
from .store import ContentRecord, ContentStoreConflict

__all__ = ["ContentStoreConflict", "SQLiteContentStore"]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _timestamp(value) -> str:
    return value.isoformat()


def _parse_timestamp(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


class SQLiteContentStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_tasks (
                    task_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    run_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, created_by, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS content_drafts (
                    draft_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    image_suggestions_json TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    template_version TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    confirmed_by TEXT,
                    confirmed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (task_id, revision)
                );
                CREATE TABLE IF NOT EXISTS content_audits (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
                    tenant_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_content_audits_task_time
                    ON content_audits(task_id, created_at, audit_id);
                INSERT INTO content_store_meta(key, value) VALUES ('schema_version', '1')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """
            )

    @staticmethod
    def _brief_json(brief: NormalizedBrief) -> str:
        return _json({
            "topic": brief.topic,
            "sources": [{"url": item.url, "excerpt": item.excerpt} for item in brief.sources],
            "knowledge_references": list(brief.knowledge_references),
        })

    @staticmethod
    def _brief(value: str) -> NormalizedBrief:
        payload = json.loads(value)
        return NormalizedBrief(
            topic=payload["topic"],
            sources=tuple(NormalizedSource(**item) for item in payload["sources"]),
            knowledge_references=tuple(payload["knowledge_references"]),
        )

    @staticmethod
    def _draft_payload(draft: ContentDraft) -> tuple[Any, ...]:
        return (
            draft.draft_id, draft.task_id, draft.run_id, draft.tenant_id, draft.title, draft.summary,
            draft.body_markdown, _json(draft.image_suggestions),
            _json([{"url": item.url, "excerpt": item.excerpt} for item in draft.citations]),
            draft.template_version, draft.revision, draft.status.value, draft.confirmed_by,
            _timestamp(draft.confirmed_at) if draft.confirmed_at else None,
            _timestamp(draft.created_at), _timestamp(draft.updated_at),
        )

    @staticmethod
    def _draft(row: sqlite3.Row) -> ContentDraft:
        return ContentDraft(
            draft_id=row["draft_id"], task_id=row["task_id"], run_id=row["run_id"], tenant_id=row["tenant_id"],
            title=row["title"], summary=row["summary"], body_markdown=row["body_markdown"],
            image_suggestions=json.loads(row["image_suggestions_json"]),
            citations=[NormalizedSource(**item) for item in json.loads(row["citations_json"])],
            template_version=row["template_version"], revision=row["revision"],
            status=ContentStatus(row["status"]), confirmed_by=row["confirmed_by"],
            confirmed_at=_parse_timestamp(row["confirmed_at"]) if row["confirmed_at"] else None,
            created_at=_parse_timestamp(row["created_at"]), updated_at=_parse_timestamp(row["updated_at"]),
        )

    @staticmethod
    def _record(row: sqlite3.Row, drafts: list[sqlite3.Row], audits: list[sqlite3.Row]) -> ContentRecord:
        return ContentRecord(
            task_id=row["task_id"], tenant_id=row["tenant_id"], created_by=row["created_by"],
            idempotency_key=row["idempotency_key"], input_fingerprint=row["input_fingerprint"],
            brief=SQLiteContentStore._brief(row["brief_json"]),
            run_ids=list(json.loads(row["run_ids_json"])),
            drafts=[SQLiteContentStore._draft(item) for item in drafts],
            audits=[ContentAudit(item["action"], item["actor_id"], _parse_timestamp(item["created_at"])) for item in audits],
        )

    def _load(self, task_id: str) -> ContentRecord | None:
        row = self._connection.execute("SELECT * FROM content_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        drafts = self._connection.execute(
            "SELECT * FROM content_drafts WHERE task_id = ? ORDER BY revision, created_at", (task_id,)
        ).fetchall()
        audits = self._connection.execute(
            "SELECT * FROM content_audits WHERE task_id = ? ORDER BY created_at, audit_id", (task_id,)
        ).fetchall()
        return self._record(row, drafts, audits)

    def find_by_idempotency(self, tenant_id: str, user_id: str, key: str) -> ContentRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT task_id FROM content_tasks WHERE tenant_id = ? AND created_by = ? AND idempotency_key = ?",
                (tenant_id, user_id, key),
            ).fetchone()
            return self._load(row["task_id"]) if row else None

    def add(self, record: ContentRecord) -> ContentRecord:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO content_tasks(task_id, tenant_id, created_by, idempotency_key, input_fingerprint, brief_json, run_ids_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.task_id, record.tenant_id, record.created_by, record.idempotency_key, record.input_fingerprint,
                 self._brief_json(record.brief), _json(record.run_ids), now, now),
            )
            self._write_children(record)
        return record

    def save(self, record: ContentRecord, *, expected_revision: int | None = None) -> ContentRecord:
        from datetime import UTC, datetime

        with self._lock, self._connection:
            current = self._load(record.task_id)
            if current is None:
                raise KeyError(record.task_id)
            if expected_revision is not None and current.draft.revision != expected_revision:
                raise ContentStoreConflict(record.task_id)
            self._connection.execute(
                "UPDATE content_tasks SET brief_json = ?, run_ids_json = ?, updated_at = ? WHERE task_id = ?",
                (self._brief_json(record.brief), _json(record.run_ids), datetime.now(UTC).isoformat(), record.task_id),
            )
            self._connection.execute("DELETE FROM content_drafts WHERE task_id = ?", (record.task_id,))
            self._connection.execute("DELETE FROM content_audits WHERE task_id = ?", (record.task_id,))
            self._write_children(record)
        return record

    def _write_children(self, record: ContentRecord) -> None:
        self._connection.executemany(
            "INSERT INTO content_drafts(draft_id, task_id, run_id, tenant_id, title, summary, body_markdown, image_suggestions_json, citations_json, template_version, revision, status, confirmed_by, confirmed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [self._draft_payload(draft) for draft in record.drafts],
        )
        self._connection.executemany(
            "INSERT INTO content_audits(task_id, tenant_id, actor_id, action, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(record.task_id, record.tenant_id, audit.actor_id, audit.action, "{}", _timestamp(audit.occurred_at)) for audit in record.audits],
        )

    def get(self, tenant_id: str, user_id: str, task_id: str, *, elevated: bool = False) -> ContentRecord:
        with self._lock:
            record = self._load(task_id)
            if record is None or record.tenant_id != tenant_id or (record.created_by != user_id and not elevated):
                raise KeyError(task_id)
            return record

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
