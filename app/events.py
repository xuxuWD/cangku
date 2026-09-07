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

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EventEnvelope":
        occurred_at = value["occurred_at"]
        if not isinstance(occurred_at, datetime):
            occurred_at = datetime.fromisoformat(str(occurred_at))
        return cls(
            event_id=str(value["event_id"]),
            tenant_id=str(value["tenant_id"]),
            aggregate_type=str(value["aggregate_type"]),
            aggregate_id=str(value["aggregate_id"]),
            version=int(value["version"]),
            sequence=int(value["sequence"]),
            dedupe_key=str(value["dedupe_key"]),
            action=str(value["action"]),
            occurred_at=occurred_at,
            payload=dict(value.get("payload") or {}),
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> "EventEnvelope":
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return cls.from_dict(json.loads(value))


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

    def read_recent(self, *, limit: int = 50) -> list[EventEnvelope]:
        with self._lock:
            if limit <= 0:
                return []
            return self._events[-limit:]


class RedisStreamEventBus:
    """Redis Streams adapter; publishing uses XADD and consumers can replay by sequence."""

    def __init__(self, client, stream: str = "workbench:events") -> None:
        self.client = client
        self.stream = stream

    def publish(self, event: EventEnvelope) -> str:
        return str(self.client.xadd(self.stream, {"event": event.to_json()}, id="*"))

    def read_recent(self, *, limit: int = 50) -> list[EventEnvelope]:
        if limit <= 0:
            return []
        rows = self.client.xrevrange(self.stream, max="+", min="-", count=limit)
        return [event for _message_id, event in reversed(self._decode_messages([(self.stream, rows)]))]

    def ensure_group(self, group: str, *, start_id: str = "0-0") -> None:
        try:
            self.client.xgroup_create(self.stream, group, id=start_id, mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc).upper():
                raise

    def read_group(
        self,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 1000,
        message_id: str = ">",
    ) -> list[tuple[str, EventEnvelope]]:
        rows = self.client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={self.stream: message_id},
            count=count,
            block=block_ms,
        )
        return self._decode_messages(rows)

    def ack(self, group: str, *message_ids: str) -> int:
        if not message_ids:
            return 0
        return int(self.client.xack(self.stream, group, *message_ids))

    def claim_pending(
        self,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 60_000,
        count: int = 100,
        start_id: str = "0-0",
    ) -> list[tuple[str, EventEnvelope]]:
        result = self.client.xautoclaim(
            self.stream,
            group,
            consumer,
            min_idle_ms,
            start_id,
            count=count,
        )
        messages = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
        return self._decode_messages([(self.stream, messages)])

    @staticmethod
    def _decode_messages(rows) -> list[tuple[str, EventEnvelope]]:
        decoded: list[tuple[str, EventEnvelope]] = []
        for _stream_name, messages in rows or []:
            for message_id, fields in messages:
                event_json = fields.get("event") or fields.get(b"event")
                if event_json is None:
                    raise ValueError("Redis Stream message missing event field")
                decoded.append((
                    message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id),
                    EventEnvelope.from_json(event_json),
                ))
        return decoded


class IdempotentEventConsumer:
    def __init__(
        self,
        *,
        max_attempts: int = 3,
        on_dead_letter: Callable[[EventEnvelope], None] | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.on_dead_letter = on_dead_letter
        self._attempts: dict[str, int] = {}
        self._processed: set[str] = set()
        self._dead_lettered: set[str] = set()
        self.dead_letters: list[EventEnvelope] = []
        self._lock = RLock()

    @property
    def processed_count(self) -> int:
        return len(self._processed)

    def handle(self, event: EventEnvelope, handler: Callable[[EventEnvelope], None]) -> str:
        with self._lock:
            if event.dedupe_key in self._processed:
                return "duplicate"
            if event.dedupe_key in self._dead_lettered:
                return "dead_letter"
            try:
                handler(event)
            except Exception:
                attempts = self._attempts.get(event.dedupe_key, 0) + 1
                self._attempts[event.dedupe_key] = attempts
                if attempts >= self.max_attempts:
                    self._dead_lettered.add(event.dedupe_key)
                    self.dead_letters.append(event)
                    if self.on_dead_letter:
                        self.on_dead_letter(event)
                    return "dead_letter"
                return "retry"
            self._processed.add(event.dedupe_key)
            return "processed"
