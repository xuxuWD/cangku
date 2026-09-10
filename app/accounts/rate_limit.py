from __future__ import annotations

import hashlib
import hmac
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol


class LoginRateLimited(ValueError):
    """账号已被登录失败锁定。"""


@dataclass(frozen=True)
class LoginAttemptState:
    phone_hash: str
    failure_count: int
    window_started_at: datetime
    locked_until: datetime | None = None


class LoginAttemptStore(Protocol):
    def load(self, phone_hash: str) -> LoginAttemptState | None: ...
    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState: ...
    def clear(self, phone_hash: str) -> None: ...


class InMemoryLoginAttemptStore:
    """开发期内存实现；计数与窗口推进在同一把锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, LoginAttemptState] = {}
        self._lock = RLock()

    def dump_keys(self) -> set[str]:
        with self._lock:
            return set(self._items)

    def load(self, phone_hash: str) -> LoginAttemptState | None:
        with self._lock:
            return self._items.get(phone_hash)

    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState:
        with self._lock:
            current = self._items.get(phone_hash)
            if current is None or now - current.window_started_at >= timedelta(seconds=window_seconds):
                state = LoginAttemptState(phone_hash=phone_hash, failure_count=1, window_started_at=now)
            else:
                state = replace(current, failure_count=current.failure_count + 1)
            if state.failure_count >= max_failures:
                state = replace(state, locked_until=now + timedelta(seconds=lock_seconds))
            self._items[phone_hash] = state
            return state

    def clear(self, phone_hash: str) -> None:
        with self._lock:
            self._items.pop(phone_hash, None)


class LoginRateLimiter:
    """按手机号的失败计数与锁定；手机号只以 HMAC 哈希形式接触仓储。"""

    def __init__(
        self,
        store: LoginAttemptStore,
        *,
        secret: str,
        max_failures: int,
        window_seconds: int,
        lock_seconds: int,
    ) -> None:
        self.store = store
        self.secret = secret
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds

    def phone_hash(self, phone: str) -> str:
        return hmac.new(self.secret.encode(), phone.encode(), hashlib.sha256).hexdigest()

    def is_locked(self, phone: str, *, now: datetime | None = None) -> bool:
        state = self.store.load(self.phone_hash(phone))
        if state is None or state.locked_until is None:
            return False
        return (now or datetime.now(UTC)) < state.locked_until

    def require_unlocked(self, phone: str, *, now: datetime | None = None) -> None:
        if self.is_locked(phone, now=now):
            raise LoginRateLimited("登录尝试过于频繁，请稍后再试")

    def register_failure(self, phone: str, *, now: datetime | None = None) -> LoginAttemptState:
        return self.store.record_failure(
            self.phone_hash(phone),
            now=now or datetime.now(UTC),
            window_seconds=self.window_seconds,
            max_failures=self.max_failures,
            lock_seconds=self.lock_seconds,
        )

    def register_success(self, phone: str) -> None:
        self.store.clear(self.phone_hash(phone))


class PostgresLoginAttemptStore:
    """登录尝试持久化；record_failure 用单条 upsert 原子完成窗口判断、计数与锁定。"""

    _COLUMNS = "phone_hash, failure_count, window_started_at, locked_until"

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
    def _hydrate(row: tuple) -> LoginAttemptState:
        return LoginAttemptState(
            phone_hash=str(row[0]),
            failure_count=int(row[1]),
            window_started_at=row[2],
            locked_until=row[3],
        )

    def load(self, phone_hash: str) -> LoginAttemptState | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._COLUMNS} FROM workbench_login_attempts WHERE phone_hash = %s",
                    (phone_hash,),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState:
        window_cutoff = now - timedelta(seconds=window_seconds)
        lock_until = now + timedelta(seconds=lock_seconds)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_login_attempts
                            (phone_hash, failure_count, window_started_at, locked_until, updated_at)
                        VALUES (%s, 1, %s, CASE WHEN 1 >= %s THEN %s ELSE NULL END, now())
                        ON CONFLICT (phone_hash) DO UPDATE SET
                            failure_count = CASE
                                WHEN workbench_login_attempts.window_started_at <= %s THEN 1
                                ELSE workbench_login_attempts.failure_count + 1 END,
                            window_started_at = CASE
                                WHEN workbench_login_attempts.window_started_at <= %s THEN %s
                                ELSE workbench_login_attempts.window_started_at END,
                            locked_until = CASE
                                WHEN (CASE
                                        WHEN workbench_login_attempts.window_started_at <= %s THEN 1
                                        ELSE workbench_login_attempts.failure_count + 1 END) >= %s
                                    THEN %s
                                ELSE NULL END,
                            updated_at = now()
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            phone_hash,
                            now,
                            max_failures,
                            lock_until,
                            window_cutoff,
                            window_cutoff,
                            now,
                            window_cutoff,
                            max_failures,
                            lock_until,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RuntimeError("登录尝试写入失败")
        return self._hydrate(row)

    def clear(self, phone_hash: str) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_login_attempts WHERE phone_hash = %s", (phone_hash,)
                    )
