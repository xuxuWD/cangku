from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import datetime

from .events import EventEnvelope


class OutboxPublisher:
    """Publishes committed Outbox rows and marks only successful deliveries."""

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

    def publish_pending(self, *, limit: int = 100) -> int:
        published = 0
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT event_id, tenant_id, aggregate_type, aggregate_id, version,
                               sequence, dedupe_key, action, payload, occurred_at
                        FROM workbench_event_outbox
                        WHERE published_at IS NULL
                        ORDER BY occurred_at, event_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cursor.fetchall()
                    for row in rows:
                        event = self._row_to_event(row)
                        try:
                            self.event_bus.publish(event)
                        except Exception as exc:
                            cursor.execute(
                                """
                                UPDATE workbench_event_outbox
                                SET attempts = attempts + 1, last_error = %s
                                WHERE event_id = %s
                                """,
                                (str(exc)[:500], row[0]),
                            )
                            continue
                        cursor.execute(
                            """
                            UPDATE workbench_event_outbox
                            SET published_at = now(), last_error = NULL
                            WHERE event_id = %s AND published_at IS NULL
                            """,
                            (row[0],),
                        )
                        published += 1
        return published

    @staticmethod
    def _row_to_event(row: tuple) -> EventEnvelope:
        payload = row[8]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return EventEnvelope(
            event_id=str(row[0]),
            tenant_id=str(row[1]),
            aggregate_type=str(row[2]),
            aggregate_id=str(row[3]),
            version=int(row[4]),
            sequence=int(row[5]),
            dedupe_key=str(row[6]),
            action=str(row[7]),
            occurred_at=row[9] if isinstance(row[9], datetime) else datetime.fromisoformat(str(row[9])),
            payload=dict(payload or {}),
        )
