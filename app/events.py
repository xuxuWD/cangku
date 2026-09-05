from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Callable


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    version: int
    sequence: int
    dedupe_key: str
    action: str
    occurred_at: datetime
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "version": self.version,
            "sequence": self.sequence,
            "dedupe_key": self.dedupe_key,
            "action": self.action,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []
        self._lock = RLock()

    def publish(self, event: EventEnvelope) -> None:
        with self._lock:
            self._events.append(event)

    def read(self, consumer: str, *, after_sequence: int = 0, limit: int | None = None) -> list[EventEnvelope]:
        del consumer
        with self._lock:
            events = [event for event in self._events if event.sequence > after_sequence]
            return events if limit is None else events[:limit]


class RedisStreamEventBus:
    """Redis Streams adapter; publishing uses XADD and consumers can replay by sequence."""

    def __init__(self, client, stream: str = "workbench:events") -> None:
        self.client = client
        self.stream = stream

    def publish(self, event: EventEnvelope) -> str:
        return str(self.client.xadd(self.stream, {"event": event.to_json()}, id="*"))


class IdempotentEventConsumer:
    def __init__(self, *, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self._attempts: dict[str, int] = {}
        self._processed: set[str] = set()
        self.dead_letters: list[EventEnvelope] = []
        self._lock = RLock()

    @property
    def processed_count(self) -> int:
        return len(self._processed)

    def handle(self, event: EventEnvelope, handler: Callable[[EventEnvelope], None]) -> str:
        with self._lock:
            if event.dedupe_key in self._processed:
                return "duplicate"
            try:
                handler(event)
            except Exception:
                attempts = self._attempts.get(event.dedupe_key, 0) + 1
                self._attempts[event.dedupe_key] = attempts
                if attempts >= self.max_attempts:
                    self.dead_letters.append(event)
                    return "dead_letter"
                return "retry"
            self._processed.add(event.dedupe_key)
            return "processed"
