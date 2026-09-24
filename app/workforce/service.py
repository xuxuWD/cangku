"""岗位与数字员工目录的服务层：写审计 + 计算「未纳管」候选集。

「未纳管」= 知识范围绑定与任务记录里出现过、但目录里还没有的标识。
这里刻意**实时求差集**而不是落库登记，避免出现第二份「谁算存在」的真相。
"""

from __future__ import annotations

from ..audit.models import AuditAction
from ..domain import RISK_ORDER, PolicyError, RiskLevel, UserContext
from .models import (
    DigitalEmployee,
    DigitalEmployeeShare,
    DirectoryNotManaged,
    DirectoryStatus,
    JobRole,
    needs_approval,
    normalize_key,
)
from .store import WorkforceDirectoryStore, _safe_key


class WorkforceDirectoryService:
    def __init__(
        self,
        store: WorkforceDirectoryStore,
        *,
        audit=None,
        knowledge_registry=None,
        task_store=None,
    ) -> None:
        self.store = store
        self.audit = audit
        self.knowledge_registry = knowledge_registry
        self.task_store = task_store

    # ------------------------------------------------------------ 岗位

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole:
        role = self.store.create_role(context, role_key=role_key, name=name, description=description)
        self._record(
            context,
            AuditAction.WORKFORCE_ROLE_CREATED,
            "job_role",
            role.role_key,
            {"role_key": role.role_key, "status": role.status.value, "changed_fields": ["role_key", "name"]},
        )
        return role

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole:
        role = self.store.update_role(context, role_key, name=name, description=description, status=status)
        action = (
            AuditAction.WORKFORCE_ROLE_DISABLED
            if _is_disabling(status)
            else AuditAction.WORKFORCE_ROLE_UPDATED
        )
        self._record(
            context,
            action,
            "job_role",
            role.role_key,
            {
                "role_key": role.role_key,
                "status": role.status.value,
                "changed_fields": _changed_fields(name=name, description=description, status=status),
            },
        )
        return role

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]:
        return self.store.list_roles(context, status=status, limit=limit, offset=offset)

    # ------------------------------------------------------------ 数字员工

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "", owner_user_id: str | None = None) -> DigitalEmployee:
        """创建数字员工。**归属人由仓储层决定**：非管理员恒为自己（请求体指定的一律忽略），
        `super_admin` 可指定（缺省仍为调用者本人）—— 见 `store._resolve_owner`。
        """
        employee = self.store.create_employee(
            context,
            agent_key=agent_key,
            name=name,
            role_key=role_key,
            description=description,
            owner_user_id=owner_user_id,
        )
        self._record(
            context,
            AuditAction.WORKFORCE_AGENT_CREATED,
            "digital_employee",
            employee.agent_key,
            {
                "agent_key": employee.agent_key,
                "role_key": employee.role_key,
                "status": employee.status.value,
                "changed_fields": ["agent_key", "name", "role_key"],
            },
        )
        return employee

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee:
        employee = self.store.update_employee(context, agent_key, name=name, description=description, role_key=role_key, status=status)
        action = (
            AuditAction.WORKFORCE_AGENT_DISABLED
            if _is_disabling(status)
            else AuditAction.WORKFORCE_AGENT_UPDATED
        )
        self._record(
            context,
            action,
            "digital_employee",
            employee.agent_key,
            {
                "agent_key": employee.agent_key,
                "role_key": employee.role_key,
                "status": employee.status.value,
                "changed_fields": _changed_fields(name=name, description=description, role_key=role_key, status=status),
            },
        )
        return employee

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]:
        return self.store.list_employees(context, status=status, role_key=role_key, limit=limit, offset=offset)

    def visible_agent_keys(self, context: UserContext) -> set[str] | None:
        """调用者可见的员工标识集合；`None` = 不受限（`super_admin`）。

        供 `GET /workforce/roster` 的任务计数子源复用**同一** `owner ∪ shares` 口径
        （2026-09-24 修复：该端点原先不过滤，把本租户全量员工标识+计数发给了任意登录身份）。
        """
        return self.store.visible_agent_keys(context)

    # ------------------------------------------------------------ 派活闸门（B2 · `use` 档的专有语义）

    def ensure_can_dispatch(self, context: UserContext, *, agent_key: str) -> None:
        """**派活**闸门：非 `super_admin` 只能用「归属自己 ∪ 被 `use` 共享」的**纳管**数字员工。

        2026-09-24 修复：此前任务落库路径（`_store_new_task`）**从不校验** `employee_key` 的归属/共享
        ⇒ `read` 档成员、乃至零共享的同事都能用他人的数字员工建任务（`use` = 能派活、
        `read` = 不能派活 在可执行路径上形同虚设）。

        ⚠️ **未纳管标识**（不在目录里）**不拦** —— 任务字段历史上是自由文本
        （`employee_key` 与目录 `agent_key` 同值不同名，见契约「岗位与数字员工目录」），
        它不属于任何人的员工，故沿用既有语义；只有「**他人的**纳管员工」才判 403。
        """
        if context.role == "super_admin":
            return
        owner = self.store.read_agent_owner(context, agent_key)
        if owner is None:
            return
        if context.user_id and owner == context.user_id:
            return
        if self.store.share_permission(context, agent_key, context.user_id) == "use":
            return
        raise PolicyError("没有使用该数字员工的权限（需归属人或 use 档共享）")

    # ------------------------------------------------------------ 共享管理（B2 · 迁移 045）

    def add_share(self, context: UserContext, agent_key: str, *, grantee_user_id: str, permission: str) -> DigitalEmployeeShare:
        """把**自己的**员工按档位共享给某人（**仅归属人**；他人 / 跨租户 404）。"""
        share = self.store.add_share(
            context, agent_key, grantee_user_id=grantee_user_id, permission=permission
        )
        self._record(
            context,
            AuditAction.WORKFORCE_AGENT_SHARE_ADDED,
            "digital_employee",
            share.agent_key,
            {
                "agent_key": share.agent_key,
                "grantee_user_id": share.grantee_user_id,
                "permission": share.permission,
            },
        )
        return share

    def list_shares(self, context: UserContext, agent_key: str, *, limit: int = 200, offset: int = 0) -> tuple[list[DigitalEmployeeShare], int]:
        return self.store.list_shares(context, agent_key, limit=limit, offset=offset)

    def remove_share(self, context: UserContext, agent_key: str, grantee_user_id: str) -> bool:
        """撤销共享；**幂等**：本就不是共享者返回 `False` ⇒ **不重复写审计**（契约 C4）。"""
        removed = self.store.remove_share(context, agent_key, grantee_user_id)
        if removed:
            self._record(
                context,
                AuditAction.WORKFORCE_AGENT_SHARE_REMOVED,
                "digital_employee",
                _safe_key(agent_key),
                {"agent_key": _safe_key(agent_key), "grantee_user_id": str(grantee_user_id).strip()},
            )
        return removed

    # ------------------------------------------------------------ 任务创建的治理判定

    def task_requires_approval(self, context: UserContext, *, agent_key: str, risk_level: RiskLevel) -> bool:
        """任务创建时是否必须人工审批（段一规格 §2.2 的**唯一消费点**）。

        * 有纳管且启用的数字员工 → 按其治理配置（自治等级 + 风险阈值）判定；
        * 否则回落**既有口径**：风险不低于 `high` 即需审批。该回落值与 023 的列默认值
          （`risk_threshold='high'` + `autonomy_level='approval_for_risky'`）完全一致，
          因此「无治理配置」与「按默认配置」结果相同，既不放宽也不收紧。

        判定逻辑只有 `needs_approval` 一处实现，这里只负责「取配置 + 回落」。
        """
        governance = self.store.read_agent_governance(context, agent_key)
        if governance is None:
            return RISK_ORDER[risk_level.value] >= RISK_ORDER[RiskLevel.HIGH.value]
        autonomy_level, risk_threshold = governance
        return needs_approval(autonomy_level, risk_level.value, risk_threshold)

    # ------------------------------------------------------------ 阶段 2 写路径闸门

    def ensure_role_binding_available(self, context: UserContext, role_key: str) -> str:
        """知识范围写路径闸门：岗位标识必须已在目录且启用；返回归一后的标识。

        只作用于**写**路径；读/检索解析不经过这里（历史自由文本绑定仍可用）。
        """
        if not self.store.role_is_active(context, role_key):
            raise DirectoryNotManaged("该标识尚未纳入目录，请先在「数字员工设置」中纳管")
        return normalize_key(role_key)

    def ensure_agent_binding_available(self, context: UserContext, agent_key: str) -> str:
        if not self.store.agent_is_active(context, agent_key):
            raise DirectoryNotManaged("该标识尚未纳入目录，请先在「数字员工设置」中纳管")
        return normalize_key(agent_key)

    # ------------------------------------------------------------ 未纳管候选

    def candidates(self, context: UserContext) -> dict[str, list[str]]:
        """返回尚未纳入目录的标识：`{"roles": [...], "agents": [...]}`。

        员工候选来自「知识范围的 agent 绑定」与「任务里出现过的 employee_key」的并集；
        岗位候选来自「知识范围的 role 绑定」。
        """
        role_keys, agent_keys = self.store.known_keys(context)
        bindings: dict[str, dict[str, list[str]]] = {"role": {}, "agent": {}}
        if self.knowledge_registry is not None:
            bindings = self.knowledge_registry.list_bindings(context)
        counts: dict[str, int] = {}
        if self.task_store is not None:
            counts = self.task_store.count_by_employee(context.tenant_id)
        unmanaged_roles = sorted(set(bindings["role"]) - role_keys)
        unmanaged_agents = sorted((set(bindings["agent"]) | set(counts)) - agent_keys)
        return {"roles": unmanaged_roles, "agents": unmanaged_agents}

    # ------------------------------------------------------------ 内部

    def _record(self, context: UserContext, action: AuditAction, target_type: str, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )


def _is_disabling(status: str | None) -> bool:
    return status is not None and str(status) == DirectoryStatus.DISABLED.value


def _changed_fields(**candidates: object) -> list[str]:
    """只记录确实提交了的字段名，避免审计里出现「改了但实际上没传」的假信息。"""
    return [name for name, value in candidates.items() if value is not None]
