"""会话令牌的服务端撤销名单（登出立即生效）。

背景
    会话令牌是无状态 HMAC 令牌。此前登出只靠客户端丢弃令牌 + 短期 TTL 兜底，
    服务端无法让已签发的令牌提前失效。本模块按令牌的 ``jti`` 记录撤销。

设计
    - 只记录 ``jti`` 与**令牌自身的过期时间**；判定时按 ``expires_at > now()`` 过滤，
      因此令牌过期后条目自然失效，无需与 TTL 对齐的定时清理任务（PostgreSQL 实现
      在写入时顺带删除过期行，避免表无限增长）。
    - ``revoke`` 幂等：重复撤销同一 ``jti`` 不报错。
    - 内存实现仅供开发与单测；生产使用 PostgreSQL 表 ``workbench_session_revocations``。
    - **fail-closed**：存储层异常向上抛出，由接口层按「无法校验会话状态」拒绝请求，
      绝不因为查不到记录就放行。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol


class SessionRevocationStore(Protocol):
    def revoke(self, token_id: str, *, expires_at: datetime) -> None: ...
    def is_revoked(self, token_id: str) -> bool: ...


class InMemorySessionRevocationStore:
    """开发期内存撤销名单；过期条目在读写时惰性清理。"""

    def __init__(self) -> None:
        self._revoked: dict[str, datetime] = {}
        self._lock = RLock()

    def revoke(self, token_id: str, *, expires_at: datetime) -> None:
        with self._lock:
            self._revoked[token_id] = expires_at
            self._purge()

    def is_revoked(self, token_id: str) -> bool:
        with self._lock:
            self._purge()
            expires_at = self._revoked.get(token_id)
            return expires_at is not None and expires_at > datetime.now(UTC)

    def _purge(self) -> None:
        now = datetime.now(UTC)
        for key in [key for key, expires_at in self._revoked.items() if expires_at <= now]:
            self._revoked.pop(key, None)


class PostgresSessionRevocationStore:
    """持久化撤销名单；判定按令牌过期时间过滤。"""

    _INSERT = """
        INSERT INTO workbench_session_revocations (token_id, expires_at)
        VALUES (%s, %s)
        ON CONFLICT (token_id) DO UPDATE SET expires_at = EXCLUDED.expires_at
        """
    _PURGE = "DELETE FROM workbench_session_revocations WHERE expires_at <= now()"
    _SELECT = (
        "SELECT 1 FROM workbench_session_revocations "
        "WHERE token_id = %s AND expires_at > now()"
    )

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

    def revoke(self, token_id: str, *, expires_at: datetime) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(self._INSERT, (token_id, expires_at))
                    cursor.execute(self._PURGE)

    def is_revoked(self, token_id: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._SELECT, (token_id,))
                return cursor.fetchone() is not None
