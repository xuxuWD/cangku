from __future__ import annotations

from typing import Protocol

from .domain import IdempotencyConflict, RiskLevel, Task, TaskNotFound, TaskStateConflict, TaskStatus, UserContext


class TaskRepository(Protocol):
    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]: ...

    def get(self, context: UserContext, task_id: str) -> Task: ...

    def approve(self, context: UserContext, task_id: str) -> Task: ...


class PostgresTaskRepository:
    """PostgreSQL adapter contract; migrations define the transactional constraints.

    The adapter is intentionally kept behind the same repository protocol as the
    development store. Production wiring is enabled after connection pooling and
    migration startup checks are added.
    """

    def __init__(self, connection) -> None:
        self.connection = connection

    def approve(self, context: UserContext, task_id: str) -> Task:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
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
                    raise TaskStateConflict("任务不存在、已审批或不属于当前企业")
        return self.get(context, task_id)

    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]:
        if task.tenant_id != context.tenant_id:
            raise TaskNotFound(task.id)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workbench_tasks
                        (id, tenant_id, project_id, created_by, employee_key, title,
                         risk_level, budget, idempotency_key, request_fingerprint, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, created_by, idempotency_key) DO NOTHING
                    RETURNING id, tenant_id, project_id, created_by, employee_key, title,
                              risk_level, budget, idempotency_key, request_fingerprint, status
                    """,
                    (
                        task.id,
                        task.tenant_id,
                        task.project_id,
                        task.created_by,
                        task.employee_key,
                        task.title,
                        task.risk_level.value,
                        task.budget,
                        task.idempotency_key,
                        task.request_fingerprint,
                        task.status.value,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT id, tenant_id, project_id, created_by, employee_key, title,
                               risk_level, budget, idempotency_key, request_fingerprint, status
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
                return self._row_to_task(row), True

    def get(self, context: UserContext, task_id: str) -> Task:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tenant_id, project_id, created_by, employee_key, title,
                       risk_level, budget, idempotency_key, request_fingerprint, status
                FROM workbench_tasks
                WHERE id = %s AND tenant_id = %s
                  AND (%s IN ('department_lead', 'ceo', 'super_admin') OR created_by = %s)
                """,
                (task_id, context.tenant_id, context.role, context.user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise TaskNotFound(task_id)
            return self._row_to_task(row)

    @staticmethod
    def _row_to_task(row: tuple) -> Task:
        return Task(
            id=str(row[0]),
            tenant_id=str(row[1]),
            project_id=row[2],
            created_by=str(row[3]),
            employee_key=str(row[4]),
            title=str(row[5]),
            risk_level=RiskLevel(str(row[6])),
            budget=float(row[7]),
            idempotency_key=str(row[8]),
            request_fingerprint=str(row[9]),
            status=TaskStatus(str(row[10])),
            audits=[],
        )
