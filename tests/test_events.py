from datetime import UTC, datetime

from app.events import EventEnvelope, InMemoryEventBus, IdempotentEventConsumer


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
