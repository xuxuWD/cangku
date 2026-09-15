"""记忆仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制（复用 `models` 的访问判定），避免调用方绕过接口层直接读写。
所有查询严格带 `tenant_id`，不依赖任何调用方传入的租户条件（沿用对话层 store 骨架）。

作用域（scope）由**服务层**解析后以枚举传入；仓储层只按传入值过滤/落库，不自行解析。
除 `list_all_for_tenant` / `delete_all_for_tenant`（生命周期专用，仅服务层判角色）外，
其余方法一律做本人 / VIEW_ANY 归属校验。
"""

from __future__ import annotations

import math
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Protocol

from ..domain import UserContext
from .models import (
    EMBEDDING_DIMENSIONS,
    MAX_PROFILE_KEYS_PER_OWNER,
    MemoryBudgetExceeded,
    MemoryFact,
    MemoryNotFound,
    MemoryOwnerKind,
    MemoryProfileKey,
    MemoryRule,
    MemoryScope,
    MemoryStatus,
    can_view_any,
    ensure_can_manage,
    ensure_can_view,
    new_memory_id,
    normalize_content,
    normalize_owner_kind,
    normalize_profile_key,
    normalize_profile_value,
    normalize_rule_key,
    normalize_scope,
)

MAX_LIMIT = 200


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _embedding_to_text(vector) -> str:
    """把 embedding 编码为 pgvector 文本格式 `[...]`（psycopg3 接受字符串自变量）。"""
    if vector is None:
        return "[]"
    return "[" + ",".join(f"{float(value):.6f}" for value in vector) + "]"


def _parse_embedding(value) -> tuple[float, ...] | None:
    """把 pgvector 返回值解析为 tuple[float]；NULL / 未注册扩展时保持 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1]
            tokens = [token for token in inner.replace(",", " ").split() if token]
            try:
                return tuple(float(token) for token in tokens)
            except ValueError:
                return None
        return None
    # pgvector 注册类型 / 任意序列
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None


def _cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryStore(Protocol):
    """记忆读写；除生命周期方法外，所有方法都严格限定本租户并做归属校验。"""

    def create_fact(self, context, *, content, scope, owner_kind="user", owner_id=None, idempotency_key, embedding) -> MemoryFact: ...

    def supersede_fact(self, context, memory_id) -> MemoryFact: ...

    def list_facts(self, context, *, owner_kind="user", owner_id=None, limit=50, offset=0) -> tuple[list[MemoryFact], int]: ...

    def create_rule(self, context, *, rule_key, content, scope, owner_kind="user", owner_id=None) -> MemoryRule: ...

    def set_profile_key(self, context, *, key, value, owner_kind="user", owner_id=None) -> MemoryProfileKey: ...

    def get_profile(self, context, *, owner_kind="user", owner_id=None) -> dict[str, str]: ...

    def search_facts(self, context, query_embedding, *, scope=None, limit=20) -> list[MemoryFact]: ...

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[MemoryFact]: ...

    def delete_all_for_tenant(self, tenant_id) -> int: ...


def _resolve_owner(context: UserContext, owner_kind, owner_id) -> tuple[MemoryOwnerKind, str]:
    kind = normalize_owner_kind(owner_kind)
    resolved = owner_id or context.user_id
    return kind, resolved


def _fact_allowed(context: UserContext, fact: MemoryFact) -> bool:
    """是否可按访问规则读取该事实（本人或 VIEW_ANY）。"""
    return can_view_any(context) or (
        fact.owner_kind is MemoryOwnerKind.USER and fact.owner_id == context.user_id
    )


class InMemoryMemoryStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], MemoryFact] = {}
        self._rules: dict[tuple[str, str], MemoryRule] = {}
        self._profiles: dict[tuple[str, str, str, str], MemoryProfileKey] = {}
        self._lock = RLock()

    # ------------------------------------------------------------ 事实类

    def create_fact(self, context, *, content, scope, owner_kind="user", owner_id=None, idempotency_key, embedding) -> MemoryFact:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_scope = normalize_scope(scope)
        clean_content = normalize_content(content)
        with self._lock:
            for fact in self._facts.values():
                if (
                    fact.tenant_id == context.tenant_id
                    and fact.owner_kind == kind
                    and fact.owner_id == oid
                    and fact.idempotency_key == str(idempotency_key)
                ):
                    # 幂等：同 (tenant, owner_kind, owner_id, idempotency_key) 已存在 → 返回既有记录。
                    return fact
            fact = MemoryFact(
                tenant_id=context.tenant_id,
                memory_id=new_memory_id(),
                owner_kind=kind,
                owner_id=oid,
                scope=clean_scope,
                content=clean_content,
                embedding=tuple(embedding) if embedding is not None else None,
                idempotency_key=str(idempotency_key),
                created_by=context.user_id,
            )
            self._facts[(context.tenant_id, fact.memory_id)] = fact
            return fact

    def supersede_fact(self, context, memory_id) -> MemoryFact:
        with self._lock:
            fact = self._facts.get((context.tenant_id, str(memory_id)))
            if fact is None:
                raise MemoryNotFound(memory_id)
        ensure_can_view(context, fact.owner_kind, fact.owner_id)
        with self._lock:
            fact = self._facts.get((context.tenant_id, str(memory_id)))
            updated = replace(fact, status=MemoryStatus.SUPERSEDED, superseded_by=fact.memory_id)
            self._facts[(context.tenant_id, fact.memory_id)] = updated
            return updated

    def list_facts(self, context, *, owner_kind="user", owner_id=None, limit=50, offset=0) -> tuple[list[MemoryFact], int]:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        with self._lock:
            matched = [
                fact
                for (tenant_id, _key), fact in self._facts.items()
                if tenant_id == context.tenant_id
                and fact.owner_kind == kind
                and fact.owner_id == oid
                and _fact_allowed(context, fact)
                and fact.status is MemoryStatus.ACTIVE
            ]
        matched.sort(key=lambda item: (item.created_at or datetime.min, item.memory_id), reverse=True)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def search_facts(self, context, query_embedding, *, scope=None, limit=20) -> list[MemoryFact]:
        clean_scope = normalize_scope(scope) if scope is not None else None
        query = tuple(query_embedding)
        with self._lock:
            scored = []
            for (tenant_id, _key), fact in self._facts.items():
                if not (
                    tenant_id == context.tenant_id
                    and fact.status is MemoryStatus.ACTIVE
                    and fact.embedding is not None
                    and _fact_allowed(context, fact)
                ):
                    continue
                if clean_scope is not None and fact.scope != clean_scope:
                    continue
                scored.append((_cosine_similarity(query, fact.embedding), fact))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [fact for _score, fact in scored[: _clamp(limit)]]

    # ------------------------------------------------------------ 规则类

    def create_rule(self, context, *, rule_key, content, scope, owner_kind="user", owner_id=None) -> MemoryRule:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_key = normalize_rule_key(rule_key)
        clean_scope = normalize_scope(scope)
        clean_content = normalize_content(content)
        with self._lock:
            version = 1
            successor_id = None
            for (_tid, _kid), rule in self._rules.items():
                if (
                    rule.tenant_id == context.tenant_id
                    and rule.owner_kind == kind
                    and rule.owner_id == oid
                    and rule.status is MemoryStatus.ACTIVE
                    and rule.rule_key == clean_key
                ):
                    successor_id = rule.memory_id
                    version = rule.version + 1
                    self._rules[(context.tenant_id, rule.memory_id)] = replace(
                        rule, status=MemoryStatus.SUPERSEDED, superseded_by=successor_id
                    )
            new_rule = MemoryRule(
                tenant_id=context.tenant_id,
                memory_id=new_memory_id(),
                owner_kind=kind,
                owner_id=oid,
                scope=clean_scope,
                content=clean_content,
                rule_key=clean_key,
                version=version,
                created_by=context.user_id,
            )
            self._rules[(context.tenant_id, new_rule.memory_id)] = new_rule
            return new_rule

    # ------------------------------------------------------------ 身份类画像

    def set_profile_key(self, context, *, key, value, owner_kind="user", owner_id=None) -> MemoryProfileKey:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_key = normalize_profile_key(key)
        clean_value = normalize_profile_value(value)
        with self._lock:
            present = (context.tenant_id, kind, oid, clean_key) in self._profiles
            count = sum(
                1
                for (tid, k, oid2, _k2) in self._profiles
                if tid == context.tenant_id and k == kind and oid2 == oid
            )
            if not present and count >= MAX_PROFILE_KEYS_PER_OWNER:
                raise MemoryBudgetExceeded("该 owner 的画像键已达上限")
            profile = MemoryProfileKey(
                tenant_id=context.tenant_id,
                owner_kind=kind,
                owner_id=oid,
                profile_key=clean_key,
                value=clean_value,
                created_by=context.user_id,
            )
            # UPSERT：同键覆盖。
            self._profiles[(context.tenant_id, kind, oid, clean_key)] = profile
            return profile

    def get_profile(self, context, *, owner_kind="user", owner_id=None) -> dict[str, str]:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_view(context, kind, oid)
        with self._lock:
            result = {
                p.profile_key: p.value
                for (tid, k, oid2, _k2), p in self._profiles.items()
                if tid == context.tenant_id and k == kind and oid2 == oid
            }
        return result

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[MemoryFact]:
        with self._lock:
            return [
                fact
                for (tid, _key), fact in self._facts.items()
                if tid == tenant_id and fact.status is MemoryStatus.ACTIVE
                and (since is None or (fact.created_at and fact.created_at >= since))
            ]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._lock:
            to_delete = [key for (tid, key) in self._facts if tid == tenant_id]
            for key in to_delete:
                del self._facts[(tenant_id, key)]
            return len(to_delete)


class PostgresMemoryStore:
    """记忆持久化（表 `workbench_memory_facts` / `workbench_memory_rules` / `workbench_memory_profile_keys`，迁移 029）。"""

    _FACT_COLUMNS = "tenant_id, memory_id, owner_kind, owner_id, scope, content, embedding, status, superseded_by, idempotency_key, created_by, created_at"
    _RULE_COLUMNS = "tenant_id, memory_id, owner_kind, owner_id, scope, content, rule_key, status, superseded_by, created_by, created_at"
    _PROFILE_COLUMNS = "tenant_id, owner_kind, owner_id, profile_key, value, created_by, updated_at"

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
    def _hydrate_fact(cls, row: tuple) -> MemoryFact:
        return MemoryFact(
            tenant_id=str(row[0]),
            memory_id=str(row[1]),
            owner_kind=MemoryOwnerKind(str(row[2])),
            owner_id=str(row[3]),
            scope=MemoryScope(str(row[4])),
            content=str(row[5]),
            embedding=_parse_embedding(row[6]),
            status=MemoryStatus(str(row[7])),
            superseded_by=None if row[8] is None else str(row[8]),
            idempotency_key=str(row[9]),
            created_by=None if row[10] is None else str(row[10]),
            created_at=row[11],
        )

    @classmethod
    def _hydrate_rule(cls, row: tuple) -> MemoryRule:
        return MemoryRule(
            tenant_id=str(row[0]),
            memory_id=str(row[1]),
            owner_kind=MemoryOwnerKind(str(row[2])),
            owner_id=str(row[3]),
            scope=MemoryScope(str(row[4])),
            content=str(row[5]),
            rule_key=str(row[6]),
            status=MemoryStatus(str(row[7])),
            superseded_by=None if row[8] is None else str(row[8]),
            created_by=None if row[9] is None else str(row[9]),
            created_at=row[10],
            # version 单独在 SQL 中返回（见 create_rule / 查询时补充），此处默认 1。
            version=1,
        )

    @classmethod
    def _hydrate_profile(cls, row: tuple) -> MemoryProfileKey:
        return MemoryProfileKey(
            tenant_id=str(row[0]),
            owner_kind=MemoryOwnerKind(str(row[1])),
            owner_id=str(row[2]),
            profile_key=str(row[3]),
            value=str(row[4]),
            created_by=None if row[5] is None else str(row[5]),
            updated_at=row[6],
        )

    # ------------------------------------------------------------ 事实类

    def create_fact(self, context, *, content, scope, owner_kind="user", owner_id=None, idempotency_key, embedding) -> MemoryFact:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_scope = normalize_scope(scope)
        clean_content = normalize_content(content)
        idem = str(idempotency_key)
        embed_text = _embedding_to_text(embedding) if embedding is not None else None
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._FACT_COLUMNS} FROM workbench_memory_facts
                        WHERE tenant_id = %s AND owner_kind = %s AND owner_id = %s AND idempotency_key = %s
                        """,
                        (context.tenant_id, kind.value, oid, idem),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        return self._hydrate_fact(existing)  # 幂等：返回既有记录，不重复入库。
                    memory_id = new_memory_id()
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_memory_facts
                            (tenant_id, memory_id, owner_kind, owner_id, scope, content, embedding, idempotency_key, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._FACT_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            memory_id,
                            kind.value,
                            oid,
                            clean_scope.value,
                            clean_content,
                            embed_text,
                            idem,
                            context.user_id,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise MemoryNotFound(memory_id)
        return self._hydrate_fact(row)

    def supersede_fact(self, context, memory_id) -> MemoryFact:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._FACT_COLUMNS} FROM workbench_memory_facts WHERE tenant_id = %s AND memory_id = %s",
                    (context.tenant_id, str(memory_id)),
                )
                row = cursor.fetchone()
        if row is None:
            raise MemoryNotFound(memory_id)
        fact = self._hydrate_fact(row)
        ensure_can_view(context, fact.owner_kind, fact.owner_id)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_memory_facts
                        SET status = %s, superseded_by = %s
                        WHERE tenant_id = %s AND memory_id = %s
                        RETURNING {self._FACT_COLUMNS}
                        """,
                        (MemoryStatus.SUPERSEDED.value, fact.memory_id, context.tenant_id, fact.memory_id),
                    )
                    updated = cursor.fetchone()
        if updated is None:
            raise MemoryNotFound(memory_id)
        return self._hydrate_fact(updated)

    def list_facts(self, context, *, owner_kind="user", owner_id=None, limit=50, offset=0) -> tuple[list[MemoryFact], int]:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        clauses = [
            "tenant_id = %s",
            "owner_kind = %s",
            "owner_id = %s",
            "status = %s",
        ]
        params: list[object] = [context.tenant_id, kind.value, oid, MemoryStatus.ACTIVE.value]
        if not can_view_any(context):
            clauses.append("owner_id = %s")
            params.append(context.user_id)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._FACT_COLUMNS} FROM workbench_memory_facts
                    WHERE {where} ORDER BY created_at DESC, memory_id DESC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_memory_facts WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_fact(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def search_facts(self, context, query_embedding, *, scope=None, limit=20) -> list[MemoryFact]:
        clean_scope = normalize_scope(scope) if scope is not None else None
        query_text = _embedding_to_text(query_embedding)
        clauses = [
            "tenant_id = %s",
            "status = %s",
            "embedding IS NOT NULL",
        ]
        params: list[object] = [context.tenant_id, MemoryStatus.ACTIVE.value]
        if not can_view_any(context):
            clauses.append("owner_id = %s")
            params.append(context.user_id)
        if clean_scope is not None:
            clauses.append("scope = %s")
            params.append(clean_scope.value)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                # 余弦距离（`<=>`）升序即相似度最高；`%s::vector` 传入向量文本。
                # ⚠️ psycopg 按 SQL 中占位符**出现顺序**绑定参数：`%s::vector` 在 SELECT 子句最先出现，
                #    因此 query_text 必须是**第一个**参数，随后才是 WHERE 子句的 params（tenant/status/scope）。
                cursor.execute(
                    f"""
                    SELECT {self._FACT_COLUMNS}, (embedding <=> %s::vector) AS distance
                    FROM workbench_memory_facts
                    WHERE {where} ORDER BY distance ASC LIMIT %s
                    """,
                    (query_text, *params, _clamp(limit)),
                )
                rows = cursor.fetchall()
        facts = []
        for row in rows:
            fact = self._hydrate_fact(row[:12])
            facts.append(fact)
        return facts

    # ------------------------------------------------------------ 规则类

    def create_rule(self, context, *, rule_key, content, scope, owner_kind="user", owner_id=None) -> MemoryRule:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_key = normalize_rule_key(rule_key)
        clean_scope = normalize_scope(scope)
        clean_content = normalize_content(content)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT memory_id, version FROM workbench_memory_rules
                        WHERE tenant_id = %s AND owner_kind = %s AND owner_id = %s AND rule_key = %s AND status = %s
                        ORDER BY version DESC LIMIT 1
                        """,
                        (context.tenant_id, kind.value, oid, clean_key, MemoryStatus.ACTIVE.value),
                    )
                    active = cursor.fetchone()
                    version = (int(active[1]) + 1) if active is not None else 1
                    superseded_by = None
                    if active is not None:
                        superseded_by = new_memory_id()
                        cursor.execute(
                            """
                            UPDATE workbench_memory_rules
                            SET status = %s, superseded_by = %s
                            WHERE tenant_id = %s AND memory_id = %s
                            """,
                            (MemoryStatus.SUPERSEDED.value, superseded_by, context.tenant_id, str(active[0])),
                        )
                    memory_id = superseded_by or new_memory_id()
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_memory_rules
                            (tenant_id, memory_id, owner_kind, owner_id, scope, content, rule_key, version, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._RULE_COLUMNS}, version
                        """,
                        (
                            context.tenant_id,
                            memory_id,
                            kind.value,
                            oid,
                            clean_scope.value,
                            clean_content,
                            clean_key,
                            version,
                            context.user_id,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise MemoryNotFound(memory_id)
        return self._hydrate_rule_with_version(row)

    @classmethod
    def _hydrate_rule_with_version(cls, row: tuple) -> MemoryRule:
        # `_RULE_COLUMNS`(11 列) + `version` = 12 列；version 在索引 11。
        rule = cls._hydrate_rule(row[:11])
        rule = replace(rule, version=int(row[11]))
        return rule

    # ------------------------------------------------------------ 身份类画像

    def set_profile_key(self, context, *, key, value, owner_kind="user", owner_id=None) -> MemoryProfileKey:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_manage(context, kind, oid)
        clean_key = normalize_profile_key(key)
        clean_value = normalize_profile_value(value)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_memory_profile_keys
                            (tenant_id, owner_kind, owner_id, profile_key, value, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, owner_kind, owner_id, profile_key)
                        DO UPDATE SET value = EXCLUDED.value, created_by = EXCLUDED.created_by, updated_at = now()
                        RETURNING {self._PROFILE_COLUMNS}
                        """,
                        (context.tenant_id, kind.value, oid, clean_key, clean_value, context.user_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise MemoryNotFound(clean_key)
        return self._hydrate_profile(row)

    def get_profile(self, context, *, owner_kind="user", owner_id=None) -> dict[str, str]:
        kind, oid = _resolve_owner(context, owner_kind, owner_id)
        ensure_can_view(context, kind, oid)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT profile_key, value FROM workbench_memory_profile_keys
                    WHERE tenant_id = %s AND owner_kind = %s AND owner_id = %s
                    """,
                    (context.tenant_id, kind.value, oid),
                )
                rows = cursor.fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[MemoryFact]:
        clauses = ["tenant_id = %s", "status = %s"]
        params: list[object] = [tenant_id, MemoryStatus.ACTIVE.value]
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._FACT_COLUMNS} FROM workbench_memory_facts WHERE {where}",
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [self._hydrate_fact(row) for row in rows]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_memory_facts WHERE tenant_id = %s", (tenant_id,)
                    )
                    deleted = cursor.rowcount
        return int(deleted)


# re-export 供 import 使用
__all__ = [
    "MemoryStore",
    "InMemoryMemoryStore",
    "PostgresMemoryStore",
    "MAX_LIMIT",
    "EMBEDDING_DIMENSIONS",
]