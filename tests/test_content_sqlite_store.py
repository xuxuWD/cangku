from datetime import UTC, datetime

import pytest

from app.content.models import ContentAudit, ContentDraft, ContentStatus, NormalizedBrief, NormalizedSource
from app.content.sqlite_store import ContentStoreConflict, SQLiteContentStore
from app.content.store import ContentRecord


def make_record(task_id: str, tenant_id: str, user_id: str, key: str) -> ContentRecord:
    now = datetime.now(UTC)
    brief = NormalizedBrief(
        topic="持久化选题",
        sources=(NormalizedSource(url="https://example.com/source", excerpt="正文摘录"),),
        knowledge_references=("kb-content",),
    )
    draft = ContentDraft(
        draft_id=f"draft-{task_id}", task_id=task_id, run_id=f"run-{task_id}", tenant_id=tenant_id,
        title="标题", summary="摘要", body_markdown="正文", image_suggestions=["配图"],
        citations=list(brief.sources), template_version="mock-content-v1", status=ContentStatus.REVIEWING,
        created_at=now, updated_at=now,
    )
    return ContentRecord(
        task_id=task_id, tenant_id=tenant_id, created_by=user_id, idempotency_key=key,
        input_fingerprint=f"fingerprint-{task_id}", brief=brief, run_ids=[draft.run_id],
        drafts=[draft], audits=[ContentAudit("content.created", user_id, now)],
    )


def test_sqlite_store_round_trips_record_after_new_instance(tmp_path):
    first = SQLiteContentStore(tmp_path / "nested" / "content.sqlite3")
    record = make_record("task-1", "tenant-a", "user-a", "key-1")
    first.add(record)
    first.close()

    second = SQLiteContentStore(tmp_path / "nested" / "content.sqlite3")
    restored = second.get("tenant-a", "user-a", "task-1")
    assert restored.brief.topic == record.brief.topic
    assert restored.draft.body_markdown == record.draft.body_markdown
    assert restored.draft.citations == record.draft.citations
    assert restored.audits[0].action == "content.created"
    second.close()


def test_sqlite_store_scopes_idempotency_and_reads_by_tenant_user(tmp_path):
    store = SQLiteContentStore(tmp_path / "content.sqlite3")
    store.add(make_record("task-1", "tenant-a", "user-a", "same-key"))
    assert store.find_by_idempotency("tenant-a", "user-a", "same-key").task_id == "task-1"
    assert store.find_by_idempotency("tenant-b", "user-a", "same-key") is None
    with pytest.raises(KeyError):
        store.get("tenant-a", "other-user", "task-1")
    assert store.get("tenant-a", "admin", "task-1", elevated=True).task_id == "task-1"
    store.close()


def test_sqlite_store_save_rejects_stale_revision_without_overwriting(tmp_path):
    path = tmp_path / "content.sqlite3"
    first = SQLiteContentStore(path)
    first.add(make_record("task-1", "tenant-a", "user-a", "key-1"))
    stale = first.get("tenant-a", "user-a", "task-1")
    current = first.get("tenant-a", "user-a", "task-1")
    current.draft.title = "新标题"
    current.draft.revision = 2
    first.save(current, expected_revision=1)
    stale.draft.title = "旧标题"
    stale.draft.revision = 2
    with pytest.raises(ContentStoreConflict):
        first.save(stale, expected_revision=1)
    assert first.get("tenant-a", "user-a", "task-1").draft.title == "新标题"
    first.close()
