"""执行幂等仓储 `workbench_execution_idempotency`（迁移 027，规格 §4.1.3）。

对话入口以请求头 `Idempotency-Key` 为执行幂等键；本表记录「该键对应哪一次执行的哪个结果」，
只存指针、不存正文：首次响应由 `message_id` 反查 append-only 消息表重建。

写入即校验迁移 027 的 `result_check`（`outcome` 与 `http_status` 的合法组合），
与 `app/tool_execution/store.py` 的 `body_check` 校验同一思路：**不合法组合不入库**。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

OUTCOMES = ("executed", "pending_approval", "rejected", "failed")

# 迁移 027 的 `workbench_execution_idempotency_result_check` 逐值照抄（防止非法组合入库）。
_ALLOWED_STATUS_BY_OUTCOME: dict[str, frozenset[int]] = {
    "executed": frozenset({201}),
    "pending_approval": frozenset({202}),
    "rejected": frozenset({403, 404, 409, 422}),
    "failed": frozenset({502, 504}),
}


class ExecutionIdempotencyConflict(ValueError):
    """同一幂等键对应的结果冲突（不应发生；出现即拒绝覆盖首次结果）。"""


@dataclass(frozen=True)
class ExecutionIdempotencyRecord:
    """`workbench_execution_idempotency` 一行（字段与迁移 027 一一对应）。"""

    tenant_id: str
    actor_id: str
    conversation_id: str
    idempotency_key: str
    outcome: str
    http_status: int
    message_id: str | None = None
    run_id: str | None = None
    approval_id: str | None = None
    created_at: datetime | None = None


def _validate(record: ExecutionIdempotencyRecord) -> None:
    """照抄 `result_check`：`http_status` 必须是该 `outcome` 的合法结果码。"""
    allowed = _ALLOWED_STATUS_BY_OUTCOME.get(record.outcome)
    if allowed is None:
        raise ValueError(f"outcome 不在 4 值之内：{record.outcome}")
    if record.http_status not in allowed:
        raise ValueError(
            f"outcome={record.outcome} 与 http_status={record.http_status} 不是合法组合（迁移 027 result_check）"
        )


class ExecutionIdempotencyStore(Protocol):
    def get(
        self, tenant_id: str, actor_id: str, conversation_id: str, idempotency_key: str
    ) -> ExecutionIdempotencyRecord | None: ...

    def insert(self, record: ExecutionIdempotencyRecord) -> tuple[ExecutionIdempotencyRecord, bool]: ...

    def find_by_run(self, tenant_id: str, run_id: str) -> ExecutionIdempotencyRecord | None:
        """按运行号反查「该运行由哪次对话调用产生」（P2c-2：决议后推进需定位会话）。"""
        ...


class InMemoryExecutionIdempotencyStore:
    """开发 / 测试用内存实现；复合主键即去重机制（并发写收敛为首次行）。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str, str], ExecutionIdempotencyRecord] = {}
        self._lock = RLock()

    @staticmethod
    def _key(record: ExecutionIdempotencyRecord) -> tuple[str, str, str, str]:
        return (
            record.tenant_id,
            record.actor_id,
            record.conversation_id,
            record.idempotency_key,
        )

    def get(
        self, tenant_id: str, actor_id: str, conversation_id: str, idempotency_key: str
    ) -> ExecutionIdempotencyRecord | None:
        with self._lock:
            return self._items.get((tenant_id, actor_id, conversation_id, idempotency_key))

    def insert(self, record: ExecutionIdempotencyRecord) -> tuple[ExecutionIdempotencyRecord, bool]:
        _validate(record)
        key = self._key(record)
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                # `ON CONFLICT DO NOTHING`：冲突以库中已存在行为准（首次结果优先）。
                return existing, False
            self._items[key] = record
            return record, True

    def find_by_run(self, tenant_id: str, run_id: str) -> ExecutionIdempotencyRecord | None:
        """按运行号反查（多行命中时取**最早**创建的一行；仅在内存实现里做确定性排序）。"""
        with self._lock:
            candidates = [
                record
                for record in self._items.values()
                if record.tenant_id == tenant_id and record.run_id == run_id
            ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda record: (
                record.created_at is None,
                record.created_at,
                record.idempotency_key,
            ),
        )[0]


class PostgresExecutionIdempotencyStore:
    """`workbench_execution_idempotency` 持久化（迁移 027）。"""

    _COLUMNS = (
        "tenant_id, actor_id, conversation_id, idempotency_key, message_id, "
        "run_id, approval_id, outcome, http_status, created_at"
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

    @staticmethod
    def _hydrate(row: tuple) -> ExecutionIdempotencyRecord:
        return ExecutionIdempotencyRecord(
            tenant_id=str(row[0]),
            actor_id=str(row[1]),
            conversation_id=str(row[2]),
            idempotency_key=str(row[3]),
            message_id=None if row[4] is None else str(row[4]),
            run_id=None if row[5] is None else str(row[5]),
            approval_id=None if row[6] is None else str(row[6]),
            outcome=str(row[7]),
            http_status=int(row[8]),
            created_at=row[9],
        )

    def get(
        self, tenant_id: str, actor_id: str, conversation_id: str, idempotency_key: str
    ) -> ExecutionIdempotencyRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_execution_idempotency
                    WHERE tenant_id = %s AND actor_id = %s AND conversation_id = %s
                      AND idempotency_key = %s
                    """,
                    (tenant_id, actor_id, conversation_id, idempotency_key),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def insert(self, record: ExecutionIdempotencyRecord) -> tuple[ExecutionIdempotencyRecord, bool]:
        _validate(record)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_execution_idempotency ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
                        ON CONFLICT (tenant_id, actor_id, conversation_id, idempotency_key)
                        DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            record.tenant_id,
                            record.actor_id,
                            record.conversation_id,
                            record.idempotency_key,
                            record.message_id,
                            record.run_id,
                            record.approval_id,
                            record.outcome,
                            record.http_status,
                            record.created_at,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return self._hydrate(row), True
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_execution_idempotency
                        WHERE tenant_id = %s AND actor_id = %s AND conversation_id = %s
                          AND idempotency_key = %s
                        """,
                        (
                            record.tenant_id,
                            record.actor_id,
                            record.conversation_id,
                            record.idempotency_key,
                        ),
                    )
                    existing = cursor.fetchone()
        if existing is None:
            raise ExecutionIdempotencyConflict("幂等行写入冲突但读不到既有行")
        return self._hydrate(existing), False

    def find_by_run(self, tenant_id: str, run_id: str) -> ExecutionIdempotencyRecord | None:
        """按运行号反查（走迁移 027 既有索引 `idx_workbench_execution_idempotency_run`）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_execution_idempotency
                    WHERE tenant_id = %s AND run_id = %s
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (tenant_id, run_id),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None


def record_to_dict(record: ExecutionIdempotencyRecord) -> dict[str, object]:
    """（便捷）序列化为可读字典，供日志 / 断言使用；不含任何正文。"""
    return {
        "tenant_id": record.tenant_id,
        "actor_id": record.actor_id,
        "conversation_id": record.conversation_id,
        "idempotency_key": record.idempotency_key,
        "outcome": record.outcome,
        "http_status": record.http_status,
        "message_id": record.message_id,
        "run_id": record.run_id,
        "approval_id": record.approval_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def dumps(record: ExecutionIdempotencyRecord) -> str:  # pragma: no cover - 便捷输出
    return json.dumps(record_to_dict(record), ensure_ascii=False, sort_keys=True)
