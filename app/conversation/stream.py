"""实时流仓储（P2b §2.1 / §2.2）：帧明细 append-only + 状态每 run 一行 + 序号分配 + 熔断 + 清理。

口径（真源 `docs/superpowers/specs/2026-09-17-realtime-stream-p2b-design.md`，已评审 2026-09-17）：
- **先落库、再推送**；序号由状态行**原子递增**（与插帧同事务）⇒ 不重复、不跳号。
- **双上限熔断**（`max_frames` / `max_bytes`）：超限 ⇒ 状态置 `unavailable`，由**写入网关**追加
  一帧显式告知（`stream.unavailable`，`is_terminal=true`）——**不静默丢帧**。
- **不做「换 run 清旧帧」**：同一会话多 run 各自独立；悬挂由 `mark_stalled` 兜底收口（§2.2 说明）。
- **清理只删本两表**：消息表 / 审计 / 运行事件不受影响；清理按 `expires_at`（终态时置位）。
- 脱敏（`redact_payload`）在**写入网关**完成（本模块只落库）；表约束含复合外键（跨租户拒写）。

内存实现与 PG 实现**方法集一致**；PG 用单连接或连接池（与既有 store 同手法）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any

# 帧 kind 的固定取值域（§2.5）：消息两种 + 系统一种；过程事件复用 RuntimeEventType 十种原值。
MESSAGE_USER_KIND = "message.user"
MESSAGE_ASSISTANT_KIND = "message.assistant"
UNAVAILABLE_KIND = "stream.unavailable"

# 熔断受控原因（写入审计 `conversation.stream.unavailable` 的 reason，受控枚举）。
REASON_FRAME_LIMIT = "frame_limit"
REASON_BYTE_LIMIT = "byte_limit"
REASON_WRITE_FAILED = "write_failed"
REASON_STALLED = "stalled"

STATUS_STREAMING = "streaming"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_UNAVAILABLE = "unavailable"

MAX_LIST_LIMIT = 1000


def _now() -> datetime:
    return datetime.now(UTC)


def _payload_bytes(payload: dict[str, Any]) -> int:
    """payload 的规范化字节数（与写入同一序列化口径）。"""
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIST_LIMIT))


@dataclass(frozen=True)
class StreamFrame:
    tenant_id: str
    conversation_id: str
    run_id: str
    seq: int
    kind: str
    payload: dict[str, Any]
    is_terminal: bool
    created_at: datetime


@dataclass
class StreamState:
    tenant_id: str
    conversation_id: str
    run_id: str
    last_seq: int = 0
    frame_count: int = 0
    byte_count: int = 0
    is_terminal: bool = False
    status: str = STATUS_STREAMING
    persisted_to_message_id: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


class InMemoryStreamStore:
    """内存流仓储（development / 测试）。"""

    def __init__(self, *, max_frames: int = 2000, max_bytes: int = 4 * 1024 * 1024) -> None:
        self._lock = RLock()
        self._frames: dict[tuple[str, str, str], list[StreamFrame]] = {}
        self._states: dict[tuple[str, str, str], StreamState] = {}
        self.max_frames = int(max_frames)
        self.max_bytes = int(max_bytes)

    def append_frame(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
        is_terminal: bool = False,
        now: datetime | None = None,
    ) -> StreamFrame | None:
        """原子追加一帧；熔断（帧数 / 字节）或已不可写时返回 `None`（调用方追加告知帧）。"""
        reference = now or _now()
        size = _payload_bytes(payload)
        with self._lock:
            key = (tenant_id, conversation_id, run_id)
            state = self._states.get(key)
            if state is None:
                state = StreamState(tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id)
                self._states[key] = state
                self._frames[key] = []
            if state.status == STATUS_UNAVAILABLE:
                return None
            if state.frame_count + 1 > self.max_frames or state.byte_count + size > self.max_bytes:
                return None
            frame = StreamFrame(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=run_id,
                seq=state.last_seq + 1,
                kind=kind,
                payload=dict(payload),
                is_terminal=is_terminal,
                created_at=reference,
            )
            state.last_seq += 1
            state.frame_count += 1
            state.byte_count += size
            state.updated_at = reference
            self._frames[key].append(frame)
            return frame

    def list_frames(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[StreamFrame]:
        with self._lock:
            frames = self._frames.get((tenant_id, conversation_id, run_id), [])
            return [frame for frame in frames if frame.seq > after_seq][: _clamp(limit)]

    def get_state(self, tenant_id: str, conversation_id: str, run_id: str) -> StreamState | None:
        with self._lock:
            state = self._states.get((tenant_id, conversation_id, run_id))
            return None if state is None else StreamState(**vars(state))

    def latest_run_id(self, tenant_id: str, conversation_id: str) -> str | None:
        """活跃优先，否则最新（按 updated_at）。"""
        with self._lock:
            candidates = [
                state
                for (tid, cid, _), state in self._states.items()
                if tid == tenant_id and cid == conversation_id
            ]
        if not candidates:
            return None
        active = [state for state in candidates if state.status == STATUS_STREAMING]
        pool = active or candidates
        return max(pool, key=lambda state: state.updated_at).run_id

    def set_terminal(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        status: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        with self._lock:
            state = self._states.get((tenant_id, conversation_id, run_id))
            if state is None:
                return
            state.status = status
            state.is_terminal = True
            state.expires_at = expires_at
            state.updated_at = now or _now()

    def reopen_if_terminal(self, tenant_id: str, conversation_id: str, run_id: str) -> bool:
        """P2c-2 §2.8：决议后推进前，把**已终态**的流状态先行重开（`seq` 继续单调）。

        - 仅对 `completed` / `failed` 生效（`status` 置回 `streaming`、清 `expires_at`）；
        - `unavailable`（熔断 / 悬挂兜底）**不复活**——该 run 已显式告知「过程流不可用」；
        - 状态行不存在（该 run 从未开流）⇒ 不创建（零破坏：旧端点 / `mock` 路径无流）。
        """
        with self._lock:
            state = self._states.get((tenant_id, conversation_id, run_id))
            if state is None or not state.is_terminal or state.status == STATUS_UNAVAILABLE:
                return False
            state.status = STATUS_STREAMING
            state.is_terminal = False
            state.expires_at = None
            state.updated_at = _now()
            return True

    def set_unavailable(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        with self._lock:
            state = self._states.get((tenant_id, conversation_id, run_id))
            if state is None:
                state = StreamState(tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id)
                self._states[(tenant_id, conversation_id, run_id)] = state
                self._frames[(tenant_id, conversation_id, run_id)] = []
            state.status = STATUS_UNAVAILABLE
            state.is_terminal = True
            state.expires_at = expires_at
            state.updated_at = now or _now()

    def append_unavailable(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> StreamFrame:
        """追加**显式告知帧**（`stream.unavailable`）：**绕过双上限**、每 run 至多一条（幂等）。

        同时把状态置 `unavailable` + `is_terminal` + `expires_at`；重复调用返回既有告知帧。
        """
        reference = now or _now()
        with self._lock:
            key = (tenant_id, conversation_id, run_id)
            state = self._states.get(key)
            if state is None:
                state = StreamState(tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id)
                self._states[key] = state
                self._frames[key] = []
            frames = self._frames[key]
            existing = next((frame for frame in frames if frame.kind == UNAVAILABLE_KIND), None)
            if existing is not None:
                state.status = STATUS_UNAVAILABLE
                state.is_terminal = True
                state.expires_at = expires_at
                state.updated_at = reference
                return existing
            payload = {"reason": reason}
            frame = StreamFrame(
                tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id,
                seq=state.last_seq + 1, kind=UNAVAILABLE_KIND, payload=payload,
                is_terminal=True, created_at=reference,
            )
            state.last_seq += 1
            state.frame_count += 1
            state.byte_count += _payload_bytes(payload)
            state.status = STATUS_UNAVAILABLE
            state.is_terminal = True
            state.expires_at = expires_at
            state.updated_at = reference
            frames.append(frame)
            return frame

    def persist_watermark(
        self, tenant_id: str, conversation_id: str, run_id: str, message_id: str
    ) -> None:
        with self._lock:
            state = self._states.get((tenant_id, conversation_id, run_id))
            if state is not None:
                state.persisted_to_message_id = message_id

    def mark_stalled(self, *, cutoff: datetime, expires_at: datetime) -> int:
        """悬挂兜底：未终态且 `updated_at < cutoff` ⇒ 置 `unavailable('stalled')`；返回处理数。"""
        changed = 0
        with self._lock:
            for state in self._states.values():
                if state.status == STATUS_STREAMING and state.updated_at < cutoff:
                    state.status = STATUS_UNAVAILABLE
                    state.is_terminal = True
                    state.expires_at = expires_at
                    state.updated_at = _now()
                    changed += 1
        return changed

    def purge_expired(self, *, cutoff: datetime) -> int:
        """删除 `expires_at < cutoff` 的 run（帧 + 状态行）；返回删除 run 数。"""
        with self._lock:
            keys = [
                key
                for key, state in self._states.items()
                if state.expires_at is not None and state.expires_at < cutoff
            ]
            for key in keys:
                self._states.pop(key, None)
                self._frames.pop(key, None)
            return len(keys)


_FRAME_COLUMNS = "tenant_id, conversation_id, run_id, seq, kind, payload, is_terminal, created_at"
_STATE_COLUMNS = (
    "tenant_id, conversation_id, run_id, last_seq, frame_count, byte_count, is_terminal, status, "
    "persisted_to_message_id, expires_at, created_at, updated_at"
)


class PostgresStreamStore:
    """PG 流仓储（迁移 036）；序号分配与写帧**同事务**。"""

    def __init__(self, connection_or_pool, *, max_frames: int = 2000, max_bytes: int = 4 * 1024 * 1024) -> None:
        self.connection = connection_or_pool
        self.max_frames = int(max_frames)
        self.max_bytes = int(max_bytes)

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _frame(row: tuple) -> StreamFrame:
        payload = row[5]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return StreamFrame(
            tenant_id=str(row[0]), conversation_id=str(row[1]), run_id=str(row[2]), seq=int(row[3]),
            kind=str(row[4]), payload=dict(payload or {}), is_terminal=bool(row[6]), created_at=row[7],
        )

    @staticmethod
    def _state(row: tuple) -> StreamState:
        return StreamState(
            tenant_id=str(row[0]), conversation_id=str(row[1]), run_id=str(row[2]), last_seq=int(row[3]),
            frame_count=int(row[4]), byte_count=int(row[5]), is_terminal=bool(row[6]), status=str(row[7]),
            persisted_to_message_id=None if row[8] is None else str(row[8]), expires_at=row[9],
            created_at=row[10], updated_at=row[11],
        )

    def append_frame(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
        is_terminal: bool = False,
        now: datetime | None = None,
    ) -> StreamFrame | None:
        reference = now or _now()
        size = _payload_bytes(payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # 序号原子分配：INSERT ... ON CONFLICT DO UPDATE（同事务内），并回读计数做熔断判定。
                    cursor.execute(
                        """
                        INSERT INTO workbench_conversation_stream_state
                            (tenant_id, conversation_id, run_id, last_seq, frame_count, byte_count)
                        VALUES (%s, %s, %s, 0, 0, 0)
                        ON CONFLICT (tenant_id, conversation_id, run_id) DO NOTHING
                        """,
                        (tenant_id, conversation_id, run_id),
                    )
                    cursor.execute(
                        f"SELECT {_STATE_COLUMNS} FROM workbench_conversation_stream_state "
                        "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s FOR UPDATE",
                        (tenant_id, conversation_id, run_id),
                    )
                    state = self._state(cursor.fetchone())
                    if state.status == STATUS_UNAVAILABLE:
                        return None
                    if state.frame_count + 1 > self.max_frames or state.byte_count + size > self.max_bytes:
                        return None
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET last_seq = last_seq + 1, frame_count = frame_count + 1,
                            byte_count = byte_count + %s, updated_at = %s
                        WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                        RETURNING last_seq
                        """,
                        (size, reference, tenant_id, conversation_id, run_id),
                    )
                    seq = int(cursor.fetchone()[0])
                    cursor.execute(
                        f"INSERT INTO workbench_conversation_stream_frames ({_FRAME_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                        (tenant_id, conversation_id, run_id, seq, kind, encoded, is_terminal, reference),
                    )
        return StreamFrame(
            tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id, seq=seq, kind=kind,
            payload=dict(payload), is_terminal=is_terminal, created_at=reference,
        )

    def list_frames(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[StreamFrame]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_FRAME_COLUMNS} FROM workbench_conversation_stream_frames "
                    "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s AND seq > %s "
                    "ORDER BY seq LIMIT %s",
                    (tenant_id, conversation_id, run_id, int(after_seq), _clamp(limit)),
                )
                rows = cursor.fetchall()
        return [self._frame(row) for row in rows]

    def get_state(self, tenant_id: str, conversation_id: str, run_id: str) -> StreamState | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_STATE_COLUMNS} FROM workbench_conversation_stream_state "
                    "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s",
                    (tenant_id, conversation_id, run_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._state(row)

    def latest_run_id(self, tenant_id: str, conversation_id: str) -> str | None:
        """活跃优先，否则最新（`status='streaming'` 优先，其次 `updated_at DESC`）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT run_id FROM workbench_conversation_stream_state
                    WHERE tenant_id = %s AND conversation_id = %s
                    ORDER BY (status = 'streaming') DESC, updated_at DESC
                    LIMIT 1
                    """,
                    (tenant_id, conversation_id),
                )
                row = cursor.fetchone()
        return None if row is None else str(row[0])

    def set_terminal(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        status: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET status = %s, is_terminal = true, expires_at = %s, updated_at = %s
                        WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                        """,
                        (status, expires_at, now or _now(), tenant_id, conversation_id, run_id),
                    )

    def reopen_if_terminal(self, tenant_id: str, conversation_id: str, run_id: str) -> bool:
        """P2c-2 §2.8：决议后推进前，把**已终态**的流状态先行重开（`seq` 继续单调）。

        仅对 `completed` / `failed` 生效；`unavailable` **不复活**；状态行不存在 ⇒ 不创建。
        返回是否发生了重开。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET status = 'streaming', is_terminal = false, expires_at = NULL, updated_at = %s
                        WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                          AND is_terminal = true AND status <> 'unavailable'
                        """,
                        (_now(), tenant_id, conversation_id, run_id),
                    )
                    return cursor.rowcount > 0

    def set_unavailable(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        del reason  # reason 由写入网关写入告知帧与审计；状态行只记 unavailable
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_conversation_stream_state
                            (tenant_id, conversation_id, run_id, status, is_terminal, expires_at, updated_at)
                        VALUES (%s, %s, %s, 'unavailable', true, %s, %s)
                        ON CONFLICT (tenant_id, conversation_id, run_id)
                        DO UPDATE SET status = 'unavailable', is_terminal = true,
                                      expires_at = EXCLUDED.expires_at, updated_at = EXCLUDED.updated_at
                        """,
                        (tenant_id, conversation_id, run_id, expires_at, now or _now()),
                    )

    def persist_watermark(
        self, tenant_id: str, conversation_id: str, run_id: str, message_id: str
    ) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET persisted_to_message_id = %s, updated_at = now()
                        WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                        """,
                        (message_id, tenant_id, conversation_id, run_id),
                    )

    def append_unavailable(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> StreamFrame:
        """追加**显式告知帧**（`stream.unavailable`）：**绕过双上限**、每 run 至多一条（幂等）。"""
        reference = now or _now()
        encoded = json.dumps({"reason": reason}, ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_conversation_stream_state
                            (tenant_id, conversation_id, run_id)
                        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                        """,
                        (tenant_id, conversation_id, run_id),
                    )
                    cursor.execute(
                        f"SELECT {_STATE_COLUMNS} FROM workbench_conversation_stream_state "
                        "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s FOR UPDATE",
                        (tenant_id, conversation_id, run_id),
                    )
                    cursor.fetchone()  # FOR UPDATE 锁行（序号分配在该行上串行化）
                    cursor.execute(
                        f"SELECT {_FRAME_COLUMNS} FROM workbench_conversation_stream_frames "
                        "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s AND kind = %s "
                        "ORDER BY seq LIMIT 1",
                        (tenant_id, conversation_id, run_id, UNAVAILABLE_KIND),
                    )
                    existing_row = cursor.fetchone()
                    if existing_row is not None:
                        cursor.execute(
                            """
                            UPDATE workbench_conversation_stream_state
                            SET status = 'unavailable', is_terminal = true, expires_at = %s, updated_at = %s
                            WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                            """,
                            (expires_at, reference, tenant_id, conversation_id, run_id),
                        )
                        return self._frame(existing_row)
                    size = len(encoded.encode("utf-8"))
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET last_seq = last_seq + 1, frame_count = frame_count + 1,
                            byte_count = byte_count + %s, status = 'unavailable',
                            is_terminal = true, expires_at = %s, updated_at = %s
                        WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s
                        RETURNING last_seq
                        """,
                        (size, expires_at, reference, tenant_id, conversation_id, run_id),
                    )
                    seq = int(cursor.fetchone()[0])
                    cursor.execute(
                        f"INSERT INTO workbench_conversation_stream_frames ({_FRAME_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, true, %s)",
                        (tenant_id, conversation_id, run_id, seq, UNAVAILABLE_KIND, encoded, reference),
                    )
        return StreamFrame(
            tenant_id=tenant_id, conversation_id=conversation_id, run_id=run_id, seq=seq,
            kind=UNAVAILABLE_KIND, payload={"reason": reason}, is_terminal=True, created_at=reference,
        )

    def mark_stalled(self, *, cutoff: datetime, expires_at: datetime) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_conversation_stream_state
                        SET status = 'unavailable', is_terminal = true, expires_at = %s, updated_at = now()
                        WHERE status = 'streaming' AND updated_at < %s
                        """,
                        (expires_at, cutoff),
                    )
                    return int(cursor.rowcount or 0)

    def purge_expired(self, *, cutoff: datetime) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT tenant_id, conversation_id, run_id
                        FROM workbench_conversation_stream_state
                        WHERE expires_at IS NOT NULL AND expires_at < %s
                        """,
                        (cutoff,),
                    )
                    keys = [(str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()]
                    for tenant_id, conversation_id, run_id in keys:
                        cursor.execute(
                            "DELETE FROM workbench_conversation_stream_frames "
                            "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s",
                            (tenant_id, conversation_id, run_id),
                        )
                        cursor.execute(
                            "DELETE FROM workbench_conversation_stream_state "
                            "WHERE tenant_id = %s AND conversation_id = %s AND run_id = %s",
                            (tenant_id, conversation_id, run_id),
                        )
                    return len(keys)