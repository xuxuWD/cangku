"""审计查询的仓储层：过滤、倒序、分页与总数。

先写测试：租户必填隔离；动作多选 / 目标 / 操作者 / 时间范围过滤；limit+offset 与 total。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit.models import AuditAction, AuditRecord
from app.audit.store import InMemoryAuditStore, PostgresAuditStore

BASE = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def record(
    *,
    tenant_id: str = "t-1",
    action: AuditAction = AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
    actor_id: str | None = "u-1",
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    minutes: int = 0,
) -> AuditRecord:
    return AuditRecord(
        action=action,
        tenant_id=tenant_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
        occurred_at=BASE + timedelta(minutes=minutes),
    )


def seeded() -> InMemoryAuditStore:
    store = InMemoryAuditStore()
    store.append(record(minutes=0))
    store.append(record(action=AuditAction.PLAN_APPROVED, target_type="plan_proposal", target_id="p-1", minutes=1))
    store.append(record(action=AuditAction.PLAN_REJECTED, target_type="plan_proposal", target_id="p-2", minutes=2))
    store.append(record(actor_id="u-9", action=AuditAction.ACCOUNT_LOGIN_FAILED, minutes=3))
    store.append(record(tenant_id="t-2", action=AuditAction.PLAN_APPROVED, minutes=4))
    return store


def test_query_is_scoped_to_the_given_tenant() -> None:
    items, total = seeded().query("t-1")

    assert total == 4
    assert {item.tenant_id for item in items} == {"t-1"}


def test_query_returns_newest_first() -> None:
    items, _total = seeded().query("t-1")

    assert [item.occurred_at for item in items] == sorted(
        [item.occurred_at for item in items], reverse=True
    )
    assert items[0].action is AuditAction.ACCOUNT_LOGIN_FAILED


def test_query_filters_by_actions() -> None:
    items, total = seeded().query("t-1", actions=[AuditAction.PLAN_APPROVED, AuditAction.PLAN_REJECTED])

    assert total == 2
    assert {item.action for item in items} == {AuditAction.PLAN_APPROVED, AuditAction.PLAN_REJECTED}


def test_query_filters_by_target_actor_and_time() -> None:
    store = seeded()

    by_target, target_total = store.query("t-1", target_type="plan_proposal", target_id="p-1")
    assert target_total == 1
    assert by_target[0].target_id == "p-1"

    by_actor, actor_total = store.query("t-1", actor_id="u-9")
    assert actor_total == 1
    assert by_actor[0].actor_id == "u-9"

    since, since_total = store.query("t-1", since=BASE + timedelta(minutes=2))
    assert since_total == 2
    assert all(item.occurred_at >= BASE + timedelta(minutes=2) for item in since)

    until, until_total = store.query("t-1", until=BASE + timedelta(minutes=1))
    assert until_total == 2
    assert all(item.occurred_at <= BASE + timedelta(minutes=1) for item in until)


def test_query_pages_and_reports_total() -> None:
    store = seeded()

    first, total = store.query("t-1", limit=2, offset=0)
    second, _total = store.query("t-1", limit=2, offset=2)

    assert total == 4
    assert len(first) == 2
    assert len(second) == 2
    assert {item.record_id for item in first}.isdisjoint({item.record_id for item in second})
    assert first == store.query("t-1", limit=2, offset=0)[0]


def test_query_without_matches_is_empty() -> None:
    items, total = seeded().query("t-1", actor_id="nobody")

    assert items == []
    assert total == 0


class RecordingCursor:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.responses.pop(0)

    def fetchall(self):
        return self.responses.pop(0)


class RecordingConnection:
    def __init__(self, responses: list[object]) -> None:
        self.cursor_instance = RecordingCursor(responses)

    def cursor(self):
        return self.cursor_instance


def row(minutes: int = 0) -> tuple:
    return (
        1,
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED.value,
        "u-1",
        "t-1",
        None,
        None,
        None,
        {"status": "ok"},
        BASE + timedelta(minutes=minutes),
    )


def test_postgres_query_builds_where_clauses_and_count() -> None:
    connection = RecordingConnection([[row()], (7,)])
    store = PostgresAuditStore(connection)

    items, total = store.query(
        "t-1",
        actions=[AuditAction.ACCOUNT_LOGIN_SUCCEEDED],
        target_type="task",
        target_id="task-1",
        actor_id="u-1",
        since=BASE,
        until=BASE + timedelta(days=1),
        limit=20,
        offset=40,
    )

    select_statement, select_params = connection.cursor_instance.statements[0]
    count_statement, count_params = connection.cursor_instance.statements[1]
    assert "WHERE tenant_id = %s" in select_statement
    assert "action = ANY(%s)" in select_statement
    assert "target_type = %s" in select_statement
    assert "target_id = %s" in select_statement
    assert "actor_id = %s" in select_statement
    assert "occurred_at >= %s" in select_statement
    assert "occurred_at <= %s" in select_statement
    assert "ORDER BY id DESC" in select_statement
    assert "LIMIT %s OFFSET %s" in select_statement
    assert select_params == (
        "t-1",
        ["account.login.succeeded"],
        "task",
        "task-1",
        "u-1",
        BASE,
        BASE + timedelta(days=1),
        20,
        40,
    )
    assert count_statement.startswith("SELECT COUNT(*)")
    assert "WHERE tenant_id = %s" in count_statement
    assert count_params == (
        "t-1",
        ["account.login.succeeded"],
        "task",
        "task-1",
        "u-1",
        BASE,
        BASE + timedelta(days=1),
    )
    assert total == 7
    assert [item.action for item in items] == [AuditAction.ACCOUNT_LOGIN_SUCCEEDED]


def test_postgres_query_without_filters_only_scopes_tenant() -> None:
    connection = RecordingConnection([[], (0,)])
    store = PostgresAuditStore(connection)

    items, total = store.query("t-1")

    select_statement, select_params = connection.cursor_instance.statements[0]
    assert select_statement.count("%s") == 3
    assert select_params == ("t-1", 50, 0)
    assert items == []
    assert total == 0
