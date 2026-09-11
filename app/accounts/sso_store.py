"""SSO 授权 state 一次性仓储：内存与 PostgreSQL 两种实现。

设计要点：
- `consume` 必须一次性：取到即删除；不存在或已过期一律抛 `SsoStateNotFound`，
  过期项在返回前也已经被删除，避免被重复消费。
- PostgreSQL 用单条 `DELETE ... WHERE state = %s RETURNING ...` 保证原子一次性消费。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol


class SsoStateNotFound(LookupError):
    """SSO 授权 state 不存在、已消费或已过期。"""


@dataclass(frozen=True)
class SsoState:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    created_at: datetime


class SsoStateStore(Protocol):
    def add(self, value: SsoState) -> None: ...
    def consume(self, state: str, *, now: datetime | None = None, ttl_seconds: int) -> SsoState: ...
    def purge_expired(self, *, now: datetime | None = None, ttl_seconds: int) -> int: ...


class InMemorySsoStateStore:
    """开发期内存实现；读取即删除，过期项一并清除。"""

    def __init__(self) -> None:
        self._items: dict[str, SsoState] = {}
        self._lock = RLock()

    def add(self, value: SsoState) -> None:
        with self._lock:
            self._items[value.state] = value

    def consume(self, state: str, *, now: datetime | None = None, ttl_seconds: int) -> SsoState:
        moment = now or datetime.now(UTC)
        with self._lock:
            item = self._items.pop(state, None)
        if item is None:
            raise SsoStateNotFound(state)
        if moment - item.created_at > timedelta(seconds=ttl_seconds):
            raise SsoStateNotFound(state)
        return item

    def purge_expired(self, *, now: datetime | None = None, ttl_seconds: int) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(seconds=ttl_seconds)
        with self._lock:
            expired = [key for key, item in self._items.items() if item.created_at < cutoff]
            for key in expired:
                del self._items[key]
        return len(expired)


class PostgresSsoStateStore:
    """SSO state 持久化；consume 用单条 DELETE ... RETURNING 原子消费。"""

    _COLUMNS = "state, nonce, code_verifier, redirect_uri, created_at"

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> SsoState:
        return SsoState(
            state=str(row[0]),
            nonce=str(row[1]),
            code_verifier=str(row[2]),
            redirect_uri=str(row[3]),
            created_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC),
        )

    def add(self, value: SsoState) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_sso_states ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (state) DO NOTHING
                        """,
                        (
                            value.state,
                            value.nonce,
                            value.code_verifier,
                            value.redirect_uri,
                            value.created_at,
                        ),
                    )

    def consume(self, state: str, *, now: datetime | None = None, ttl_seconds: int) -> SsoState:
        moment = now or datetime.now(UTC)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM workbench_sso_states WHERE state = %s RETURNING {self._COLUMNS}",
                        (state,),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise SsoStateNotFound(state)
        item = self._hydrate(row)
        if moment - item.created_at > timedelta(seconds=ttl_seconds):
            raise SsoStateNotFound(state)
        return item

    def purge_expired(self, *, now: datetime | None = None, ttl_seconds: int) -> int:
        moment = now or datetime.now(UTC)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM workbench_sso_states
                        WHERE created_at < %s - make_interval(secs => %s)
                        """,
                        (moment, ttl_seconds),
                    )
                    return int(cursor.rowcount)
