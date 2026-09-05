from datetime import UTC, datetime

from app.events import EventEnvelope, InMemoryEventBus, IdempotentEventConsumer, RedisStreamEventBus


def envelope(event_id: str = "event-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
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


def test_event_bus_preserves_order_and_supports_replay() -> None:
    bus = InMemoryEventBus()
    bus.publish(envelope("event-1"))
    bus.publish(envelope("event-2"))

    first = bus.read("consumer-a", after_sequence=0)
    replay = bus.read("consumer-a", after_sequence=0)

    assert [event.event_id for event in first] == ["event-1", "event-2"]
    assert [event.event_id for event in replay] == ["event-1", "event-2"]


def test_consumer_processes_each_dedupe_key_once() -> None:
    bus = InMemoryEventBus()
    consumer = IdempotentEventConsumer()
    processed: list[str] = []

    event = envelope()
    bus.publish(event)
    bus.publish(EventEnvelope(**{**event.__dict__, "event_id": "event-duplicate"}))

    for item in bus.read("consumer-a", after_sequence=0):
        consumer.handle(item, lambda current: processed.append(current.event_id))

    assert processed == ["event-1"]
    assert consumer.processed_count == 1


def test_failed_event_is_retried_then_moved_to_dead_letter() -> None:
    consumer = IdempotentEventConsumer(max_attempts=2)
    event = envelope()

    assert consumer.handle(event, lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))) == "retry"
    assert consumer.handle(event, lambda _: (_ for _ in ()).throw(RuntimeError("permanent"))) == "dead_letter"
    assert consumer.dead_letters == [event]


def test_dead_letter_callback_is_called_once() -> None:
    alerted: list[str] = []
    consumer = IdempotentEventConsumer(max_attempts=1, on_dead_letter=lambda item: alerted.append(item.event_id))

    event = envelope()
    failing_handler = lambda _: (_ for _ in ()).throw(RuntimeError("permanent"))

    assert consumer.handle(event, failing_handler) == "dead_letter"
    assert consumer.handle(event, failing_handler) == "dead_letter"
    assert alerted == ["event-1"]
    assert consumer.dead_letters == [event]


class GroupRedis:
    def __init__(self, event: EventEnvelope) -> None:
        self.event = event
        self.calls: list[tuple[str, tuple, dict]] = []

    def xgroup_create(self, *args, **kwargs):
        self.calls.append(("xgroup_create", args, kwargs))

    def xreadgroup(self, *args, **kwargs):
        self.calls.append(("xreadgroup", args, kwargs))
        return [(b"workbench:events", [(b"12-0", {b"event": self.event.to_json().encode()})])]

    def xack(self, *args, **kwargs):
        self.calls.append(("xack", args, kwargs))
        return 1

    def xautoclaim(self, *args, **kwargs):
        self.calls.append(("xautoclaim", args, kwargs))
        return (b"0-0", [(b"13-0", {b"event": self.event.to_json().encode()})], [])


def test_redis_stream_supports_consumer_group_read_ack_and_reclaim() -> None:
    event = envelope()
    client = GroupRedis(event)
    bus = RedisStreamEventBus(client)

    bus.ensure_group("tasks")
    messages = bus.read_group("tasks", "worker-1", count=5, block_ms=250)
    assert messages[0][0] == "12-0"
    assert messages[0][1] == event
    assert bus.ack("tasks", "12-0") == 1

    reclaimed = bus.claim_pending("tasks", "worker-1", min_idle_ms=60_000, count=2)
    assert reclaimed[0][0] == "13-0"
    assert reclaimed[0][1] == event
    assert [name for name, _, _ in client.calls] == ["xgroup_create", "xreadgroup", "xack", "xautoclaim"]
