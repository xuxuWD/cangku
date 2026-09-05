from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import uuid4


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PENDING_APPROVAL = "pending_approval"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class UserContext:
    tenant_id: str
    user_id: str
    role: str


@dataclass
class AuditEvent:
    action: str
    actor_id: str
    actor_role: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Task:
    tenant_id: str
    project_id: str | None
    created_by: str
    employee_key: str
    title: str
    risk_level: RiskLevel
    budget: float
    idempotency_key: str
    request_fingerprint: str
    status: TaskStatus
    id: str = field(default_factory=lambda: f"task-{uuid4().hex[:12]}")
    audits: list[AuditEvent] = field(default_factory=list)


class PolicyError(ValueError):
    """动作不满足统一权限策略。"""


class TaskNotFound(LookupError):
    pass


class IdempotencyConflict(ValueError):
    pass


class TaskStateConflict(ValueError):
    pass


class TaskStore:
    """开发期内存仓储；接口保持稳定，生产环境替换为数据库实现。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def create(self, context: UserContext, task: Task) -> tuple[Task, bool]:
        key = (context.tenant_id, context.user_id, task.idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id:
                existing = self._tasks[existing_id]
                if existing.request_fingerprint != task.request_fingerprint:
                    raise IdempotencyConflict("相同幂等键对应的任务内容不一致")
                return existing, False
            self._tasks[task.id] = task
            self._idempotency[key] = task.id
            return task, True

    def get(self, context: UserContext, task_id: str) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            elevated = {"department_lead", "ceo", "super_admin"}
            can_view = context.role in elevated or (task is not None and task.created_by == context.user_id)
            if task is None or task.tenant_id != context.tenant_id or not can_view:
                raise TaskNotFound(task_id)
            return task

    def approve(self, context: UserContext, task_id: str) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.tenant_id != context.tenant_id:
                raise TaskNotFound(task_id)
            if task.status != TaskStatus.PENDING_APPROVAL:
                raise TaskStateConflict("任务当前不需要审批")
            task.status = TaskStatus.QUEUED
            task.audits.append(AuditEvent(action="task.approved", actor_id=context.user_id, actor_role=context.role))
            return task


def ensure_can_create(context: UserContext, risk_level: RiskLevel, budget: float) -> None:
    if context.role not in {"employee", "department_lead", "ceo", "super_admin"}:
        raise PolicyError("当前岗位不能创建任务")
    if budget < 0:
        raise PolicyError("预算不能小于 0")
    if risk_level == RiskLevel.HIGH and context.role == "employee" and budget > 1000:
        raise PolicyError("普通员工的高风险任务预算不能超过 1000")


def ensure_can_approve(context: UserContext) -> None:
    if context.role not in {"ceo", "super_admin"}:
        raise PolicyError("只有 CEO 或超级管理员可以审批高风险任务")
