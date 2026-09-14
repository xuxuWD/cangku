"""岗位与数字员工目录仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制（复用 `_ensure_admin`），避免调用方绕过接口层直接读写。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from threading import RLock
from typing import Protocol

from ..domain import PolicyError, UserContext
from .models import (
    DigitalEmployee,
    DirectoryConflict,
    DirectoryNotFound,
    DirectoryStatus,
    InvalidDirectoryKey,
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
    """目录读写；所有方法都要求 `super_admin` 且严格限定本租户。"""

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole: ...

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole: ...

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]: ...

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "") -> DigitalEmployee: ...

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee: ...

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]: ...

    def known_keys(self, context: UserContext) -> tuple[set[str], set[str]]: ...

    def role_is_active(self, context: UserContext, role_key: str) -> bool: ...

    def agent_is_active(self, context: UserContext, agent_key: str) -> bool: ...

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee: ...

    def read_agent_governance(self, context: UserContext, agent_key: str) -> tuple[str, str] | None: ...

    def update_agent_config(self, context: UserContext, agent_key: str, *, system_prompt: str | None = None, model_key: str | None = None, temperature: float | None = None, tool_allowlist: tuple[str, ...] | None = None, memory_policy: dict[str, object] | None = None, autonomy_level: str | None = None, risk_threshold: str | None = None, approval_timeout_minutes: int | None = None, daily_budget_cents: int | None = None) -> DigitalEmployee: ...


def _ensure_admin(context: UserContext) -> None:
    if context.role != "super_admin":
        raise PolicyError("只有超级管理员可以管理岗位与数字员工目录")


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


class InMemoryWorkforceDirectoryStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._roles: dict[tuple[str, str], JobRole] = {}
        self._employees: dict[tuple[str, str], DigitalEmployee] = {}
        self._lock = RLock()

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
        _ensure_admin(context)
        wanted = normalize_status(status) if status is not None else None
        with self._lock:
            matched = [
                role
                for (tenant_id, _key), role in sorted(self._roles.items())
                if tenant_id == context.tenant_id and (wanted is None or role.status == wanted)
            ]
        return matched[offset : offset + _clamp(limit)], len(matched)

    # ------------------------------------------------------------ 数字员工

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "") -> DigitalEmployee:
        _ensure_admin(context)
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
        _ensure_admin(context)
        wanted = normalize_status(status) if status is not None else None
        wanted_role = normalize_key(role_key) if role_key is not None else None
        with self._lock:
            matched = [
                employee
                for (tenant_id, _key), employee in sorted(self._employees.items())
                if tenant_id == context.tenant_id
                and (wanted is None or employee.status == wanted)
                and (wanted_role is None or employee.role_key == wanted_role)
            ]
        return matched[offset : offset + _clamp(limit)], len(matched)

    # ------------------------------------------------------------ 配置读写（仅 super_admin）

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        _ensure_admin(context)
        key = normalize_key(agent_key)
        with self._lock:
            employee = self._employees.get((context.tenant_id, key))
        if employee is None:
            raise DirectoryNotFound(agent_key)
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
    _EMPLOYEE_COLUMNS = "tenant_id, agent_key, name, description, role_key, status, created_by, created_at, updated_at"
    # 配置读写在既有列之后追加 §7.2 字段；既有 CRUD/列表仍用 _EMPLOYEE_COLUMNS（其默认值由数据类补齐）
    _AGENT_CONFIG_COLUMNS = (
        f"{_EMPLOYEE_COLUMNS}, system_prompt, model_key, temperature, tool_allowlist, "
        "memory_policy, autonomy_level, risk_threshold, approval_timeout_minutes, daily_budget_cents"
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
            system_prompt=str(row[9] or ""),
            model_key=str(row[10] or ""),
            temperature=float(row[11]) if row[11] is not None else 0.20,
            tool_allowlist=_as_str_tuple(row[12]),
            memory_policy=_as_dict(row[13]),
            autonomy_level=str(row[14]),
            risk_threshold=str(row[15]),
            approval_timeout_minutes=int(row[16]),
            daily_budget_cents=int(row[17]),
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
        _ensure_admin(context)
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(normalize_status(status).value)
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

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "") -> DigitalEmployee:
        _ensure_admin(context)
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
                            (tenant_id, agent_key, name, description, role_key, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, agent_key) DO NOTHING
                        RETURNING {self._EMPLOYEE_COLUMNS}
                        """,
                        (context.tenant_id, key, clean_name, clean_description, target_role, DirectoryStatus.ACTIVE.value, context.user_id),
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
        _ensure_admin(context)
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if role_key is not None:
            clauses.append("role_key = %s")
            params.append(normalize_key(role_key))
        if status is not None:
            clauses.append("status = %s")
            params.append(normalize_status(status).value)
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

    # ------------------------------------------------------------ 配置读写（仅 super_admin）

    def read_agent_config(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        _ensure_admin(context)
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
        return self._hydrate_agent_config(row)

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
