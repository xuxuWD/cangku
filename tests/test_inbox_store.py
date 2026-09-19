"""站内通知仓储的测试：内存与 PostgreSQL 双实现。

覆盖：写入与排序、按接收人/租户隔离、未读过滤与计数、标记已读（幂等 + 他人不可见）、
全部已读、以及保留期惰性清理。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.inbox import (
    InMemoryInboxStore,
    InboxItem,
    InboxKind,
    InboxNotFound,
    PostgresInboxStore,
)

TENANT = "t-1"
RECIPIENT = "acct-1"


def item(
    *,
    inbox_id: str = "inbox-1",
    recipient: str = RECIPIENT,
    tenant: str = TENANT,
    kind: InboxKind = InboxKind.TASK_APPROVED,
    created_at: datetime | None = None,
    read_at: datetime | None = None,
    target_id: str = "task-1",
    conversation_id: str | None = None,
    approval_id: str | None = None,
) -> InboxItem:
    return InboxItem(
        inbox_id=inbox_id,
        tenant_id=tenant,
        recipient_id=recipient,
        kind=kind,
        title="你提交的任务已通过审批",
        target_type="task",
        target_id=target_id,
        # S1 第三款（迁移 041）：可空上文；默认 None 即「存量通知」形态。
        target_conversation_id=conversation_id,
        target_approval_id=approval_id,
        created_at=created_at or datetime.now(UTC),
        read_at=read_at,
    )


# ------------------------------------------------------------------ 内存实现


def test_memory_store_lists_newest_first_for_the_recipient_only() -> None:
    store = InMemoryInboxStore()
    older = item(inbox_id="inbox-old", created_at=datetime(2026, 9, 10, tzinfo=UTC))
    newer = item(inbox_id="inbox-new", created_at=datetime(2026, 9, 11, tzinfo=UTC))
    other_recipient = item(inbox_id="inbox-other", recipient="acct-2")
    other_tenant = item(inbox_id="inbox-other-tenant", tenant="t-2")
    for entry in (older, newer, other_recipient, other_tenant):
        store.add(entry)

    listed = store.list_for_recipient(TENANT, RECIPIENT, unread_only=False, limit=10)

    # 判定依据：只返回本人本租户，且按创建时间倒序。
    assert [entry.inbox_id for entry in listed] == ["inbox-new", "inbox-old"]


def test_memory_store_filters_unread_and_counts() -> None:
    store = InMemoryInboxStore()
    store.add(item(inbox_id="inbox-unread"))
    store.add(item(inbox_id="inbox-read", read_at=datetime.now(UTC)))

    assert store.count_unread(TENANT, RECIPIENT) == 1
    unread = store.list_for_recipient(TENANT, RECIPIENT, unread_only=True, limit=10)
    assert [entry.inbox_id for entry in unread] == ["inbox-unread"]


def test_memory_store_marks_read_idempotently_and_hides_others_items() -> None:
    store = InMemoryInboxStore()
    original = item(inbox_id="inbox-1")
    store.add(original)

    first = store.mark_read(TENANT, RECIPIENT, "inbox-1")
    second = store.mark_read(TENANT, RECIPIENT, "inbox-1")

    assert first.read_at is not None
    # 判定依据：重复标记幂等——不覆盖首次已读时间。
    assert second.read_at == first.read_at

    # 判定依据：他人或跨租户读取一律按不存在处理（不泄露存在性）。
    for tenant, recipient in ((TENANT, "acct-2"), ("t-2", RECIPIENT)):
        with pytest.raises(InboxNotFound):
            store.mark_read(tenant, recipient, "inbox-1")
    with pytest.raises(InboxNotFound):
        store.mark_read(TENANT, RECIPIENT, "inbox-missing")


def test_memory_store_marks_all_read_for_the_recipient_only() -> None:
    store = InMemoryInboxStore()
    store.add(item(inbox_id="inbox-1"))
    store.add(item(inbox_id="inbox-2"))
    store.add(item(inbox_id="inbox-other", recipient="acct-2"))

    updated = store.mark_all_read(TENANT, RECIPIENT)

    assert updated == 2
    assert store.count_unread(TENANT, RECIPIENT) == 0
    assert store.count_unread(TENANT, "acct-2") == 1


def test_memory_store_purges_items_beyond_retention() -> None:
    store = InMemoryInboxStore(retention_days=30)
    expired = item(inbox_id="inbox-expired", created_at=datetime.now(UTC) - timedelta(days=31))
    store.add(expired)
    store.add(item(inbox_id="inbox-fresh"))

    listed = store.list_for_recipient(TENANT, RECIPIENT, unread_only=False, limit=10)

    assert [entry.inbox_id for entry in listed] == ["inbox-fresh"]
    # 判定依据：过期条目在写入/读取时被惰性清理，不需要定时任务。
    assert store.count_unread(TENANT, RECIPIENT) == 1


# ------------------------------------------------------------------ PostgreSQL 实现


class FakeCursor:
    def __init__(self, rows: list[object] | None = None, *, rowcount: int = 0) -> None:
        self.rows = list(rows or [])
        self.statements: list[tuple[str, tuple]] = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows.pop(0) if self.rows else []


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeConnection:
    def __init__(self, rows: list[object] | None = None, *, rowcount: int = 0) -> None:
        self.cursor_instance = FakeCursor(rows, rowcount=rowcount)

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_instance


def row(
    *,
    inbox_id: str = "inbox-1",
    read_at: datetime | None = None,
    conversation_id: str | None = None,
    approval_id: str | None = None,
) -> tuple:
    """按 `PostgresInboxStore._COLUMNS` 的顺序造一行（列顺序本身就是被测契约）。"""
    return (
        inbox_id,
        TENANT,
        RECIPIENT,
        str(InboxKind.TASK_APPROVED),
        "你提交的任务已通过审批",
        "task",
        "task-1",
        conversation_id,
        approval_id,
        datetime(2026, 9, 11, tzinfo=UTC),
        read_at,
    )


def test_postgres_store_inserts_and_hydrates() -> None:
    connection = FakeConnection([row(conversation_id="conv-9", approval_id="ap-9")])
    store = PostgresInboxStore(connection)

    saved = store.add(item(conversation_id="conv-9", approval_id="ap-9"))

    insert_params = [params for statement, params in connection.cursor_instance.statements if "INSERT" in statement][0]
    assert insert_params[0] == "inbox-1"
    # 判定依据：参数顺序与 `_COLUMNS` 一致（错位即写错列）；两列上文落在 7 / 8 位。
    assert insert_params[7] == "conv-9"
    assert insert_params[8] == "ap-9"
    assert saved.inbox_id == "inbox-1"
    assert saved.kind is InboxKind.TASK_APPROVED
    assert saved.target_id == "task-1"
    assert saved.target_conversation_id == "conv-9"
    assert saved.target_approval_id == "ap-9"
    # 判定依据：写入时顺带清理过期条目，避免表无限增长。
    assert any("DELETE FROM workbench_inbox_items" in statement for statement, _ in connection.cursor_instance.statements)


def test_postgres_store_lists_with_recipient_scope_and_ordering() -> None:
    connection = FakeConnection([[row(), row(inbox_id="inbox-2")]])
    store = PostgresInboxStore(connection)

    listed = store.list_for_recipient(TENANT, RECIPIENT, unread_only=True, limit=20)

    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE tenant_id = %s AND recipient_id = %s" in statement
    assert "read_at IS NULL" in statement
    assert "ORDER BY created_at DESC" in statement
    assert "LIMIT %s" in statement
    assert params == (TENANT, RECIPIENT, 20)
    assert [entry.inbox_id for entry in listed] == ["inbox-1", "inbox-2"]
    # 判定依据：新列对「存量行」（上下文为 NULL）零破坏——读回来是 `None`，不是空串。
    assert listed[0].target_conversation_id is None
    assert listed[0].target_approval_id is None


def test_postgres_store_counts_unread() -> None:
    connection = FakeConnection([(3,)])
    store = PostgresInboxStore(connection)

    assert store.count_unread(TENANT, RECIPIENT) == 3
    assert "COUNT(*)" in connection.cursor_instance.statements[0][0]


def test_postgres_store_marks_read_with_coalesce_and_raises_when_absent() -> None:
    connection = FakeConnection([row(read_at=datetime(2026, 9, 11, 1, tzinfo=UTC))])
    store = PostgresInboxStore(connection)

    marked = store.mark_read(TENANT, RECIPIENT, "inbox-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "SET read_at = COALESCE(read_at, now())" in statement
    assert "WHERE inbox_id = %s AND tenant_id = %s AND recipient_id = %s" in statement
    assert params == ("inbox-1", TENANT, RECIPIENT)
    assert marked.read_at is not None

    missing = PostgresInboxStore(FakeConnection([None]))
    with pytest.raises(InboxNotFound):
        missing.mark_read(TENANT, RECIPIENT, "inbox-missing")


def test_postgres_store_marks_all_read_using_rowcount() -> None:
    connection = FakeConnection(rowcount=4)
    store = PostgresInboxStore(connection)

    assert store.mark_all_read(TENANT, RECIPIENT) == 4
    statement, params = connection.cursor_instance.statements[0]
    assert "SET read_at = now()" in statement
    assert params == (TENANT, RECIPIENT)
