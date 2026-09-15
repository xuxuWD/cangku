"""技能仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制（复用 `models` 的访问判定），避免调用方绕过接口层直接读写。
所有查询严格带 `tenant_id`，不依赖任何调用方传入的租户条件（沿用记忆层 store 骨架）。

状态机在 `review` / `enable` / `disable` 强制（submitted → approved/rejected →
enabled → disabled，`enabled ⇄ disabled` 可回退），版本递增校验在 `submit` 强制（幂等优先）。
除生命周期方法（`list_all_for_tenant` / `delete_all_for_tenant`）外均做本人 / 管理员校验。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from threading import RLock
from typing import Protocol

from ..domain import UserContext
from .models import (
    BindingStatus,
    InvalidSkillPackage,
    Skill,
    SkillBinding,
    SkillNotFound,
    SkillStateConflict,
    SkillStatus,
    can_review,
    parse_version,
    skill_visible_to,
)

MAX_LIMIT = 200


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _parse_tools(value) -> tuple[str, ...]:
    """把 `allowed_tools`（JSONB 或已解析列表）归一为 tuple[str]。"""
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return ()
        return tuple(str(item) for item in parsed)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


class SkillStore(Protocol):
    """技能与绑定读写；除生命周期方法外，严格限定本租户并做归属校验。"""

    def submit(self, context, *, skill, package_sha256) -> Skill: ...

    def get(self, context, skill_key, version) -> Skill: ...

    def list(self, context, *, status=None, limit=50, offset=0) -> tuple[list[Skill], int]: ...

    def review(self, context, skill_key, version, *, approved) -> Skill: ...

    def enable(self, context, skill_key, version) -> Skill: ...

    def disable(self, context, skill_key, version) -> Skill: ...

    def bind_skill(self, context, agent_key, skill_key, *, created_by) -> SkillBinding: ...

    def unbind_skill(self, context, agent_key, skill_key) -> SkillBinding: ...

    def list_bindings(self, context, *, agent_key=None, skill_key=None, limit=50, offset=0) -> tuple[list[SkillBinding], int]: ...

    def list_enabled_for_agent(self, context, agent_key) -> list[Skill]: ...

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[Skill]: ...

    def delete_all_for_tenant(self, tenant_id) -> int: ...


class InMemorySkillStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._skills: dict[tuple[str, str, str], Skill] = {}
        self._bindings: dict[tuple[str, str, str], SkillBinding] = {}
        self._lock = RLock()

    # ------------------------------------------------------------ 技能包

    def submit(self, context, *, skill, package_sha256) -> Skill:
        with self._lock:
            key = (context.tenant_id, skill.skill_key, skill.version)
            existing = self._skills.get(key)
            if existing is not None:
                return existing  # 幂等：同 (tenant, skill_key, version) 返回既有。
            # 版本递增校验：同 skill_key 存在更高版本 → 409（相同版本已在上一步走幂等返回）。
            for (_tid, k, _v), row in self._skills.items():
                if _tid == context.tenant_id and k == skill.skill_key:
                    if parse_version(row.version) > parse_version(skill.version):
                        raise SkillStateConflict("已存在更高版本的技能包，请提交更新版本号之一")
            payload = replace(skill, content_sha256=package_sha256, status=SkillStatus.SUBMITTED)
            self._skills[key] = payload
            return payload

    def _get_raw(self, context, skill_key, version) -> Skill:
        row = self._skills.get((context.tenant_id, skill_key, version))
        if row is None:
            raise SkillNotFound(f"{skill_key}@{version}")
        return row

    def get(self, context, skill_key, version) -> Skill:
        skill = self._get_raw(context, skill_key, version)
        if not skill_visible_to(context, skill):
            raise SkillNotFound(f"{skill_key}@{version}")
        return skill

    def list(self, context, *, status=None, limit=50, offset=0) -> tuple[list[Skill], int]:
        clean_status = None
        if status is not None:
            clean_status = SkillStatus(status)
        with self._lock:
            matched = []
            for (tid, _k, _v), skill in self._skills.items():
                if tid != context.tenant_id:
                    continue
                if not can_review(context) and skill.owner_id != context.user_id:
                    continue  # 普通员工只看自己提交的（§store.list）。
                if clean_status is not None and skill.status is not clean_status:
                    continue
                matched.append(skill)
        matched.sort(key=lambda s: (_dt_or_min(s.created_at), s.skill_key, s.version), reverse=True)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def review(self, context, skill_key, version, *, approved) -> Skill:
        with self._lock:
            skill = self._get_raw(context, skill_key, version)
            if skill.status is not SkillStatus.SUBMITTED:
                raise SkillStateConflict("仅 submitted 状态的技能包可审核")
            new_status = SkillStatus.APPROVED if approved else SkillStatus.REJECTED
            updated = replace(
                skill,
                status=new_status,
                reviewed_by=context.user_id,
            )
            self._skills[(context.tenant_id, skill_key, version)] = updated
            return updated

    def enable(self, context, skill_key, version) -> Skill:
        with self._lock:
            skill = self._get_raw(context, skill_key, version)
            if skill.status is SkillStatus.ENABLED:
                return skill  # 幂等
            if skill.status not in (SkillStatus.APPROVED, SkillStatus.DISABLED):
                raise SkillStateConflict("仅 approved / disabled 状态的技能包可启用")
            updated = replace(skill, status=SkillStatus.ENABLED)
            self._skills[(context.tenant_id, skill_key, version)] = updated
            return updated

    def disable(self, context, skill_key, version) -> Skill:
        with self._lock:
            skill = self._get_raw(context, skill_key, version)
            if skill.status is SkillStatus.DISABLED:
                return skill  # 幂等
            if skill.status is not SkillStatus.ENABLED:
                raise SkillStateConflict("仅 enabled 状态的技能包可停用")
            updated = replace(skill, status=SkillStatus.DISABLED)
            self._skills[(context.tenant_id, skill_key, version)] = updated
            return updated

    # ------------------------------------------------------------ 绑定

    def bind_skill(self, context, agent_key, skill_key, *, created_by) -> SkillBinding:
        with self._lock:
            key = (context.tenant_id, agent_key, skill_key)
            existing = self._bindings.get(key)
            if existing is not None and existing.status is BindingStatus.ACTIVE:
                return existing  # 幂等
            binding = SkillBinding(
                tenant_id=context.tenant_id,
                agent_key=agent_key,
                skill_key=skill_key,
                status=BindingStatus.ACTIVE,
                created_by=created_by,
            )
            self._bindings[key] = binding  # UPSERT active（覆盖 disabled）
            return binding

    def unbind_skill(self, context, agent_key, skill_key) -> SkillBinding:
        with self._lock:
            key = (context.tenant_id, agent_key, skill_key)
            existing = self._bindings.get(key)
            if existing is None:
                raise SkillNotFound(f"binding {agent_key}/{skill_key}")
            if existing.status is BindingStatus.DISABLED:
                return existing  # 幂等
            updated = replace(existing, status=BindingStatus.DISABLED)
            self._bindings[key] = updated
            return updated

    def list_bindings(self, context, *, agent_key=None, skill_key=None, limit=50, offset=0) -> tuple[list[SkillBinding], int]:
        with self._lock:
            matched = [
                b
                for (tid, _a, _s), b in self._bindings.items()
                if tid == context.tenant_id
                and (agent_key is None or b.agent_key == agent_key)
                and (skill_key is None or b.skill_key == skill_key)
            ]
        matched.sort(key=lambda b: (b.created_at or parse_epoch(b), b.agent_key, b.skill_key))
        return matched[offset : offset + _clamp(limit)], len(matched)

    def list_enabled_for_agent(self, context, agent_key) -> list[Skill]:
        with self._lock:
            bound_keys = {
                b.skill_key
                for (tid, _a, _s), b in self._bindings.items()
                if tid == context.tenant_id and b.agent_key == agent_key and b.status is BindingStatus.ACTIVE
            }
            enabled = []
            for (tid, _k, _v), skill in self._skills.items():
                if tid == context.tenant_id and skill.status is SkillStatus.ENABLED and skill.skill_key in bound_keys:
                    enabled.append(skill)
            enabled.sort(key=lambda s: (_dt_or_min(s.created_at), s.skill_key))
        return enabled

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[Skill]:
        with self._lock:
            return [
                skill
                for (tid, _k, _v), skill in self._skills.items()
                if tid == tenant_id and (since is None or (skill.created_at and skill.created_at >= since))
            ]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._lock:
            keys = [key for key in list(self._skills.keys()) if key[0] == tenant_id]
            for key in keys:
                del self._skills[key]
            return len(keys)


def _dt_or_min(value):
    from datetime import datetime
    return value or datetime.min


class PostgresSkillStore:
    """技能持久化（表 `workbench_skills` / `workbench_skill_bindings`，迁移 030）。"""

    _SKILL_COLUMNS = (
        "tenant_id, skill_key, version, name, description, license, allowed_tools, "
        "status, source_key, content_sha256, owner_id, reviewed_by, created_at, updated_at, "
        "content_body"
    )
    _BINDING_COLUMNS = "tenant_id, agent_key, skill_key, status, created_by, created_at"

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

    @classmethod
    def _hydrate_skill(cls, row: tuple) -> Skill:
        # `_SKILL_COLUMNS`：0 tenant_id,1 skill_key,2 version,3 name,4 description,5 license,
        # 6 allowed_tools,7 status,8 source_key,9 content_sha256,10 owner_id,11 reviewed_by,
        # 12 created_at,13 updated_at,14 content_body（M5，031 迁移）。
        return Skill(
            tenant_id=str(row[0]),
            skill_key=str(row[1]),
            version=str(row[2]),
            name=str(row[3]),
            description=str(row[4]),
            license=str(row[5]),
            allowed_tools=_parse_tools(row[6]),
            status=SkillStatus(str(row[7])),
            source_key=str(row[8]),
            content_sha256=str(row[9]),
            owner_id=str(row[10]),
            reviewed_by=None if row[11] is None else str(row[11]),
            created_at=row[12],
            updated_at=row[13],
            content_body="" if row[14] is None else str(row[14]),
        )

    @classmethod
    def _hydrate_binding(cls, row: tuple) -> SkillBinding:
        # `_BINDING_COLUMNS`：0 tenant_id,1 agent_key,2 skill_key,3 status,4 created_by,5 created_at。
        return SkillBinding(
            tenant_id=str(row[0]),
            agent_key=str(row[1]),
            skill_key=str(row[2]),
            status=BindingStatus(str(row[3])),
            created_by=str(row[4]),
            created_at=row[5],
        )

    @staticmethod
    def _tools_json(tools) -> str:
        return json.dumps([str(t) for t in (tools or ())])

    # ------------------------------------------------------------ 技能包

    def submit(self, context, *, skill, package_sha256) -> Skill:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._SKILL_COLUMNS} FROM workbench_skills
                        WHERE tenant_id = %s AND skill_key = %s AND version = %s
                        """,
                        (context.tenant_id, skill.skill_key, skill.version),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        return self._hydrate_skill(existing)  # 幂等：返回既有记录。
                    # 版本递增校验：同 skill_key 已有更高版本 → 409。
                    cursor.execute(
                        """
                        SELECT version FROM workbench_skills
                        WHERE tenant_id = %s AND skill_key = %s
                        """,
                        (context.tenant_id, skill.skill_key),
                    )
                    for (existing_version,) in cursor.fetchall():
                        if parse_version(str(existing_version)) > parse_version(skill.version):
                            raise SkillStateConflict("已存在更高版本的技能包，请提交更新版本号之一")
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_skills
                            (tenant_id, skill_key, version, name, description, license,
                             allowed_tools, status, source_key, content_sha256, owner_id, content_body)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                        RETURNING {self._SKILL_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            skill.skill_key,
                            skill.version,
                            skill.name,
                            skill.description,
                            skill.license,
                            self._tools_json(skill.allowed_tools),
                            SkillStatus.SUBMITTED.value,
                            skill.source_key,
                            package_sha256,
                            skill.owner_id,
                            skill.content_body,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise SkillNotFound(f"{skill.skill_key}@{skill.version}")
        return self._hydrate_skill(row)

    def _fetch_skill(self, connection, tenant_id, skill_key, version) -> tuple | None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {self._SKILL_COLUMNS} FROM workbench_skills WHERE tenant_id = %s AND skill_key = %s AND version = %s",
                (tenant_id, skill_key, version),
            )
            return cursor.fetchone()

    def get(self, context, skill_key, version) -> Skill:
        with self._connection() as connection:
            row = self._fetch_skill(connection, context.tenant_id, skill_key, version)
        if row is None:
            raise SkillNotFound(f"{skill_key}@{version}")
        skill = self._hydrate_skill(row)
        if not skill_visible_to(context, skill):
            raise SkillNotFound(f"{skill_key}@{version}")
        return skill

    def list(self, context, *, status=None, limit=50, offset=0) -> tuple[list[Skill], int]:
        clean_status = SkillStatus(status) if status is not None else None
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if not can_review(context):
            clauses.append("owner_id = %s")
            params.append(context.user_id)
        if clean_status is not None:
            clauses.append("status = %s")
            params.append(clean_status.value)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SKILL_COLUMNS} FROM workbench_skills
                    WHERE {where} ORDER BY created_at DESC, skill_key ASC, version ASC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_skills WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_skill(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def _update_status(self, context, skill_key, version, *, new_status, allowed_if):
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_skills
                        SET status = %s, updated_at = now()
                        WHERE tenant_id = %s AND skill_key = %s AND version = %s AND status IN ({", ".join(["%s"] * len(allowed_if))})
                        RETURNING {self._SKILL_COLUMNS}
                        """,
                        (new_status, context.tenant_id, skill_key, version, *[s.value for s in allowed_if]),
                    )
                    row = cursor.fetchone()
        return None if row is None else self._hydrate_skill(row)

    def review(self, context, skill_key, version, *, approved) -> Skill:
        new_status = SkillStatus.APPROVED if approved else SkillStatus.REJECTED
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # 仅 submitted 可审核；不满足不更新、返回 None → 由状态冲突升级为 409。
                    cursor.execute(
                        f"""
                        UPDATE workbench_skills
                        SET status = %s, reviewed_by = %s, updated_at = now()
                        WHERE tenant_id = %s AND skill_key = %s AND version = %s AND status = %s
                        RETURNING {self._SKILL_COLUMNS}
                        """,
                        (new_status.value, context.user_id, context.tenant_id, skill_key, version, SkillStatus.SUBMITTED.value),
                    )
                    row = cursor.fetchone()
        if row is None:
            # 区分「不存在」与「状态冲突」。
            with self._connection() as connection:
                exists = self._fetch_skill(connection, context.tenant_id, skill_key, version)
            if exists is None:
                raise SkillNotFound(f"{skill_key}@{version}")
            raise SkillStateConflict("仅 submitted 状态的技能包可审核")
        return self._hydrate_skill(row)

    def enable(self, context, skill_key, version) -> Skill:
        result = self._update_status(
            context, skill_key, version,
            new_status=SkillStatus.ENABLED,
            allowed_if=(SkillStatus.APPROVED, SkillStatus.DISABLED),
        )
        if result is not None:
            return result
        # 检查幂等（已 enabled）否则 409/404。
        with self._connection() as connection:
            row = self._fetch_skill(connection, context.tenant_id, skill_key, version)
        if row is None:
            raise SkillNotFound(f"{skill_key}@{version}")
        skill = self._hydrate_skill(row)
        if skill.status is SkillStatus.ENABLED:
            return skill  # 幂等
        raise SkillStateConflict("仅 approved / disabled 状态的技能包可启用")

    def disable(self, context, skill_key, version) -> Skill:
        result = self._update_status(
            context, skill_key, version,
            new_status=SkillStatus.DISABLED,
            allowed_if=(SkillStatus.ENABLED,),
        )
        if result is not None:
            return result
        with self._connection() as connection:
            row = self._fetch_skill(connection, context.tenant_id, skill_key, version)
        if row is None:
            raise SkillNotFound(f"{skill_key}@{version}")
        skill = self._hydrate_skill(row)
        if skill.status is SkillStatus.DISABLED:
            return skill  # 幂等
        raise SkillStateConflict("仅 enabled 状态的技能包可停用")

    # ------------------------------------------------------------ 绑定

    def bind_skill(self, context, agent_key, skill_key, *, created_by) -> SkillBinding:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_skill_bindings
                            (tenant_id, agent_key, skill_key, status, created_by)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, agent_key, skill_key)
                        DO UPDATE SET status = EXCLUDED.status, created_by = EXCLUDED.created_by
                        RETURNING {self._BINDING_COLUMNS}
                        """,
                        (context.tenant_id, agent_key, skill_key, BindingStatus.ACTIVE.value, created_by),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise SkillNotFound(f"binding {agent_key}/{skill_key}")
        return self._hydrate_binding(row)

    def unbind_skill(self, context, agent_key, skill_key) -> SkillBinding:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_skill_bindings
                        SET status = %s
                        WHERE tenant_id = %s AND agent_key = %s AND skill_key = %s AND status = %s
                        RETURNING {self._BINDING_COLUMNS}
                        """,
                        (BindingStatus.DISABLED.value, context.tenant_id, agent_key, skill_key, BindingStatus.ACTIVE.value),
                    )
                    row = cursor.fetchone()
        if row is not None:
            return self._hydrate_binding(row)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._BINDING_COLUMNS} FROM workbench_skill_bindings WHERE tenant_id = %s AND agent_key = %s AND skill_key = %s",
                    (context.tenant_id, agent_key, skill_key),
                )
                existing = cursor.fetchone()
        if existing is None:
            raise SkillNotFound(f"binding {agent_key}/{skill_key}")
        binding = self._hydrate_binding(existing)
        if binding.status is BindingStatus.DISABLED:
            return binding  # 幂等
        raise SkillStateConflict("绑定状态异常")

    def list_bindings(self, context, *, agent_key=None, skill_key=None, limit=50, offset=0) -> tuple[list[SkillBinding], int]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if agent_key is not None:
            clauses.append("agent_key = %s")
            params.append(agent_key)
        if skill_key is not None:
            clauses.append("skill_key = %s")
            params.append(skill_key)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._BINDING_COLUMNS} FROM workbench_skill_bindings
                    WHERE {where} ORDER BY created_at DESC, agent_key ASC, skill_key ASC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_skill_bindings WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_binding(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def list_enabled_for_agent(self, context, agent_key) -> list[Skill]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SKILL_COLUMNS} FROM workbench_skills
                    WHERE tenant_id = %s AND status = %s AND skill_key IN (
                        SELECT skill_key FROM workbench_skill_bindings
                        WHERE tenant_id = %s AND agent_key = %s AND status = %s
                    )
                    ORDER BY created_at ASC, skill_key ASC, version ASC
                    """,
                    (context.tenant_id, SkillStatus.ENABLED.value,
                     context.tenant_id, agent_key, BindingStatus.ACTIVE.value),
                )
                rows = cursor.fetchall()
        return [self._hydrate_skill(row) for row in rows]

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[Skill]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {self._SKILL_COLUMNS} FROM workbench_skills WHERE {where}", tuple(params))
                rows = cursor.fetchall()
        return [self._hydrate_skill(row) for row in rows]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM workbench_skills WHERE tenant_id = %s", (tenant_id,))
                    deleted = cursor.rowcount
        return int(deleted)


# re-export 供 import 使用
__all__ = [
    "SkillStore",
    "InMemorySkillStore",
    "PostgresSkillStore",
    "MAX_LIMIT",
]