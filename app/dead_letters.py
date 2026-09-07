from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from contextlib import contextmanager, nullcontext
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


class PostgresDeadLetterStore:
    """Durable dead-letter repository using a connection or connection pool."""

    def __init__(self, connection_or_pool, event_bus) -> None:
        self.connection = connection_or_pool
        self.event_bus = event_bus

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    def record(self, event: EventEnvelope, error: str, *, attempts: int = 1) -> DeadLetter:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_dead_letters
                            (event_id, tenant_id, aggregate_type, aggregate_id, version, sequence,
                             dedupe_key, action, payload, attempts, last_error, occurred_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE
                        SET attempts = GREATEST(workbench_dead_letters.attempts, EXCLUDED.attempts),
                            last_error = EXCLUDED.last_error
                        RETURNING event_id, tenant_id, aggregate_type, aggregate_id, version,
                                  sequence, dedupe_key, action, payload, attempts, last_error,
                                  occurred_at, replayed_at, replayed_by
                        """,
                        (
                            event.event_id, event.tenant_id, event.aggregate_type, event.aggregate_id,
                            event.version, event.sequence, event.dedupe_key, event.action,
                            json.dumps(event.payload, ensure_ascii=False), max(1, attempts), error[:500],
                            event.occurred_at,
                        ),
                    )
                    row = cursor.fetchone()
                    return self._row_to_dead_letter(row)

    def list(self, context: UserContext) -> list[DeadLetter]:
        self._ensure_admin(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, tenant_id, aggregate_type, aggregate_id, version,
                           sequence, dedupe_key, action, payload, attempts, last_error,
                           occurred_at, replayed_at, replayed_by
                    FROM workbench_dead_letters
                    WHERE tenant_id = %s
                    ORDER BY recorded_at, event_id
                    """,
                    (context.tenant_id,),
                )
                return [self._row_to_dead_letter(row) for row in cursor.fetchall()]

    def replay(self, context: UserContext, event_id: str) -> str:
        self._ensure_admin(context)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT event_id, tenant_id, aggregate_type, aggregate_id, version,
                               sequence, dedupe_key, action, payload, attempts, last_error,
                               occurred_at, replayed_at, replayed_by
                        FROM workbench_dead_letters
                        WHERE event_id = %s AND tenant_id = %s
                        FOR UPDATE
                        """,
                        (event_id, context.tenant_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise LookupError(event_id)
                    item = self._row_to_dead_letter(row)
                    if item.replayed_at is not None:
                        return "already_replayed"
                    self.event_bus.publish(item.event)
                    cursor.execute(
                        """
                        UPDATE workbench_dead_letters
                        SET replayed_at = now(), replayed_by = %s
                        WHERE event_id = %s AND tenant_id = %s AND replayed_at IS NULL
                        """,
                        (context.user_id, event_id, context.tenant_id),
                    )
                    return "replayed"

    @staticmethod
    def _row_to_dead_letter(row: tuple) -> DeadLetter:
        payload = row[8]
        if isinstance(payload, str):
            payload = json.loads(payload)
        event = EventEnvelope(
            event_id=str(row[0]), tenant_id=str(row[1]), aggregate_type=str(row[2]),
            aggregate_id=str(row[3]), version=int(row[4]), sequence=int(row[5]),
            dedupe_key=str(row[6]), action=str(row[7]),
            occurred_at=row[11] if isinstance(row[11], datetime) else datetime.fromisoformat(str(row[11])),
            payload=dict(payload or {}),
        )
        return DeadLetter(
            event=event, attempts=int(row[9]), error=str(row[10]),
            recorded_at=event.occurred_at, replayed_at=row[12], replayed_by=row[13],
        )

    @staticmethod
    def _ensure_admin(context: UserContext) -> None:
        if context.role not in {"ceo", "super_admin"}:
            raise PolicyError("只有 CEO 或超级管理员可以处理死信事件")
