from datetime import UTC, datetime, timedelta

import pytest

from app.content.models import ContentAudit, ContentDraft, ContentStatus, NormalizedBrief, NormalizedSource
from app.content.sqlite_store import ContentStoreConflict, SQLiteContentStore
from app.content.store import ContentRecord, ContentStore


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


def test_sqlite_store_lists_scoped_summaries_in_draft_updated_order(tmp_path):
    store = SQLiteContentStore(tmp_path / "content.sqlite3")
    older = make_record("task-a", "tenant-a", "user-a", "key-a")
    newer = make_record("task-b", "tenant-a", "user-b", "key-b")
    other_tenant = make_record("task-c", "tenant-b", "user-a", "key-c")
    failed = make_record("task-d", "tenant-a", "user-a", "key-d")
    timestamp = datetime(2026, 9, 7, 8, tzinfo=UTC)
    older.draft.updated_at = timestamp
    newer.draft.updated_at = timestamp + timedelta(minutes=1)
    other_tenant.draft.updated_at = timestamp + timedelta(minutes=2)
    failed.draft.updated_at = timestamp + timedelta(minutes=3)
    same_time = make_record("task-z", "tenant-a", "user-b", "key-z")
    same_time.draft.updated_at = timestamp + timedelta(minutes=1)
    failed.draft.status = ContentStatus.FAILED
    store.add(older)
    store.add(newer)
    store.add(other_tenant)
    store.add(failed)
    store.add(same_time)

    summaries, total = store.list_summaries("tenant-a", user_id=None, status=None, offset=2, limit=2)

    assert total == 4
    assert [item.task_id for item in summaries] == ["task-b", "task-a"]
    assert summaries[0].topic == "持久化选题"
    assert summaries[0].updated_at == newer.draft.updated_at
    assert not hasattr(summaries[0], "draft")

    user_summaries, user_total = store.list_summaries("tenant-a", user_id="user-a", status=None, offset=0, limit=20)
    assert user_total == 2
    assert [item.task_id for item in user_summaries] == ["task-d", "task-a"]

    failed_summaries, failed_total = store.list_summaries(
        "tenant-a", user_id=None, status=ContentStatus.FAILED, offset=0, limit=20
    )
    assert failed_total == 1
    assert [item.task_id for item in failed_summaries] == ["task-d"]

    tied_summaries, tied_total = store.list_summaries("tenant-a", user_id=None, status=None, offset=0, limit=2)
    assert tied_total == 4
    assert [item.task_id for item in tied_summaries] == ["task-d", "task-z"]
    store.close()


def test_memory_store_lists_summaries_with_same_scope_and_status_semantics():
    store = ContentStore()
    first = make_record("task-1", "tenant-a", "user-a", "key-1")
    second = make_record("task-2", "tenant-a", "user-b", "key-2")
    first.draft.updated_at = datetime(2026, 9, 7, 8, tzinfo=UTC)
    second.draft.updated_at = datetime(2026, 9, 7, 9, tzinfo=UTC)
    second.draft.status = ContentStatus.FAILED
    store.add(first)
    store.add(second)

    summaries, total = store.list_summaries("tenant-a", user_id=None, status=ContentStatus.FAILED, offset=0, limit=20)

    assert total == 1
    assert summaries[0].task_id == "task-2"
    assert summaries[0].status is ContentStatus.FAILED
