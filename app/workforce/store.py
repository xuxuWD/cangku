"""岗位与数字员工目录仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制（复用 `_ensure_admin`），避免调用方绕过接口层直接读写。
"""

from __future__ import annotations

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
    JobRole,
    RoleNotAvailable,
    normalize_description,
    normalize_key,
    normalize_name,
    normalize_status,
    now,
)

MAX_LIMIT = 200


class WorkforceDirectoryStore(Protocol):
    """目录读写；所有方法都要求 `super_admin` 且严格限定本租户。"""

    def create_role(self, context: UserContext, *, role_key: str, name: str, description: str = "") -> JobRole: ...

    def update_role(self, context: UserContext, role_key: str, *, name: str | None = None, description: str | None = None, status: str | None = None) -> JobRole: ...

    def list_roles(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[JobRole], int]: ...

    def create_employee(self, context: UserContext, *, agent_key: str, name: str, role_key: str, description: str = "") -> DigitalEmployee: ...

    def update_employee(self, context: UserContext, agent_key: str, *, name: str | None = None, description: str | None = None, role_key: str | None = None, status: str | None = None) -> DigitalEmployee: ...

    def list_employees(self, context: UserContext, *, status: str | None = None, role_key: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[DigitalEmployee], int]: ...

    def known_keys(self, context: UserContext) -> tuple[set[str], set[str]]: ...


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


class PostgresWorkforceDirectoryStore:
    """目录持久化（表 `workbench_job_roles` / `workbench_digital_employees`，迁移 022）。"""

    _ROLE_COLUMNS = "tenant_id, role_key, name, description, status, created_by, created_at, updated_at"
    _EMPLOYEE_COLUMNS = "tenant_id, agent_key, name, description, role_key, status, created_by, created_at, updated_at"

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
