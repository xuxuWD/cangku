from __future__ import annotations

from typing import Protocol

from .domain import Task, TaskNotFound, TaskStateConflict, UserContext


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
        raise NotImplementedError("PostgreSQL 任务读取映射将在迁移接入阶段完成")

    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]:
        raise NotImplementedError("PostgreSQL 创建映射将在迁移接入阶段完成")

    def get(self, context: UserContext, task_id: str) -> Task:
        raise NotImplementedError("PostgreSQL 查询映射将在迁移接入阶段完成")
