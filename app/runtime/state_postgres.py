"""运行时状态的 PostgreSQL 仓储。

单独成模块是为了避开循环导入：`serialization` 需要 `RuntimeState`，
而本模块需要 `serialization`；若把本类放进 `state.py` 就会形成环。

写入策略（2026-09-16「运行事件有界」改造后）：
  - **事件**（append-only）单行写入 `workbench_runtime_events`，主键 `(run_id, sequence)`
    保证同一 run 内序号唯一；`append` 只插一条，不再重写历史事件。
  - **状态行**仍按整行 upsert 写 `workbench_runtime_states`（不含任何事件列），
    调用方（Mock 运行时）因此不需要为了持久化额外调整写路径——每次 `_emit` /
    `save_checkpoint` 都会把当前对象的全部有界字段落库。
  - 改造前事件挂在状态行的 `events` 列里，每写一个事件都要重写全量事件（写放大 O(n²)）；
    现在单次写入的代价与历史事件数**无关**。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from .contracts import AgentPlan, RuntimeContext, RuntimeEvent
from .serialization import STATE_COLUMNS, decode_event, decode_state, encode_event, encode_state
from .state import RuntimeState, track_appended_event

_JSONB_COLUMNS = frozenset(
    {"context", "plan", "completed_steps", "approvals", "usage", "checkpoint"}
)
_COLUMNS = ", ".join(STATE_COLUMNS)
_PLACEHOLDERS = ", ".join(
    f"%s::jsonb" if column in _JSONB_COLUMNS else "%s" for column in STATE_COLUMNS
)
_CONFLICT_ASSIGNMENTS = ", ".join(
    f"{column} = EXCLUDED.{column}" for column in STATE_COLUMNS if column != "run_id"
)
# 事件表列顺序：与 `decode_event` / `encode_event` 的字段一一对应（不含 occurred_at，写库用默认值 now()）。
_EVENT_COLUMNS = ("run_id", "tenant_id", "sequence", "event_type", "payload")
_EVENT_COLUMNS_SQL = ", ".join(_EVENT_COLUMNS)
_EVENT_INSERT = (
    f"INSERT INTO workbench_runtime_events ({_EVENT_COLUMNS_SQL}) "
    "VALUES (%s, %s, %s, %s, %s::jsonb)"
)
_STATE_UPSERT = f"""
    INSERT INTO workbench_runtime_states ({_COLUMNS})
    VALUES ({_PLACEHOLDERS})
    ON CONFLICT (run_id) DO UPDATE SET
        {_CONFLICT_ASSIGNMENTS},
        updated_at = now()
"""


class PostgresRuntimeStateStore:
    """运行时状态持久化；接口与内存实现逐一对应。"""

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
    def _params(state: RuntimeState, *, event_count: int | None = None) -> tuple[Any, ...]:
        encoded = encode_state(state)
        # 允许调用方覆盖本次写入的事件计数（`append` 在同一条语句里写「追加后」的值，
        # 而内存态要等写入成功才推进 ⇒ 两者保持一致，写失败不产生漂移）。
        if event_count is not None:
            encoded["event_count"] = event_count
        values: list[Any] = []
        for column in STATE_COLUMNS:
            value = encoded[column]
            if column in _JSONB_COLUMNS:
                values.append(None if value is None else json.dumps(value, ensure_ascii=False))
            else:
                values.append(value)
        return tuple(values)

    @staticmethod
    def _event_params(state: RuntimeState, event: RuntimeEvent) -> tuple[Any, ...]:
        # 与读路径共用同一套编码：**写入前**即完成 payload 脱敏（凭据类键不落库）。
        encoded = encode_event(event)
        return (
            encoded["run_id"],
            state.context.tenant_id,
            encoded["sequence"],
            encoded["event_type"],
            json.dumps(encoded["payload"], ensure_ascii=False),
        )

    def _upsert(self, state: RuntimeState) -> RuntimeState:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(_STATE_UPSERT + f" RETURNING {_COLUMNS}", self._params(state))
                    row = cursor.fetchone()
        if row is None:
            raise KeyError(state.run_id)
        return decode_state(dict(zip(STATE_COLUMNS, row)))

    def create(
        self, context: RuntimeContext, plan: AgentPlan, *, run_id: str | None = None
    ) -> RuntimeState:
        state = RuntimeState(run_id=run_id or f"run-{uuid4().hex[:12]}", context=context, plan=plan)
        return self._upsert(state)

    def get(self, run_id: str) -> RuntimeState:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_COLUMNS} FROM workbench_runtime_states WHERE run_id = %s", (run_id,)
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(run_id)
        return decode_state(dict(zip(STATE_COLUMNS, row)))

    def remove(self, run_id: str) -> None:
        """删除一个运行状态（⑥ 失败回滚用，§4.1.3：使该次请求**零残留**）。

        与内存实现（`RuntimeStateStore.remove`）语义对齐：`run_id` 是主键、全局唯一，
        故按它删除天然不会越到其他租户；**幂等**，删不存在的行无副作用（DELETE 命中 0 行）。
        事件独立成表后，同一事务内**连同该 run 的事件一起删除**——否则回滚会留下孤儿事件，
        与「零残留」相矛盾。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_runtime_events WHERE run_id = %s", (run_id,)
                    )
                    cursor.execute(
                        "DELETE FROM workbench_runtime_states WHERE run_id = %s", (run_id,)
                    )

    def list_for_tenant(self, tenant_id: str, *, statuses: Iterable[str] | None = None) -> list[RuntimeState]:
        statement = f"SELECT {_COLUMNS} FROM workbench_runtime_states WHERE tenant_id = %s"
        params: tuple[Any, ...] = (tenant_id,)
        selected = tuple(statuses) if statuses is not None else ()
        if selected:
            statement += " AND status = ANY(%s)"
            params = (tenant_id, list(selected))
        statement += " ORDER BY created_at DESC"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                rows = cursor.fetchall() or []
        return [decode_state(dict(zip(STATE_COLUMNS, row))) for row in rows]

    def append(self, state: RuntimeState, event: RuntimeEvent) -> None:
        """追加**一条**事件（append-only）+ 一次不含事件的状态行 upsert。

        一次事务内两条语句：先插事件行，再写状态行（带上「追加后」的事件计数与用量）。
        内存态（`event_count` / `usage`）在**写入成功后**才推进，写入失败不留漂移；
        为此先在状态副本上算一次增量，用副本构造本次写入的参数。
        """
        pending = replace(state, usage=dict(state.usage))
        track_appended_event(pending, event)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(_EVENT_INSERT, self._event_params(state, event))
                    cursor.execute(_STATE_UPSERT, self._params(pending))
        track_appended_event(state, event)

    def list_events(self, run_id: str, after_sequence: int | None = None) -> list[RuntimeEvent]:
        """按 `sequence` **升序**读取某个 run 的事件；`after_sequence` 用于断点续读。

        查询恒以 `run_id`（主键的一部分，全局唯一）为界；不提供跨 run / 跨租户的读取路径。
        """
        statement = f"SELECT {_EVENT_COLUMNS_SQL} FROM workbench_runtime_events WHERE run_id = %s"
        params: tuple[Any, ...] = (run_id,)
        if after_sequence is not None:
            statement += " AND sequence > %s"
            params = (run_id, after_sequence)
        statement += " ORDER BY sequence ASC"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                rows = cursor.fetchall() or []
        return [decode_event(dict(zip(_EVENT_COLUMNS, row))) for row in rows]

    def purge_events_before(self, cutoff: datetime) -> int:
        """删除 `occurred_at < cutoff` 的运行事件，返回删除行数（保留期清理入口）。

        只动 `workbench_runtime_events`：**审计不可删除**（`delivery-remaining-checklist` 10.1），
        本方法不触碰任何审计表。状态行与其 `event_count` 保持不动 ⇒ 计数不回退，
        后续事件的序号继续单调递增（不会复用已删序号）。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_runtime_events WHERE occurred_at < %s", (cutoff,)
                    )
                    removed = cursor.rowcount
        return int(removed)

    def save_checkpoint(self, state: RuntimeState) -> dict[str, object]:
        state.checkpoint = {
            "status": state.status,
            "completed_steps": list(state.completed_steps),
            "next_step": len(state.completed_steps),
        }
        self._upsert(state)
        return dict(state.checkpoint)
