from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from threading import RLock
from uuid import uuid4


class RiskLevel(StrEnum):
    """任务与动作的风险刻度。**声明顺序即由低到高**，`RISK_ORDER` 据此生成。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 风险的序：由 `RiskLevel` 的声明顺序生成，全系统**唯一一份**。
# 上层模块（如 `workforce`）一律从这里导入，不得另写第二份序——两份序必然漂移。
RISK_ORDER: dict[str, int] = {level.value: index for index, level in enumerate(RiskLevel)}


def risk_at_least(risk_level: RiskLevel, floor: RiskLevel) -> bool:
    """风险是否**不低于** `floor`。

    安全闸门一律用它，**禁止**写成 `risk_level == RiskLevel.X`：等值判断在新增更高
    风险档时会变成 fail-open（更高档反而绕过闸门，`critical` 就是这样一个档）。
    """
    return RISK_ORDER[risk_level.value] >= RISK_ORDER[floor.value]


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PENDING_APPROVAL = "pending_approval"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class UserContext:
    tenant_id: str
    user_id: str
    role: str
    scope: str = "full"
    # 令牌会话的标识与过期时间；由 app.auth 在验签后填入，用于服务端撤销判定。
    # 头部身份（开发期 X-* 头）没有令牌，因此保持为空。
    token_id: str = ""
    expires_at: datetime | None = None


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
    budget: float | None
    idempotency_key: str
    request_fingerprint: str
    status: TaskStatus
    id: str = field(default_factory=lambda: f"task-{uuid4().hex[:12]}")
    audits: list[AuditEvent] = field(default_factory=list)
    # 组 10.5（迁移 044，用户裁决 2026-09-19 选项 A）：**权威金额 = 整数分**。
    # `budget`（元 / 浮点）保留为兼容列：历史行只有它，新行只有 `budget_cents`，两者**恰好一个有值**。
    budget_cents: int | None = None

    def budget_in_cents(self) -> int:
        """任务金额（整数分）：新行为 `budget_cents`；历史行（只有 `budget`）按「元 → 分」换算。

        换算用 `Decimal`（宪法 §3 金额红线）：`float` 直接乘 100 会有尾差（如 0.29 * 100 = 28.999…），
        `Decimal(str(value))` 走「十进制定点 → 四舍五入到分」路径，结果与迁移 044 的回填逐分一致。
        """
        if self.budget_cents is not None:
            return int(self.budget_cents)
        if self.budget is None:
            return 0
        return yuan_to_cents(self.budget)


def yuan_to_cents(value: float | int | str) -> int:
    """元 → 整数分（四舍五入到分，拒绝 NaN / 无穷）。**金额一律经此换算，不直接乘 100**。"""
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise PolicyError("预算不是有效金额")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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

    def count_by_employee(self, tenant_id: str) -> dict[str, int]:
        """按数字员工标识统计本租户任务数（只读聚合，用于岗位/员工清单页）。"""
        with self._lock:
            counts: dict[str, int] = {}
            for task in self._tasks.values():
                if task.tenant_id != tenant_id:
                    continue
                counts[task.employee_key] = counts.get(task.employee_key, 0) + 1
        return counts

    def list_for_tenant(self, tenant_id: str, *, limit: int, offset: int) -> tuple[list[Task], int]:
        """按租户列出任务元数据（B-2b 导出读取通道）。

        任务没有业务时间字段 ⇒ 排序按 `id`（与 PG 实现的 `ORDER BY id` 同口径，顺序确定）；
        返回 `(本页, 过滤后总数)`，越界分页返回空页。**只读**：不改状态、不触发通知。
        """
        with self._lock:
            rows = sorted(
                (task for task in self._tasks.values() if task.tenant_id == tenant_id),
                key=lambda task: task.id,
            )
        return rows[offset : offset + limit], len(rows)

    def set_pending_approval(self, context: UserContext, task_id: str) -> Task:
        """把承载任务由 `queued` 置为 `pending_approval`（段二规格 §3.7 Y2）。

        规格定死：建时 `queued`，**`pending_approval` 仅在 ⑥ 落库成功后置位**（`001_initial.sql`
        的 CHECK 仅允许 `queued`/`pending_approval`/`cancelled`）。不新增审计动作码；仅当当前为
        `queued` 时置位（幂等，重复调用无副作用）。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.tenant_id != context.tenant_id:
                raise TaskNotFound(task_id)
            if task.status is TaskStatus.QUEUED:
                task.status = TaskStatus.PENDING_APPROVAL
            return task

    def delete(self, tenant_id: str, task_id: str) -> None:
        """删除承载任务（⑥ 失败回滚用，§4.1.3）：连同其幂等键索引一并清除，保证**零残留**。

        仅删除本租户匹配的任务；不存在或跨租户一律不动（回滚不得误删他人数据）。新增方法，
        不改变 `create` / `get` / `approve` 等既有语义。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.tenant_id != tenant_id:
                return
            del self._tasks[task_id]
            key = (task.tenant_id, task.created_by, task.idempotency_key)
            if self._idempotency.get(key) == task_id:
                del self._idempotency[key]

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

    def list_pending_approval(self, tenant_id: str, *, limit: int) -> list[Task]:
        """列出待审批任务。

        Task 数据类没有 created_at，这里按 task.id 升序保证结果确定性。
        """
        with self._lock:
            items = [
                task
                for task in self._tasks.values()
                if task.tenant_id == tenant_id and task.status is TaskStatus.PENDING_APPROVAL
            ]
        items.sort(key=lambda task: task.id)
        return items[:limit]


def ensure_can_create(context: UserContext, risk_level: RiskLevel, budget_cents: int) -> None:
    """创建任务闸门。**金额参数一律是整数分**（组 10.5，迁移 044）：调用方不得再传「元」浮点。

    阈值口径与 10.5 之前**逐字等价**：原判据是「元 > 1000」⇒ 现在「分 > 100000」。
    """
    if context.role not in {"employee", "department_lead", "ceo", "super_admin"}:
        raise PolicyError("当前岗位不能创建任务")
    if budget_cents < 0:
        raise PolicyError("预算不能小于 0")
    # `critical` 是最高风险档：仅负责人可发起（段一规格 X3）；创建后仍一律走人工审批。
    if risk_level is RiskLevel.CRITICAL and context.role not in {"ceo", "super_admin"}:
        raise PolicyError("critical 风险任务只能由 CEO 或超级管理员发起")
    # 「不低于 high」而不是「等于 high」：否则 critical 反而绕过这条预算闸门（fail-open）。
    if risk_at_least(risk_level, RiskLevel.HIGH) and context.role == "employee" and budget_cents > 100_000:
        raise PolicyError("普通员工的高风险任务预算不能超过 1000")


def ensure_can_approve(context: UserContext) -> None:
    if context.role not in {"ceo", "super_admin"}:
        raise PolicyError("只有 CEO 或超级管理员可以审批高风险任务")
