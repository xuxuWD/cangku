from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from .authorization import ExecutionAuthorization


class RunRecordNotFound(LookupError):
    """运行记录不存在或不属于当前租户。"""


class FinishReason(StrEnum):
    """运行结束原因；由终态单向推导，非终态一律为空。

    只存受控枚举、不存自由文本——失败/取消的具体细节仍由运行事件接口暴露。
    """

    RUN_COMPLETED = "run_completed"
    CANCELLED_BY_USER = "cancelled_by_user"
    STEP_FAILED = "step_failed"
    APPROVAL_REJECTED = "approval_rejected"


@dataclass
class RunRecord:
    run_id: str
    tenant_id: str
    task_id: str
    runtime_key: str
    status: str
    started_at: datetime
    proposal_id: str | None = None
    step_count: int = 0
    completed_step_count: int = 0
    tool_calls: int = 0
    successful_tools: int = 0
    knowledge_hits: int = 0
    latency_ms: int = 0
    finished_at: datetime | None = None
    finish_reason: FinishReason | None = None
    # 执行授权位（段一规格 §2.3）。**不由 `upsert` 维护**：只有
    # `set_execution_authorization` 能改它，否则每次状态回写都会把授权抹掉。
    execution_authorization: ExecutionAuthorization | None = None


class RunRecordStore(Protocol):
    def upsert(self, record: RunRecord) -> RunRecord: ...
    def get(self, tenant_id: str, run_id: str) -> RunRecord: ...
    def list_for_task(self, tenant_id: str, task_id: str) -> list[RunRecord]: ...
    def list_recent(self, tenant_id: str, *, limit: int) -> list[RunRecord]: ...
    def set_execution_authorization(
        self, tenant_id: str, run_id: str, authorization: ExecutionAuthorization | None
    ) -> RunRecord: ...


class InMemoryRunRecordStore:
    """开发期内存运行记录仓储；同一 run_id 覆盖写，租户内隔离。"""

    def __init__(self) -> None:
        self._items: dict[str, RunRecord] = {}
        self._lock = RLock()

    def upsert(self, record: RunRecord) -> RunRecord:
        with self._lock:
            existing = self._items.get(record.run_id)
            # 授权位不归 upsert 管：状态回写必须保留既有授权（与 PG 的
            # `ON CONFLICT DO UPDATE` 刻意不更新这三列保持一致）。
            if existing is not None:
                record = replace(record, execution_authorization=existing.execution_authorization)
            self._items[record.run_id] = record
            return record

    def set_execution_authorization(
        self, tenant_id: str, run_id: str, authorization: ExecutionAuthorization | None
    ) -> RunRecord:
        with self._lock:
            item = self._items.get(run_id)
            if item is None or item.tenant_id != tenant_id:
                raise RunRecordNotFound(run_id)
            updated = replace(item, execution_authorization=authorization)
            self._items[run_id] = updated
            return updated

    def get(self, tenant_id: str, run_id: str) -> RunRecord:
        with self._lock:
            item = self._items.get(run_id)
            if item is None or item.tenant_id != tenant_id:
                raise RunRecordNotFound(run_id)
            return item

    def list_for_task(self, tenant_id: str, task_id: str) -> list[RunRecord]:
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.task_id == task_id
            ]

    def list_recent(self, tenant_id: str, *, limit: int) -> list[RunRecord]:
        with self._lock:
            items = [item for item in self._items.values() if item.tenant_id == tenant_id]
        items.sort(key=lambda item: item.started_at, reverse=True)
        return items[:limit]


class PostgresRunRecordStore:
    """运行记录持久化；run_id 冲突时覆盖更新。"""

    # 授权三列只在 INSERT 时随记录写入；`ON CONFLICT DO UPDATE` 刻意**不更新**它们
    # （授权位归 `set_execution_authorization` 独占，状态回写不得抹掉授权）。
    _COLUMNS = (
        "run_id, tenant_id, task_id, proposal_id, runtime_key, status, step_count, "
        "completed_step_count, tool_calls, successful_tools, knowledge_hits, latency_ms, "
        "started_at, finished_at, finish_reason, "
        "execution_authorized_at, execution_authorized_by, authorized_plan_digest"
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
    def _hydrate(row: tuple) -> RunRecord:
        return RunRecord(
            run_id=str(row[0]),
            tenant_id=str(row[1]),
            task_id=str(row[2]),
            proposal_id=row[3],
            runtime_key=str(row[4]),
            status=str(row[5]),
            step_count=int(row[6]),
            completed_step_count=int(row[7]),
            tool_calls=int(row[8]),
            successful_tools=int(row[9]),
            knowledge_hits=int(row[10]),
            latency_ms=int(row[11]),
            started_at=row[12],
            finished_at=row[13],
            finish_reason=FinishReason(row[14]) if row[14] else None,
            # 迁移 026 的 CHECK 保证三列同生同灭，因此只需看第一列。
            execution_authorization=(
                ExecutionAuthorization(
                    authorized_by=str(row[16]),
                    plan_digest=str(row[17]),
                    authorized_at=row[15],
                )
                if row[15] is not None
                else None
            ),
        )

    def upsert(self, record: RunRecord) -> RunRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_run_records ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id) DO UPDATE SET
                            tenant_id = EXCLUDED.tenant_id,
                            task_id = EXCLUDED.task_id,
                            proposal_id = EXCLUDED.proposal_id,
                            runtime_key = EXCLUDED.runtime_key,
                            status = EXCLUDED.status,
                            step_count = EXCLUDED.step_count,
                            completed_step_count = EXCLUDED.completed_step_count,
                            tool_calls = EXCLUDED.tool_calls,
                            successful_tools = EXCLUDED.successful_tools,
                            knowledge_hits = EXCLUDED.knowledge_hits,
                            latency_ms = EXCLUDED.latency_ms,
                            started_at = EXCLUDED.started_at,
                            finished_at = EXCLUDED.finished_at,
                            finish_reason = EXCLUDED.finish_reason
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            record.run_id,
                            record.tenant_id,
                            record.task_id,
                            record.proposal_id,
                            record.runtime_key,
                            record.status,
                            record.step_count,
                            record.completed_step_count,
                            record.tool_calls,
                            record.successful_tools,
                            record.knowledge_hits,
                            record.latency_ms,
                            record.started_at,
                            record.finished_at,
                            str(record.finish_reason) if record.finish_reason else None,
                            record.execution_authorization.authorized_at
                            if record.execution_authorization
                            else None,
                            record.execution_authorization.authorized_by
                            if record.execution_authorization
                            else None,
                            record.execution_authorization.plan_digest
                            if record.execution_authorization
                            else None,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RunRecordNotFound(record.run_id)
        return self._hydrate(row)

    def set_execution_authorization(
        self, tenant_id: str, run_id: str, authorization: ExecutionAuthorization | None
    ) -> RunRecord:
        """只改授权三列；`None` 即撤销。三列同时写，与迁移 026 的 CHECK 一致。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_run_records
                        SET execution_authorized_at = %s,
                            execution_authorized_by = %s,
                            authorized_plan_digest = %s
                        WHERE tenant_id = %s AND run_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            authorization.authorized_at if authorization else None,
                            authorization.authorized_by if authorization else None,
                            authorization.plan_digest if authorization else None,
                            tenant_id,
                            run_id,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RunRecordNotFound(run_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, run_id: str) -> RunRecord:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_run_records
                    WHERE tenant_id = %s AND run_id = %s
                    """,
                    (tenant_id, run_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise RunRecordNotFound(run_id)
        return self._hydrate(row)

    def list_for_task(self, tenant_id: str, task_id: str) -> list[RunRecord]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_run_records
                    WHERE tenant_id = %s AND task_id = %s ORDER BY started_at
                    """,
                    (tenant_id, task_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def list_recent(self, tenant_id: str, *, limit: int) -> list[RunRecord]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_run_records
                    WHERE tenant_id = %s ORDER BY started_at DESC LIMIT %s
                    """,
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]
