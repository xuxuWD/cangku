from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

from .domain import PolicyError, UserContext
from .events import EventEnvelope


@dataclass
class DeadLetter:
    event: EventEnvelope
    error: str
    attempts: int = 1
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    replayed_at: datetime | None = None
    replayed_by: str | None = None

    @property
    def event_id(self) -> str:
        return self.event.event_id


class DeadLetterStore:
    """Development implementation; production should use a durable repository."""

    def __init__(self, event_bus) -> None:
        self.event_bus = event_bus
        self._items: dict[str, DeadLetter] = {}
        self._lock = RLock()

    def record(self, event: EventEnvelope, error: str, *, attempts: int = 1) -> DeadLetter:
        with self._lock:
            item = self._items.get(event.event_id)
            if item is not None:
                item.attempts = max(item.attempts, attempts)
                if error:
                    item.error = error[:500]
                return item
            item = DeadLetter(event=event, error=error[:500], attempts=max(1, attempts))
            self._items[event.event_id] = item
            return item

    def list(self, context: UserContext) -> list[DeadLetter]:
        self._ensure_admin(context)
        with self._lock:
            return [item for item in self._items.values() if item.event.tenant_id == context.tenant_id]

    def replay(self, context: UserContext, event_id: str) -> str:
        self._ensure_admin(context)
        with self._lock:
            item = self._items.get(event_id)
            if item is None or item.event.tenant_id != context.tenant_id:
                raise LookupError(event_id)
            if item.replayed_at is not None:
                return "already_replayed"
            self.event_bus.publish(item.event)
            item.replayed_at = datetime.now(UTC)
            item.replayed_by = context.user_id
            return "replayed"

    @staticmethod
    def _ensure_admin(context: UserContext) -> None:
        if context.role not in {"ceo", "super_admin"}:
            raise PolicyError("只有 CEO 或超级管理员可以处理死信事件")
