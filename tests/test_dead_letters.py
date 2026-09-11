from datetime import UTC, datetime

import pytest

from app.dead_letters import DeadLetterStore, PostgresDeadLetterStore
from app.domain import PolicyError, UserContext
from app.events import EventEnvelope, InMemoryEventBus


def event() -> EventEnvelope:
    return EventEnvelope(
        event_id="event-1",
        tenant_id="t-1",
        aggregate_type="task",
        aggregate_id="task-1",
        version=1,
        sequence=1,
        dedupe_key="task-1:created:1",
        action="task.created",
        occurred_at=datetime.now(UTC),
        payload={"status": "queued"},
    )


def test_dead_letter_store_is_tenant_scoped_and_replay_is_auditable() -> None:
    bus = InMemoryEventBus()
    store = DeadLetterStore(bus)
    item = store.record(event(), "redis unavailable")

    assert item.event_id == "event-1"
    assert [row.event_id for row in store.list(UserContext("t-1", "admin", "super_admin"))] == ["event-1"]
    assert store.replay(UserContext("t-1", "admin", "super_admin"), "event-1") == "replayed"
    assert bus.read("replay", after_sequence=0)[0].event_id == "event-1"
    assert store.replay(UserContext("t-1", "admin", "super_admin"), "event-1") == "already_replayed"


def test_dead_letter_store_rejects_non_admin_and_cross_tenant_access() -> None:
    store = DeadLetterStore(InMemoryEventBus())
    store.record(event(), "failed")

    with pytest.raises(PolicyError):
        store.list(UserContext("t-1", "employee", "employee"))
    with pytest.raises(LookupError):
        store.replay(UserContext("t-2", "admin", "super_admin"), "event-1")


def test_memory_store_record_is_idempotent() -> None:
    store = DeadLetterStore(InMemoryEventBus())

    first = store.record(event(), "first", attempts=1)
    second = store.record(event(), "second", attempts=5)

    assert first is second
    assert second.attempts == 5
    assert second.error == "second"


def test_memory_mark_notified_is_once_only() -> None:
    store = DeadLetterStore(InMemoryEventBus())
    store.record(event(), "failed")

    assert store.mark_notified("event-1") is True
    assert store.mark_notified("event-1") is False
    assert store.list(UserContext("t-1", "admin", "super_admin"))[0].notified_at is not None


def test_memory_mark_notified_returns_false_for_missing_event() -> None:
    store = DeadLetterStore(InMemoryEventBus())

    assert store.mark_notified("missing") is False


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        return self.rows.pop(0)


class Connection:
    def __init__(self, rows):
        self.cursor_value = Cursor(rows)
        self.transactions = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def transaction(self):
        class Tx:
            def __enter__(_self):
                self.transactions += 1

            def __exit__(_self, *_args):
                return False

        return Tx()

    def cursor(self):
        return self.cursor_value


def test_postgres_dead_letter_store_replays_inside_transaction() -> None:
    stored = event()
    row = (
        stored.event_id, stored.tenant_id, stored.aggregate_type, stored.aggregate_id,
        stored.version, stored.sequence, stored.dedupe_key, stored.action,
        stored.payload, 2, "failed", stored.occurred_at, None, None, None,
    )
    connection = Connection([row])
    bus = InMemoryEventBus()
    store = PostgresDeadLetterStore(connection, bus)

    assert store.replay(UserContext("t-1", "admin", "super_admin"), "event-1") == "replayed"
    assert bus.read("replay", after_sequence=0)[0] == stored
    assert connection.transactions == 1
    assert any("FOR UPDATE" in sql for sql, _ in connection.cursor_value.statements)


class UpdateCursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))


class UpdateConnection:
    def __init__(self, rowcount: int) -> None:
        self.cursor_value = UpdateCursor(rowcount)
        self.transactions = 0

    def transaction(self):
        class Tx:
            def __enter__(_self):
                self.transactions += 1

            def __exit__(_self, *_args):
                return False

        return Tx()

    def cursor(self):
        return self.cursor_value


def test_postgres_mark_notified_guards_null_and_uses_rowcount() -> None:
    connection = UpdateConnection(rowcount=1)
    store = PostgresDeadLetterStore(connection, InMemoryEventBus())

    assert store.mark_notified("event-1") is True

    sql, params = connection.cursor_value.statements[0]
    assert "UPDATE workbench_dead_letters" in sql
    assert "SET notified_at = now()" in sql
    assert "WHERE event_id = %s AND notified_at IS NULL" in sql
    assert params == ("event-1",)


def test_postgres_mark_notified_returns_false_when_rowcount_is_zero() -> None:
    connection = UpdateConnection(rowcount=0)
    store = PostgresDeadLetterStore(connection, InMemoryEventBus())

    assert store.mark_notified("event-1") is False


def test_postgres_record_list_replay_include_notified_at_column() -> None:
    stored = event()
    notified = datetime.now(UTC)
    row = (
        stored.event_id, stored.tenant_id, stored.aggregate_type, stored.aggregate_id,
        stored.version, stored.sequence, stored.dedupe_key, stored.action,
        stored.payload, 2, "failed", stored.occurred_at, None, None, notified,
    )

    list_connection = Connection([[row]])
    listed = PostgresDeadLetterStore(list_connection, InMemoryEventBus()).list(
        UserContext("t-1", "admin", "super_admin")
    )
    assert listed[0].notified_at == notified
    assert "notified_at" in list_connection.cursor_value.statements[0][0]

    record_connection = Connection([row])
    recorded = PostgresDeadLetterStore(record_connection, InMemoryEventBus()).record(
        stored, "failed", attempts=2
    )
    assert recorded.notified_at == notified
    assert "notified_at" in record_connection.cursor_value.statements[0][0]

    unread_row = (*row[:-1], None)
    replay_connection = Connection([unread_row])
    result = PostgresDeadLetterStore(replay_connection, InMemoryEventBus()).replay(
        UserContext("t-1", "admin", "super_admin"), "event-1"
    )
    assert result == "replayed"
    assert "notified_at" in replay_connection.cursor_value.statements[0][0]
