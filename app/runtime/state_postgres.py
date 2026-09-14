"""运行时状态的 PostgreSQL 仓储。

单独成模块是为了避开循环导入：`serialization` 需要 `RuntimeState`，
而本模块需要 `serialization`；若把本类放进 `state.py` 就会形成环。

写入策略是**整行 upsert**（`append` 与 `save_checkpoint` 都写整行），因此调用方
（Mock 运行时）不需要为了持久化额外调整写路径——每次 `_emit` / `save_checkpoint`
都会把当前对象的全部字段落库。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from typing import Any, Iterable
from uuid import uuid4

from .contracts import AgentPlan, RuntimeContext, RuntimeEvent
from .serialization import STATE_COLUMNS, decode_state, encode_state
from .state import RuntimeState

_JSONB_COLUMNS = frozenset(
    {"context", "plan", "events", "completed_steps", "approvals", "usage", "checkpoint"}
)
_COLUMNS = ", ".join(STATE_COLUMNS)
_PLACEHOLDERS = ", ".join(
    f"%s::jsonb" if column in _JSONB_COLUMNS else "%s" for column in STATE_COLUMNS
)
_CONFLICT_ASSIGNMENTS = ", ".join(
    f"{column} = EXCLUDED.{column}" for column in STATE_COLUMNS if column != "run_id"
)


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
    def _params(state: RuntimeState) -> tuple[Any, ...]:
        encoded = encode_state(state)
        values: list[Any] = []
        for column in STATE_COLUMNS:
            value = encoded[column]
            if column in _JSONB_COLUMNS:
                values.append(None if value is None else json.dumps(value, ensure_ascii=False))
            else:
                values.append(value)
        return tuple(values)

    def _upsert(self, state: RuntimeState) -> RuntimeState:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_runtime_states ({_COLUMNS})
                        VALUES ({_PLACEHOLDERS})
                        ON CONFLICT (run_id) DO UPDATE SET
                            {_CONFLICT_ASSIGNMENTS},
                            updated_at = now()
                        RETURNING {_COLUMNS}
                        """,
                        self._params(state),
                    )
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
        写法与同类仓储 `PostgresRunRecordStore.delete` 一致（事务包一条 DELETE）。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
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
        state.events.append(event)
        self._upsert(state)

    def save_checkpoint(self, state: RuntimeState) -> dict[str, object]:
        state.checkpoint = {
            "status": state.status,
            "completed_steps": list(state.completed_steps),
            "next_step": len(state.completed_steps),
        }
        self._upsert(state)
        return dict(state.checkpoint)
