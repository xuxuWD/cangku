"""岗位与数字员工目录仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制，避免调用方绕过接口层直接读写。闸门分三档（B1 §3.4 评审附条件）：
    * 读档 `_ensure_directory_reader`（**四档业务角色 + 登录**）—— `list_roles` / `list_employees` /
      `read_agent_config`（仅本人可见范围内）；
    * 创建档 `_ensure_employee_creator`（**四档业务角色 + 登录**，**归属人只能是自己**）—— `create_employee`；
    * 管理档 `_ensure_admin`（仅 `super_admin`）—— 建 / 改岗位、改 / 停用员工、改配置、
      以及跨模块只读方法（`known_keys` / `role_is_active` / `agent_is_active`，本批**不放宽**）。

⚠️ **过滤在仓储层做**（`list_employees` 按 owner ∪ shares 筛，`read_agent_config` 只放
归属人 ∪ `read` 档共享者），不在路由层 —— 路由层先取全量再筛 = 越权数据已经出库。
⚠️ `customer_admin` **不在**读档 / 创建档（`DIRECTORY_ACCESS_ROLES`）—— 见 `models.py` 注释。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from threading import RLock
from typing import Protocol

from ..domain import PolicyError, UserContext
from .models import (
    DIRECTORY_ACCESS_ROLES,
    SHARE_PERMISSIONS,
    DigitalEmployee,
    DigitalEmployeeShare,
    DirectoryConflict,
    DirectoryNotFound,
    DirectoryStatus,
    InvalidDirectoryKey,
    InvalidShare,
    JobRole,
    RoleNotAvailable,
    normalize_description,
    normalize_key,
    normalize_name,
    normalize_status,
    now,
)

MAX_LIMIT = 200

# 配置字段名（§7.2）；未提交（值为 None）的字段保持原值
CONFIG_FIELDS = (
    "system_prompt",
    "model_key",
    "temperature",
    "tool_allowlist",
    "memory_policy",
    "autonomy_level",
    "risk_threshold",
    "approval_timeout_minutes",
    "daily_budget_cents",
)


def _clean_config_changes(changes: dict[str, object]) -> dict[str, object]:
    """丢弃未提交字段并归一容器类型（服务层已完成取值校验）。"""
    clean = {name: value for name, value in changes.items() if value is not None}
    if "tool_allowlist" in clean:
        clean["tool_allowlist"] = tuple(str(item) for item in clean["tool_allowlist"])  # type: ignore[union-attr]
    if "memory_policy" in clean:
        clean["memory_policy"] = dict(clean["memory_policy"])  # type: ignore[arg-type]
    return clean


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    return tuple(str(item) for item in value)  # type: ignore[union-attr]


def _as_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value)  # type: ignore[arg-type]


def _safe_key(value: str) -> str:
    """把任意输入折算成目录键；非法或空一律返回空串（等价于「查不到」），不向上抛异常。"""
    try:
        return normalize_key(value)
    except InvalidDirectoryKey:
        return ""


class WorkforceDirectoryStore(Protocol):
    """目录读写。闸门分三档：读 / 创建（**四档业务角色 + 登录**）、管理（仅 `super_admin`）。

    可见性口径（两档，D-058③ 砍掉第三档）：`可见 = owner ∪ shares ∪ super_admin`；
    **过滤一律在仓储层**（不在路由层），否则「先取全量再筛」= 越权数据已出库。
    """

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole: ...

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole: ...

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]: ...

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "", owner_user_id: str | None = None) -> DigitalEmployee: ...

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee: ...

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]: ...

    def known_keys(self, context: UserContext) -> tuple[set[str], set[str]]: ...

    def role_is_active(self, context: UserContext, role_key: str) -> bool: ...

    def agent_is_active(self, context: UserContext, agent_key: str) -> bool: ...

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee: ...

    def read_agent_governance(self, context: UserContext, agent_key: str) -> tuple[str, str] | None: ...

    def update_agent_config(self, context: UserContext, agent_key: str, *, system_prompt: str | None = None, model_key: str | None = None, temperature: float | None = None, tool_allowlist: tuple[str, ...] | None = None, memory_policy: dict[str, object] | None = None, autonomy_level: str | None = None, risk_threshold: str | None = None, approval_timeout_minutes: int | None = None, daily_budget_cents: int | None = None) -> DigitalEmployee: ...

    def add_share(self, context: UserContext, agent_key: str, *, grantee_user_id: str, permission: str) -> DigitalEmployeeShare: ...

    def list_shares(self, context: UserContext, agent_key: str, *, limit: int = MAX_LIMIT, offset: int = 0) -> tuple[list[DigitalEmployeeShare], int]: ...

    def remove_share(self, context: UserContext, agent_key: str, grantee_user_id: str) -> bool: ...

    def visible_agent_keys(self, context: UserContext) -> set[str] | None:
        """调用者可见的员工标识集合；`None` = **不受限**（`super_admin` 管理视角）。

        ⚠️ 供 `GET /workforce/roster` 的**任务计数**子源复用同一 `owner ∪ shares` 口径 ——
        否则该端点会把本租户**全量**员工标识与任务数发给任意登录身份（越权数据出库）。
        """
        ...

    def read_agent_owner(self, context: UserContext, agent_key: str) -> str | None:
        """本租户内该员工的归属人；**未纳管 / 标识非法 ⇒ `None`**（跨租户同样按不存在处理）。"""
        ...

    def share_permission(self, context: UserContext, agent_key: str, user_id: str) -> str | None:
        """该用户对该员工的共享档位（`read` / `use`）；无共享 ⇒ `None`。"""
        ...


def _ensure_admin(context: UserContext) -> None:
    """管理档：建 / 改岗位、改 / 停用员工、改配置、跨模块只读方法（本批不放宽）。"""
    if context.role != "super_admin":
        raise PolicyError("只有超级管理员可以管理岗位与数字员工目录")


def _ensure_directory_reader(context: UserContext) -> None:
    """读档：**四档业务角色 + 登录**（`employee` / `department_lead` / `ceo` / `super_admin`）。

    ⚠️ 2026-09-24 修复：原实现只判 `user_id` 非空，把 `customer_admin` 一并放行 ——
    与施工材料 §2「四档角色」口径及 `permission-matrix.md` §3（数字员工四行 customer_admin 一律 ❌）冲突。
    现按角色白名单 **fail-closed**；「看得见哪些行」仍由 `owner ∪ shares` 在仓储层过滤。
    """
    if context.role not in DIRECTORY_ACCESS_ROLES:
        raise PolicyError("当前角色不能查看岗位与数字员工目录")
    if not context.user_id:
        raise PolicyError("请先登录后再查看岗位与数字员工目录")


def _ensure_employee_creator(context: UserContext) -> None:
    """创建档：**四档业务角色 + 登录**；归属人由服务端置为调用者本人（见 `_resolve_owner`）。

    ⚠️ 2026-09-24 修复：同读档，原实现漏判角色 ⇒ `customer_admin` 可创建数字员工。
    """
    if context.role not in DIRECTORY_ACCESS_ROLES:
        raise PolicyError("当前角色不能创建数字员工")
    if not context.user_id:
        raise PolicyError("请先登录后再创建数字员工")


def _resolve_owner(context: UserContext, requested: str | None) -> str:
    """归属人**只能由服务端决定**（一切输入默认不可信）。

    * 非管理员：恒为**调用者本人** —— 请求体指定的一律忽略（不可冒名）；
    * `super_admin`：可指定（供管理侧代建），缺省仍为调用者本人。
    """
    if context.role != "super_admin":
        _ensure_employee_creator(context)
        return context.user_id
    owner = str(requested).strip() if requested is not None else ""
    resolved = owner or context.user_id
    if not resolved:
        # 只有「上下文里没有身份」（如内存仓储被直接调用且 user_id 为空）才会走到这里；
        # 与迁移 045 的 `CHECK (owner_user_id <> '')` 同一口径：空串不是合法归属人。
        raise PolicyError("归属人不能为空")
    return resolved


def _ensure_config_reader(
    context: UserContext, employee: DigitalEmployee, share_permission: str | None
) -> None:
    """读配置：**归属人 ∪ `read` 档共享者 ∪ `super_admin`**。

    ⚠️ 2026-09-24 修复（真源对齐）：B1 §3.3② 表与契约 C4 逐字写「`read` = **能看配置**」，
    原实现只放归属人 ∪ 超管 ⇒ `read` 档读不到配置，与真源相反、且与 `use` 档行为完全等价。
    现按真源放开 `read` 档；`use` 档**仍不可读**（V4=A：与「不能改配置」对称，
    `config` 是「它怎么被配置的」，不是「它能不能被派活」）。
    """
    if context.role == "super_admin":
        return
    if context.user_id and employee.owner_user_id == context.user_id:
        return
    if share_permission == "read":
        return
    raise PolicyError("只有归属人、被共享（read 档）或超级管理员可以读取数字员工配置")


def _clean_share_permission(value: object) -> str:
    """档位**逐字匹配**（与路由层 `pattern="^(read|use)$"`、迁移 045 的 CHECK 同一口径）。

    刻意**不**做 `strip` / `lower` 归一：那会让「路由层 422、仓储层放行」出现双口径。
    """
    text = str(value)
    if text not in SHARE_PERMISSIONS:
        raise InvalidShare("共享档位只能是 read 或 use")
    return text


def _clean_grantee(value: object) -> str:
    text = str(value).strip()
    if not text:
        # 与迁移 045 的 `CHECK (grantee_user_id <> '')` 同口径：空串不是身份。
        raise InvalidShare("被授权人不能为空")
    return text


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


class InMemoryWorkforceDirectoryStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._roles: dict[tuple[str, str], JobRole] = {}
        self._employees: dict[tuple[str, str], DigitalEmployee] = {}
        # 共享层（迁移 045）：键 = (租户, 员工标识, 被授权人)
        self._shares: dict[tuple[str, str, str], DigitalEmployeeShare] = {}
        self._lock = RLock()

    # ------------------------------------------------------------ 可见性（owner ∪ shares）

    def visible_agent_keys(self, context: UserContext) -> set[str] | None:
        """调用者可见的员工标识集合；`None` = **不受限**（`super_admin` 的管理视角）。

        可见性口径（D-058③ 砍掉「同岗位」第三档，仓库无「用户 → 岗位」映射）：
        `可见 = owner_user_id = 我 ∪ workbench_employee_shares 里被授权的我`。
        """
        if context.role == "super_admin":
            return None
        with self._lock:
            owned = {
                key
                for (tenant_id, key), employee in self._employees.items()
                if tenant_id == context.tenant_id and employee.owner_user_id == context.user_id
            }
            shared = {
                key
                for (tenant_id, key, grantee) in self._shares
                if tenant_id == context.tenant_id and grantee == context.user_id
            }
        return owned | shared

    def read_agent_owner(self, context: UserContext, agent_key: str) -> str | None:
        key = _safe_key(agent_key)
        if not key:
            return None
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
        return employee.owner_user_id if employee is not None else None

    def share_permission(self, context: UserContext, agent_key: str, user_id: str) -> str | None:
        key = _safe_key(agent_key)
        if not key or not user_id:
            return None
        with self._lock:
            share = self._shares.get((context.tenant_id, key, user_id))
        return share.permission if share is not None else None

    def _owned_employee(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        """取**调用者自己所属的**员工；不存在 / 不是归属人一律 `DirectoryNotFound`（不泄露存在性）。

        ⚠️ 共享管理（增删查）**仅归属人**可做（契约 C4）；`super_admin` 亦不例外
        —— 管理员要处置员工走 `update_employee`（管理档），两条路径不混。
        """
        key = _safe_key(agent_key)
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
        if employee is None or not context.user_id or employee.owner_user_id != context.user_id:
            raise DirectoryNotFound(agent_key)
        return employee

    # ------------------------------------------------------------ 岗位

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole:
        _ensure_admin(context)
        key = normalize_key(role_key)
        clean_name = normalize_name(name)
        clean_description = normalize_description(description)
        with self._lock:
            if (context.tenant_id, key) in self._roles:
                raise DirectoryConflict("该岗位标识已存在")
            role = JobRole(
                tenant_id=context.tenant_id,
                role_key=key,
                name=clean_name,
                description=clean_description,
                created_by=context.user_id,
            )
            self._roles[(context.tenant_id, key)] = role
            return role

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole:
        _ensure_admin(context)
        key = normalize_key(role_key)
        with self._lock:
            existing = self._roles.get((context.tenant_id, key))
            if existing is None:
                raise DirectoryNotFound(role_key)
            updated = replace(
                existing,
                name=normalize_name(name) if name is not None else existing.name,
                description=normalize_description(description) if description is not None else existing.description,
                status=normalize_status(status) if status is not None else existing.status,
                updated_at=now(),
            )
            self._roles[(context.tenant_id, key)] = updated
            return updated

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]:
        _ensure_directory_reader(context)
        wanted = normalize_status(status) if status is not None else None
        # V1=C：非管理员**只看到启用岗位**（员工侧创建要能选岗位，但停用岗位不该可选）；
        # 管理页走 `super_admin`，不受影响（仍可按 status 过滤看全部）。
        if context.role != "super_admin":
            wanted = DirectoryStatus.ACTIVE
        with self._lock:
            matched = [
                role
                for (tenant_id, _key), role in sorted(self._roles.items())
                if tenant_id == context.tenant_id and (wanted is None or role.status == wanted)
            ]
        return matched[offset : offset + _clamp(limit)], len(matched)

    # ------------------------------------------------------------ 数字员工

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "", owner_user_id: str | None = None) -> DigitalEmployee:
        owner = _resolve_owner(context, owner_user_id)
        key = normalize_key(agent_key)
        target_role = normalize_key(role_key)
        clean_name = normalize_name(name)
        clean_description = normalize_description(description)
        with self._lock:
            self._require_active_role(context.tenant_id, target_role)
            if (context.tenant_id, key) in self._employees:
                raise DirectoryConflict("该数字员工标识已存在")
            employee = DigitalEmployee(
                tenant_id=context.tenant_id,
                agent_key=key,
                name=clean_name,
                role_key=target_role,
                description=clean_description,
                created_by=context.user_id,
                owner_user_id=owner,
            )
            self._employees[(context.tenant_id, key)] = employee
            return employee

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee:
        _ensure_admin(context)
        key = normalize_key(agent_key)
        target_role = normalize_key(role_key) if role_key is not None else None
        with self._lock:
            existing = self._employees.get((context.tenant_id, key))
            if existing is None:
                raise DirectoryNotFound(agent_key)
            if target_role is not None:
                self._require_active_role(context.tenant_id, target_role)
            updated = replace(
                existing,
                name=normalize_name(name) if name is not None else existing.name,
                description=normalize_description(description) if description is not None else existing.description,
                role_key=target_role or existing.role_key,
                status=normalize_status(status) if status is not None else existing.status,
                updated_at=now(),
            )
            self._employees[(context.tenant_id, key)] = updated
            return updated

    def read_agent_governance(self, context: UserContext, agent_key: str) -> tuple[str, str] | None:
        """只读治理两字段（自治等级、风险阈值），供任务创建等**非管理**路径使用。

        与 `read_agent_config` 的区别：这里**不做角色限制**（任务创建者可以是任意可创建
        任务的角色），但**只返回治理字段**，不暴露提示词 / 模型 / 工具白名单（最小必要）。
        标识按目录口径**归一后精确匹配**（小写化），与「大小写不同不是两个标识」一致；
        标识非法或员工不存在 / 已停用一律返回 `None`（= 无治理配置，由调用方回落既有口径），
        刻意不抛异常——`employee_key` 在创建任务时本来就是不校验的自由输入。

        **可用性口径 = `agent_is_active`（岗位停用连带）**：员工自身 `active` **且**所属岗位 `active`，
        缺一不可——岗位停用即连带其下属员工不可用（`agent_key` 应被拒）。故本方法对
        「岗位已停用」同样返回 `None`，与写路径闸门 `ensure_agent_binding_available` 同一口径，
        区别仅在于**不要求 `super_admin`**（执行入口的操作者可以是任意角色）。
        """
        key = _safe_key(agent_key)
        if not key:
            return None
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
            if employee is None or employee.status is not DirectoryStatus.ACTIVE:
                return None
            role = self._roles.get((context.tenant_id, employee.role_key))
        if role is None or role.status is not DirectoryStatus.ACTIVE:
            return None
        return (employee.autonomy_level, employee.risk_threshold)

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]:
        _ensure_directory_reader(context)
        wanted = normalize_status(status) if status is not None else None
        wanted_role = normalize_key(role_key) if role_key is not None else None
        visible = self.visible_agent_keys(context)
        with self._lock:
            matched = [
                employee
                for (tenant_id, key), employee in sorted(self._employees.items())
                if tenant_id == context.tenant_id
                and (visible is None or key in visible)
                and (wanted is None or employee.status == wanted)
                and (wanted_role is None or employee.role_key == wanted_role)
            ]
        return matched[offset : offset + _clamp(limit)], len(matched)

    # ------------------------------------------------------------ 共享层（迁移 045）

    def add_share(self, context: UserContext, agent_key: str, *, grantee_user_id: str, permission: str) -> DigitalEmployeeShare:
        """把**自己的**员工按档位共享给某人；**仅归属人**（他人 / 跨租户 404）。"""
        employee = self._owned_employee(context, agent_key)
        grantee = _clean_grantee(grantee_user_id)
        clean_permission = _clean_share_permission(permission)
        with self._lock:
            share = DigitalEmployeeShare(
                tenant_id=context.tenant_id,
                agent_key=employee.agent_key,
                grantee_user_id=grantee,
                permission=clean_permission,
                granted_by=context.user_id,
                granted_at=now(),
            )
            self._shares[(context.tenant_id, employee.agent_key, grantee)] = share
        return share

    def list_shares(self, context: UserContext, agent_key: str, *, limit: int = MAX_LIMIT, offset: int = 0) -> tuple[list[DigitalEmployeeShare], int]:
        employee = self._owned_employee(context, agent_key)
        with self._lock:
            matched = [
                share
                for (tenant_id, key, _grantee), share in sorted(self._shares.items())
                if tenant_id == context.tenant_id and key == employee.agent_key
            ]
        return matched[offset : offset + _clamp(limit)], len(matched)

    def remove_share(self, context: UserContext, agent_key: str, grantee_user_id: str) -> bool:
        """撤销共享；**幂等**：本就不是共享者返回 `False`（调用方据此不重复写审计）。"""
        employee = self._owned_employee(context, agent_key)
        grantee = str(grantee_user_id).strip()
        if not grantee:
            return False
        with self._lock:
            return self._shares.pop((context.tenant_id, employee.agent_key, grantee), None) is not None

    # ------------------------------------------------------------ 配置读写（读 = 归属人 ∪ read 档 ∪ 超管；写 = 仅超管）

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        key = normalize_key(agent_key)
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
        if employee is None:
            raise DirectoryNotFound(agent_key)
        _ensure_config_reader(context, employee, self.share_permission(context, employee.agent_key, context.user_id))
        return employee

    def update_agent_config(self, context: UserContext, agent_key: str, *, system_prompt: str | None = None, model_key: str | None = None, temperature: float | None = None, tool_allowlist: tuple[str, ...] | None = None, memory_policy: dict[str, object] | None = None, autonomy_level: str | None = None, risk_threshold: str | None = None, approval_timeout_minutes: int | None = None, daily_budget_cents: int | None = None) -> DigitalEmployee:
        _ensure_admin(context)
        key = normalize_key(agent_key)
        changes = _clean_config_changes(
            {
                "system_prompt": system_prompt,
                "model_key": model_key,
                "temperature": temperature,
                "tool_allowlist": tool_allowlist,
                "memory_policy": memory_policy,
                "autonomy_level": autonomy_level,
                "risk_threshold": risk_threshold,
                "approval_timeout_minutes": approval_timeout_minutes,
                "daily_budget_cents": daily_budget_cents,
            }
        )
        with self._lock:
            existing = self._employees.get((context.tenant_id, key))
            if existing is None:
                raise DirectoryNotFound(agent_key)
            updated = replace(existing, updated_at=now(), **changes)
            self._employees[(context.tenant_id, key)] = updated
            return updated

    # ------------------------------------------------------------ 供「未纳管」计算

    def known_keys(self, context: UserContext) -> tuple[set[str], set[str]]:
        """返回本租户已纳管的 (岗位标识, 数字员工标识)；含已停用项（纳管过就不算未纳管）。"""
        _ensure_admin(context)
        with self._lock:
            role_keys = {key for (tenant_id, key) in self._roles if tenant_id == context.tenant_id}
            agent_keys = {key for (tenant_id, key) in self._employees if tenant_id == context.tenant_id}
        return role_keys, agent_keys

    def _require_active_role(self, tenant_id: str, role_key: str) -> JobRole:
        role = self._roles.get((tenant_id, role_key))
        if role is None:
            raise RoleNotAvailable("岗位不存在或不属于本租户")
        if role.status != DirectoryStatus.ACTIVE:
            raise RoleNotAvailable("岗位已停用，不能再挂载数字员工")
        return role

    # ------------------------------------------------------------ 可用性判定（阶段 2 写路径闸门）

    def role_is_active(self, context: UserContext, role_key: str) -> bool:
        """标识是否已在目录且启用；非法或空标识按「不可用」处理（不抛异常）。"""
        _ensure_admin(context)
        key = _safe_key(role_key)
        with self._lock:
            role = self._roles.get((context.tenant_id, key))
        return role is not None and role.status == DirectoryStatus.ACTIVE

    def agent_is_active(self, context: UserContext, agent_key: str) -> bool:
        """员工可用 = 员工自身 active **且** 所属岗位 active（岗位停用连带约束其员工）。"""
        _ensure_admin(context)
        key = _safe_key(agent_key)
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
            if employee is None or employee.status != DirectoryStatus.ACTIVE:
                return False
            role = self._roles.get((context.tenant_id, employee.role_key))
        return role is not None and role.status == DirectoryStatus.ACTIVE


class PostgresWorkforceDirectoryStore:
    """目录持久化（表 `workbench_job_roles` / `workbench_digital_employees`，迁移 022）。"""

    _ROLE_COLUMNS = "tenant_id, role_key, name, description, status, created_by, created_at, updated_at"
    # 迁移 045 起追加 `owner_user_id` / `visibility`（**追加在末尾**，既有列的序号不变）。
    _EMPLOYEE_COLUMNS = (
        "tenant_id, agent_key, name, description, role_key, status, created_by, created_at, updated_at, "
        "owner_user_id, visibility"
    )
    # 配置读写在既有列之后追加 §7.2 字段；既有 CRUD/列表仍用 _EMPLOYEE_COLUMNS。
    _AGENT_CONFIG_COLUMNS = (
        f"{_EMPLOYEE_COLUMNS}, system_prompt, model_key, temperature, tool_allowlist, "
        "memory_policy, autonomy_level, risk_threshold, approval_timeout_minutes, daily_budget_cents"
    )
    _SHARE_COLUMNS = "tenant_id, agent_key, grantee_user_id, permission, granted_by, granted_at"

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
    def _hydrate_role(row: tuple) -> JobRole:
        return JobRole(
            tenant_id=str(row[0]),
            role_key=str(row[1]),
            name=str(row[2]),
            description=str(row[3]),
            status=DirectoryStatus(str(row[4])),
            created_by=str(row[5]),
            created_at=row[6],
            updated_at=row[7],
        )

    @staticmethod
    def _hydrate_employee(row: tuple) -> DigitalEmployee:
        return DigitalEmployee(
            tenant_id=str(row[0]),
            agent_key=str(row[1]),
            name=str(row[2]),
            description=str(row[3]),
            role_key=str(row[4]),
            status=DirectoryStatus(str(row[5])),
            created_by=str(row[6]),
            created_at=row[7],
            updated_at=row[8],
            owner_user_id=str(row[9] or ""),
            visibility=str(row[10] or "private"),
        )

    @staticmethod
    def _hydrate_agent_config(row: tuple) -> DigitalEmployee:
        return DigitalEmployee(
            tenant_id=str(row[0]),
            agent_key=str(row[1]),
            name=str(row[2]),
            description=str(row[3]),
            role_key=str(row[4]),
            status=DirectoryStatus(str(row[5])),
            created_by=str(row[6]),
            created_at=row[7],
            updated_at=row[8],
            owner_user_id=str(row[9] or ""),
            visibility=str(row[10] or "private"),
            system_prompt=str(row[11] or ""),
            model_key=str(row[12] or ""),
            temperature=float(row[13]) if row[13] is not None else 0.20,
            tool_allowlist=_as_str_tuple(row[14]),
            memory_policy=_as_dict(row[15]),
            autonomy_level=str(row[16]),
            risk_threshold=str(row[17]),
            approval_timeout_minutes=int(row[18]),
            daily_budget_cents=int(row[19]),
        )

    @staticmethod
    def _hydrate_share(row: tuple) -> DigitalEmployeeShare:
        return DigitalEmployeeShare(
            tenant_id=str(row[0]),
            agent_key=str(row[1]),
            grantee_user_id=str(row[2]),
            permission=str(row[3]),
            granted_by=str(row[4]),
            granted_at=row[5],
        )

    # ------------------------------------------------------------ 岗位

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole:
        _ensure_admin(context)
        key = normalize_key(role_key)
        clean_name = normalize_name(name)
        clean_description = normalize_description(description)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_job_roles
                            (tenant_id, role_key, name, description, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, role_key) DO NOTHING
                        RETURNING {self._ROLE_COLUMNS}
                        """,
                        (context.tenant_id, key, clean_name, clean_description, DirectoryStatus.ACTIVE.value, context.user_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise DirectoryConflict("该岗位标识已存在")
        return self._hydrate_role(row)

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole:
        _ensure_admin(context)
        key = normalize_key(role_key)
        clean_name = normalize_name(name) if name is not None else None
        clean_description = normalize_description(description) if description is not None else None
        clean_status = normalize_status(status).value if status is not None else None
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_job_roles
                        SET name = COALESCE(%s, name),
                            description = COALESCE(%s, description),
                            status = COALESCE(%s, status),
                            updated_at = now()
                        WHERE tenant_id = %s AND role_key = %s
                        RETURNING {self._ROLE_COLUMNS}
                        """,
                        (clean_name, clean_description, clean_status, context.tenant_id, key),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise DirectoryNotFound(role_key)
        return self._hydrate_role(row)

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]:
        _ensure_directory_reader(context)
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        # V1=C：非管理员**只看到启用岗位**（管理页走 `super_admin`，仍可按 status 过滤看全部）。
        if context.role == "super_admin":
            if status is not None:
                clauses.append("status = %s")
                params.append(normalize_status(status).value)
        else:
            clauses.append("status = %s")
            params.append(DirectoryStatus.ACTIVE.value)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._ROLE_COLUMNS} FROM workbench_job_roles WHERE {where} ORDER BY role_key LIMIT %s OFFSET %s",
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_job_roles WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_role(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    # ------------------------------------------------------------ 数字员工

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "", owner_user_id: str | None = None) -> DigitalEmployee:
        owner = _resolve_owner(context, owner_user_id)
        key = normalize_key(agent_key)
        target_role = normalize_key(role_key)
        clean_name = normalize_name(name)
        clean_description = normalize_description(description)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._require_active_role(cursor, context.tenant_id, target_role)
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_digital_employees
                            (tenant_id, agent_key, name, description, role_key, status, created_by, owner_user_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, agent_key) DO NOTHING
                        RETURNING {self._EMPLOYEE_COLUMNS}
                        """,
                        (context.tenant_id, key, clean_name, clean_description, target_role, DirectoryStatus.ACTIVE.value, context.user_id, owner),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise DirectoryConflict("该数字员工标识已存在")
        return self._hydrate_employee(row)

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee:
        _ensure_admin(context)
        key = normalize_key(agent_key)
        target_role = normalize_key(role_key) if role_key is not None else None
        clean_name = normalize_name(name) if name is not None else None
        clean_description = normalize_description(description) if description is not None else None
        clean_status = normalize_status(status).value if status is not None else None
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    if target_role is not None:
                        self._require_active_role(cursor, context.tenant_id, target_role)
                    cursor.execute(
                        f"""
                        UPDATE workbench_digital_employees
                        SET name = COALESCE(%s, name),
                            description = COALESCE(%s, description),
                            role_key = COALESCE(%s, role_key),
                            status = COALESCE(%s, status),
                            updated_at = now()
                        WHERE tenant_id = %s AND agent_key = %s
                        RETURNING {self._EMPLOYEE_COLUMNS}
                        """,
                        (clean_name, clean_description, target_role, clean_status, context.tenant_id, key),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise DirectoryNotFound(agent_key)
        return self._hydrate_employee(row)

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]:
        _ensure_directory_reader(context)
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if role_key is not None:
            clauses.append("role_key = %s")
            params.append(normalize_key(role_key))
        if status is not None:
            clauses.append("status = %s")
            params.append(normalize_status(status).value)
        # ⚠️ 过滤**在 SQL 里**做（不是取全量再让上层筛）：非 super_admin 只看「归属自己 ∪ 被共享」。
        if context.role != "super_admin":
            clauses.append(
                "(owner_user_id = %s OR agent_key IN ("
                "SELECT agent_key FROM workbench_employee_shares "
                "WHERE tenant_id = %s AND grantee_user_id = %s))"
            )
            params.extend([context.user_id, context.tenant_id, context.user_id])
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._EMPLOYEE_COLUMNS} FROM workbench_digital_employees WHERE {where} ORDER BY role_key, agent_key LIMIT %s OFFSET %s",
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_digital_employees WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_employee(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    # ------------------------------------------------------------ 共享层（迁移 045）

    def add_share(self, context: UserContext, agent_key: str, *, grantee_user_id: str, permission: str) -> DigitalEmployeeShare:
        """把**自己的**员工按档位共享给某人；**仅归属人**（他人 / 跨租户 404，不泄露存在性）。"""
        key = self._require_owned_agent(context, agent_key)
        grantee = _clean_grantee(grantee_user_id)
        clean_permission = _clean_share_permission(permission)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_employee_shares
                            (tenant_id, agent_key, grantee_user_id, permission, granted_by)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, agent_key, grantee_user_id)
                        DO UPDATE SET permission = EXCLUDED.permission, granted_by = EXCLUDED.granted_by
                        RETURNING {self._SHARE_COLUMNS}
                        """,
                        (context.tenant_id, key, grantee, clean_permission, context.user_id),
                    )
                    row = cursor.fetchone()
        if row is None:  # pragma: no cover - RETURNING 恒有行；仅为类型收敛
            raise DirectoryNotFound(agent_key)
        return self._hydrate_share(row)

    def list_shares(self, context: UserContext, agent_key: str, *, limit: int = MAX_LIMIT, offset: int = 0) -> tuple[list[DigitalEmployeeShare], int]:
        key = self._require_owned_agent(context, agent_key)
        where = "tenant_id = %s AND agent_key = %s"
        params = (context.tenant_id, key)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._SHARE_COLUMNS} FROM workbench_employee_shares WHERE {where} "
                    "ORDER BY grantee_user_id LIMIT %s OFFSET %s",
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_employee_shares WHERE {where}", params)
                count_row = cursor.fetchone()
        return [self._hydrate_share(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def remove_share(self, context: UserContext, agent_key: str, grantee_user_id: str) -> bool:
        """撤销共享；**幂等**：本就不是共享者返回 `False`（调用方据此不重复写审计）。"""
        key = self._require_owned_agent(context, agent_key)
        grantee = str(grantee_user_id).strip()
        if not grantee:
            return False
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_employee_shares "
                        "WHERE tenant_id = %s AND agent_key = %s AND grantee_user_id = %s",
                        (context.tenant_id, key, grantee),
                    )
                    return int(cursor.rowcount) > 0

    def visible_agent_keys(self, context: UserContext) -> set[str] | None:
        """调用者可见的员工标识集合；`None` = **不受限**（`super_admin` 管理视角）。

        与 `list_employees` **同一 SQL 口径**（`owner ∪ shares`），供 `roster` 复用 ——
        否则该端点会把本租户全量员工标识与任务数发给任意登录身份。
        """
        if context.role == "super_admin":
            return None
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT agent_key FROM workbench_digital_employees
                    WHERE tenant_id = %s AND (
                        owner_user_id = %s OR agent_key IN (
                            SELECT agent_key FROM workbench_employee_shares
                            WHERE tenant_id = %s AND grantee_user_id = %s))
                    """,
                    (context.tenant_id, context.user_id, context.tenant_id, context.user_id),
                )
                rows = cursor.fetchall()
        return {str(row[0]) for row in rows}

    def read_agent_owner(self, context: UserContext, agent_key: str) -> str | None:
        """本租户内该员工的归属人；未纳管 / 标识非法 ⇒ `None`（跨租户同样按不存在处理）。"""
        key = _safe_key(agent_key)
        if not key:
            return None
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT owner_user_id FROM workbench_digital_employees WHERE tenant_id = %s AND agent_key = %s",
                    (context.tenant_id, key),
                )
                row = cursor.fetchone()
        return str(row[0] or "") if row is not None else None

    def share_permission(self, context: UserContext, agent_key: str, user_id: str) -> str | None:
        key = _safe_key(agent_key)
        if not key or not user_id:
            return None
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT permission FROM workbench_employee_shares "
                    "WHERE tenant_id = %s AND agent_key = %s AND grantee_user_id = %s",
                    (context.tenant_id, key, user_id),
                )
                row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def _require_owned_agent(self, context: UserContext, agent_key: str) -> str:
        """归属人校验（`add_share` / `list_shares` / `remove_share` 共用同一口径）。

        不存在 / 不是归属人一律 `DirectoryNotFound`（**不泄露存在性**）。
        共享管理**仅归属人**可做（契约 C4）；`super_admin` 亦不例外
        —— 管理员要处置员工走 `update_employee`（管理档），两条路径不混。
        """
        key = _safe_key(agent_key)
        if not key or not context.user_id:
            raise DirectoryNotFound(agent_key)
        if self.read_agent_owner(context, key) != context.user_id:
            raise DirectoryNotFound(agent_key)
        return key

    # ------------------------------------------------------------ 配置读写（读 = 归属人 ∪ read 档 ∪ 超管；写 = 仅超管）

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        key = normalize_key(agent_key)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._AGENT_CONFIG_COLUMNS} FROM workbench_digital_employees WHERE tenant_id = %s AND agent_key = %s",
                    (context.tenant_id, key),
                )
                row = cursor.fetchone()
        if row is None:
            raise DirectoryNotFound(agent_key)
        employee = self._hydrate_agent_config(row)
        # 归属人 / 超管无需再查共享行（省一次往返）；其余身份查 `read` 档（V4=A：`use` 档不可读）。
        permission = None
        if context.role != "super_admin" and employee.owner_user_id != context.user_id:
            permission = self.share_permission(context, employee.agent_key, context.user_id)
        _ensure_config_reader(context, employee, permission)
        return employee

    def update_agent_config(self, context: UserContext, agent_key: str, *, system_prompt: str | None = None, model_key: str | None = None, temperature: float | None = None, tool_allowlist: tuple[str, ...] | None = None, memory_policy: dict[str, object] | None = None, autonomy_level: str | None = None, risk_threshold: str | None = None, approval_timeout_minutes: int | None = None, daily_budget_cents: int | None = None) -> DigitalEmployee:
        _ensure_admin(context)
        key = normalize_key(agent_key)
        changes = _clean_config_changes(
            {
                "system_prompt": system_prompt,
                "model_key": model_key,
                "temperature": temperature,
                "tool_allowlist": tool_allowlist,
                "memory_policy": memory_policy,
                "autonomy_level": autonomy_level,
                "risk_threshold": risk_threshold,
                "approval_timeout_minutes": approval_timeout_minutes,
                "daily_budget_cents": daily_budget_cents,
            }
        )
        tool_allowlist_json = (
            json.dumps(list(changes["tool_allowlist"]), ensure_ascii=False)  # type: ignore[arg-type]
            if "tool_allowlist" in changes
            else None
        )
        memory_policy_json = (
            json.dumps(changes["memory_policy"], ensure_ascii=False) if "memory_policy" in changes else None
        )
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_digital_employees
                        SET system_prompt = COALESCE(%s, system_prompt),
                            model_key = COALESCE(%s, model_key),
                            temperature = COALESCE(%s, temperature),
                            tool_allowlist = COALESCE(%s::jsonb, tool_allowlist),
                            memory_policy = COALESCE(%s::jsonb, memory_policy),
                            autonomy_level = COALESCE(%s, autonomy_level),
                            risk_threshold = COALESCE(%s, risk_threshold),
                            approval_timeout_minutes = COALESCE(%s, approval_timeout_minutes),
                            daily_budget_cents = COALESCE(%s, daily_budget_cents),
                            updated_at = now()
                        WHERE tenant_id = %s AND agent_key = %s
                        RETURNING {self._AGENT_CONFIG_COLUMNS}
                        """,
                        (
                            changes.get("system_prompt"),
                            changes.get("model_key"),
                            changes.get("temperature"),
                            tool_allowlist_json,
                            memory_policy_json,
                            changes.get("autonomy_level"),
                            changes.get("risk_threshold"),
                            changes.get("approval_timeout_minutes"),
                            changes.get("daily_budget_cents"),
                            context.tenant_id,
                            key,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise DirectoryNotFound(agent_key)
        return self._hydrate_agent_config(row)

    def read_agent_governance(self, context: UserContext, agent_key: str) -> tuple[str, str] | None:
        """只读治理两字段；语义与内存仓储逐条对齐（不校验角色、非法标识与停用一律 `None`）。

        可用性口径 = `agent_is_active`（**岗位停用连带**）：`JOIN workbench_job_roles` 后
        **员工自身 `active` 且所属岗位 `active`** 才返回治理两字段；岗位缺失或已停用一并 `None`。
        """
        key = _safe_key(agent_key)
        if not key:
            return None
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT employee.autonomy_level, employee.risk_threshold
                    FROM workbench_digital_employees AS employee
                    JOIN workbench_job_roles AS role
                      ON role.tenant_id = employee.tenant_id AND role.role_key = employee.role_key
                    WHERE employee.tenant_id = %s AND employee.agent_key = %s
                      AND employee.status = 'active' AND role.status = 'active'
                    """,
                    (context.tenant_id, key),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return (str(row[0]), str(row[1]))

    # ------------------------------------------------------------ 供「未纳管」计算

    def known_keys(self, context: UserContext) -> tuple[set[str], set[str]]:
        _ensure_admin(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT role_key FROM workbench_job_roles WHERE tenant_id = %s", (context.tenant_id,))
                role_keys = {str(row[0]) for row in cursor.fetchall()}
                cursor.execute("SELECT agent_key FROM workbench_digital_employees WHERE tenant_id = %s", (context.tenant_id,))
                agent_keys = {str(row[0]) for row in cursor.fetchall()}
        return role_keys, agent_keys

    @staticmethod
    def _require_active_role(cursor, tenant_id: str, role_key: str) -> None:
        cursor.execute(
            "SELECT status FROM workbench_job_roles WHERE tenant_id = %s AND role_key = %s",
            (tenant_id, role_key),
        )
        row = cursor.fetchone()
        if row is None:
            raise RoleNotAvailable("岗位不存在或不属于本租户")
        if str(row[0]) != DirectoryStatus.ACTIVE.value:
            raise RoleNotAvailable("岗位已停用，不能再挂载数字员工")

    # ------------------------------------------------------------ 可用性判定（阶段 2 写路径闸门）

    def role_is_active(self, context: UserContext, role_key: str) -> bool:
        """标识是否已在目录且启用；非法或空标识按「不可用」处理（不抛异常）。"""
        _ensure_admin(context)
        return self._status_is_active("workbench_job_roles", "role_key", context.tenant_id, role_key)

    def agent_is_active(self, context: UserContext, agent_key: str) -> bool:
        """员工可用 = 员工自身 active **且** 所属岗位 active；一次 JOIN 查完，避免两次往返。"""
        _ensure_admin(context)
        key = _safe_key(agent_key)
        if not key:
            return False
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT employee.status, role.status
                    FROM workbench_digital_employees AS employee
                    LEFT JOIN workbench_job_roles AS role
                      ON role.tenant_id = employee.tenant_id AND role.role_key = employee.role_key
                    WHERE employee.tenant_id = %s AND employee.agent_key = %s
                    """,
                    (context.tenant_id, key),
                )
                row = cursor.fetchone()
        if row is None:
            return False
        # 所属岗位缺失时 LEFT JOIN 出 NULL，与「已停用」同样按不可用处理
        return str(row[0]) == DirectoryStatus.ACTIVE.value and str(row[1]) == DirectoryStatus.ACTIVE.value

    def _status_is_active(self, table: str, column: str, tenant_id: str, value: str) -> bool:
        key = _safe_key(value)
        if not key:
            return False
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT status FROM {table} WHERE tenant_id = %s AND {column} = %s",
                    (tenant_id, key),
                )
                row = cursor.fetchone()
        return row is not None and str(row[0]) == DirectoryStatus.ACTIVE.value
