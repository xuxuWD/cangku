from datetime import UTC, datetime

from app.events import InMemoryEventBus
from app.outbox import OutboxPublisher
from app.worker import celery_app, configure_outbox_publisher, publish_outbox, configure_runtime
from app.settings import Settings


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchall(self):
        return self.rows


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transactions += 1
        return self

    def __exit__(self, *_args):
        return False


class Connection:
    def __init__(self, rows):
        self.cursor_value = Cursor(rows)
        self.transactions = 0

    def transaction(self):
        return Transaction(self)

    def cursor(self):
        return self.cursor_value


def row():
    return (
        "event-1",
        "t-1",
        "task",
        "task-1",
        1,
        1,
        "task-1:created:1",
        "task.created",
        {"status": "queued"},
        datetime.now(UTC),
    )


def test_outbox_publisher_publishes_and_marks_rows_in_one_batch() -> None:
    connection = Connection([row()])
    bus = InMemoryEventBus()
    publisher = OutboxPublisher(connection, bus)

    published = publisher.publish_pending(limit=10)

    assert published == 1
    assert [event.action for event in bus.read("test", after_sequence=0)] == ["task.created"]
    assert any("UPDATE workbench_event_outbox" in sql for sql, _ in connection.cursor_value.statements)
    assert connection.transactions == 1


def test_outbox_publisher_does_not_mark_a_failed_publish() -> None:
    connection = Connection([row()])

    class FailingBus:
        def publish(self, _event):
            raise RuntimeError("redis unavailable")

    publisher = OutboxPublisher(connection, FailingBus())

    assert publisher.publish_pending(limit=10) == 0
    assert any("attempts = attempts + 1" in sql for sql, _ in connection.cursor_value.statements)
    assert not any("published_at = now()" in sql for sql, _ in connection.cursor_value.statements)


def test_celery_worker_has_periodic_outbox_schedule_and_late_ack() -> None:
    assert celery_app.conf.task_acks_late is True
    assert "outbox-publisher" in celery_app.conf.beat_schedule


def test_publish_outbox_is_safe_when_publisher_is_not_configured() -> None:
    configure_outbox_publisher(None)

    assert publish_outbox.run() == 0


def test_publish_outbox_delegates_to_configured_publisher() -> None:
    class Publisher:
        def publish_pending(self, *, limit: int = 100) -> int:
            assert limit == 100
            return 3

    configure_outbox_publisher(Publisher())
    try:
        assert publish_outbox.run() == 3
    finally:
        configure_outbox_publisher(None)


def test_worker_runtime_requires_postgres_and_wires_injected_clients() -> None:
    class Connection:
        pass

    class Redis:
        pass

    publisher = configure_runtime(
        settings=Settings(
            env="development",
            storage_backend="postgres",
            database_url="postgresql://localhost/workbench",
        ),
        connection=Connection(),
        redis_client=Redis(),
    )
    try:
        assert publisher is not None
        assert publisher.event_bus.client.__class__.__name__ == "Redis"
    finally:
        configure_outbox_publisher(None)

    import pytest

    with pytest.raises(ValueError, match="Worker 必须使用 PostgreSQL"):
        configure_runtime(settings=Settings(env="development", storage_backend="memory"))
