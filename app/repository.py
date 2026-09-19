from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from typing import Protocol

from .domain import AuditEvent, IdempotencyConflict, RiskLevel, Task, TaskNotFound, TaskStateConflict, TaskStatus, UserContext


class TaskRepository(Protocol):
    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]: ...
    def get(self, context: UserContext, task_id: str) -> Task: ...
    def approve(self, context: UserContext, task_id: str) -> Task: ...
    def list_pending_approval(self, tenant_id: str, *, limit: int) -> list[Task]: ...
    def list_for_tenant(self, tenant_id: str, *, limit: int, offset: int) -> tuple[list[Task], int]: ...
    def count_by_employee(self, tenant_id: str) -> dict[str, int]: ...
    def set_pending_approval(self, context: UserContext, task_id: str) -> Task: ...
    def delete(self, tenant_id: str, task_id: str) -> None: ...


# 任务表的列清单（**唯一定义**）：`_row_to_task` 按下标水合，六处 SELECT/RETURNING 共用本常量，
# 避免「加一列要改六处、漏一处就下标错位」。`budget_cents` 追加在**末尾**（组 10.5，迁移 044）：
# 既有下标（0..10）不变，新列读 `row[11]`。
_TASK_COLUMNS = (
    "id, tenant_id, project_id, created_by, employee_key, title, "
    "risk_level, budget, idempotency_key, request_fingerprint, status, budget_cents"
)


class PostgresTaskRepository:
    """PostgreSQL adapter using a per-operation connection or pool lease."""

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

    def approve(self, context: UserContext, task_id: str) -> Task:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_tasks
                        SET status = 'queued', updated_at = now()
                        WHERE id = %s AND tenant_id = %s AND status = 'pending_approval'
                        RETURNING id
                        """,
                        (task_id, context.tenant_id),
                    )
                    if cursor.fetchone() is None:
                        cursor.execute(
                            "SELECT id FROM workbench_tasks WHERE id = %s AND tenant_id = %s",
                            (task_id, context.tenant_id),
                        )
                        if cursor.fetchone() is None:
                            raise TaskNotFound(task_id)
                        raise TaskStateConflict("任务当前不需要审批")
                    cursor.execute(
                        """
                        INSERT INTO workbench_audit_events (task_id, tenant_id, action, actor_id, actor_role)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (task_id, context.tenant_id, "task.approved", context.user_id, context.role),
                    )
                    self._enqueue_event(cursor, task_id, context.tenant_id, "task.approved", context.user_id, TaskStatus.QUEUED, 2)
        return self.get(context, task_id)

    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]:
        if task.tenant_id != context.tenant_id:
            raise TaskNotFound(task.id)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_tasks
                            (id, tenant_id, project_id, created_by, employee_key, title,
                             risk_level, budget, idempotency_key, request_fingerprint, status,
                             budget_cents)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, created_by, idempotency_key) DO NOTHING
                        RETURNING {_TASK_COLUMNS}
                        """,
                        (task.id, task.tenant_id, task.project_id, task.created_by, task.employee_key,
                         task.title, task.risk_level.value, task.budget, task.idempotency_key,
                         task.request_fingerprint, task.status.value, task.budget_cents),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            f"""
                            SELECT {_TASK_COLUMNS}
                            FROM workbench_tasks
                            WHERE tenant_id = %s AND created_by = %s AND idempotency_key = %s
                            """,
                            (context.tenant_id, context.user_id, task.idempotency_key),
                        )
                        row = cursor.fetchone()
                        if row is None:
                            raise TaskNotFound(task.id)
                        existing = self._row_to_task(row)
                        if existing.request_fingerprint != task.request_fingerprint:
                            raise IdempotencyConflict("相同幂等键对应的任务内容不一致")
                        return existing, False
                    cursor.execute(
                        """
                        INSERT INTO workbench_audit_events (task_id, tenant_id, action, actor_id, actor_role)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (task.id, context.tenant_id, "task.created", context.user_id, context.role),
                    )
                    self._enqueue_event(cursor, task.id, context.tenant_id, "task.created", context.user_id, task.status, 1)
                    created = self._row_to_task(row)
                    created.audits.append(AuditEvent(action="task.created", actor_id=context.user_id, actor_role=context.role))
                    return created, True

    def get(self, context: UserContext, task_id: str) -> Task:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {_TASK_COLUMNS}
                        FROM workbench_tasks
                        WHERE id = %s AND tenant_id = %s
                          AND (%s IN ('department_lead', 'ceo', 'super_admin') OR created_by = %s)
                        """,
                        (task_id, context.tenant_id, context.role, context.user_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise TaskNotFound(task_id)
                    task = self._row_to_task(row)
                    cursor.execute(
                        """
                        SELECT action, actor_id, actor_role, occurred_at
                        FROM workbench_audit_events
                        WHERE task_id = %s AND tenant_id = %s
                        ORDER BY id
                        """,
                        (task_id, context.tenant_id),
                    )
                    task.audits = [AuditEvent(action=a[0], actor_id=a[1], actor_role=a[2], at=a[3]) for a in cursor.fetchall()]
                    return task

    def list_pending_approval(self, tenant_id: str, *, limit: int) -> list[Task]:
        """列出待审批任务；任务无业务时间字段，按 id 升序保证分页确定性。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_TASK_COLUMNS}
                    FROM workbench_tasks
                    WHERE tenant_id = %s AND status = 'pending_approval'
                    ORDER BY id
                    LIMIT %s
                    """,
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    def set_pending_approval(self, context: UserContext, task_id: str) -> Task:
        """把承载任务由 `queued` 置为 `pending_approval`（段二规格 §3.7 Y2；不新增审计动作码）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_tasks
                        SET status = 'pending_approval', updated_at = now()
                        WHERE id = %s AND tenant_id = %s AND status = 'queued'
                        """,
                        (task_id, context.tenant_id),
                    )
        return self.get(context, task_id)

    def delete(self, tenant_id: str, task_id: str) -> None:
        """删除承载任务及其创建痕迹（⑥ 失败回滚用，§4.1.3）：任务行 + 审计行 + 出箱行一并清除，
        使请求结束后**零残留**（与 InMemory 分支一致）。仅删除本租户匹配的记录，幂等。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM workbench_event_outbox
                        WHERE tenant_id = %s AND aggregate_type = 'task' AND aggregate_id = %s
                        """,
                        (tenant_id, task_id),
                    )
                    cursor.execute(
                        "DELETE FROM workbench_audit_events WHERE tenant_id = %s AND task_id = %s",
                        (tenant_id, task_id),
                    )
                    cursor.execute(
                        "DELETE FROM workbench_tasks WHERE id = %s AND tenant_id = %s",
                        (task_id, tenant_id),
                    )

    def count_by_employee(self, tenant_id: str) -> dict[str, int]:
        """按数字员工标识统计本租户任务数（只读聚合，用于岗位/员工清单页）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT employee_key, COUNT(*)
                    FROM workbench_tasks
                    WHERE tenant_id = %s
                    GROUP BY employee_key
                    """,
                    (tenant_id,),
                )
                rows = cursor.fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def list_for_tenant(self, tenant_id: str, *, limit: int, offset: int) -> tuple[list[Task], int]:
        """按租户列出任务元数据（B-2b 导出读取通道）。

        任务没有业务时间字段 ⇒ `ORDER BY id`（顺序确定，与内存实现同口径）；
        `COUNT(*)` 是与 `LIMIT/OFFSET` **同条件**的过滤后总数（不拿返回条数冒充总数）。
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_TASK_COLUMNS}
                    FROM workbench_tasks
                    WHERE tenant_id = %s
                    ORDER BY id
                    LIMIT %s OFFSET %s
                    """,
                    (tenant_id, limit, offset),
                )
                rows = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) FROM workbench_tasks WHERE tenant_id = %s", (tenant_id,))
                total = cursor.fetchone()
        return [self._row_to_task(row) for row in rows], int(total[0]) if total is not None else 0

    @staticmethod
    def _row_to_task(row: tuple) -> Task:
        # `budget` 与 `budget_cents` **恰好一列有值**（迁移 044 的互斥约束）：历史行只有前者、新行只有后者。
        # 两列都按「可空」水合，`Task.budget_in_cents()` 负责归一（历史行用 Decimal 换算，不直接乘 100）。
        return Task(
            id=str(row[0]), tenant_id=str(row[1]), project_id=row[2], created_by=str(row[3]),
            employee_key=str(row[4]), title=str(row[5]), risk_level=RiskLevel(str(row[6])),
            budget=float(row[7]) if row[7] is not None else None,
            idempotency_key=str(row[8]), request_fingerprint=str(row[9]),
            status=TaskStatus(str(row[10])), audits=[],
            budget_cents=int(row[11]) if len(row) > 11 and row[11] is not None else None,
        )

    @staticmethod
    def _enqueue_event(cursor, task_id: str, tenant_id: str, action: str, actor_id: str, status: TaskStatus, sequence: int) -> None:
        cursor.execute(
            """
            INSERT INTO workbench_event_outbox
                (event_id, tenant_id, aggregate_type, aggregate_id, version, sequence,
                 dedupe_key, action, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (
                f"{task_id}:{action}:1",
                tenant_id,
                "task",
                task_id,
                1,
                sequence,
                f"{task_id}:{action}:1",
                action,
                json.dumps({"status": status.value, "actor_id": actor_id}, ensure_ascii=False),
            ),
        )
