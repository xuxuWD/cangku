from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

from .domain import PolicyError, UserContext


@dataclass(frozen=True)
class KnowledgeAccessAudit:
    tenant_id: str
    binding_type: str
    binding_key: str
    old_knowledge_base_ids: list[str]
    new_knowledge_base_ids: list[str]
    actor_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class KnowledgeAccessRegistry:
    """Tenant-scoped knowledge-base bindings for roles and digital employees."""

    def __init__(self) -> None:
        self._role_scopes: dict[tuple[str, str], set[str]] = {}
        self._agent_scopes: dict[tuple[str, str], set[str]] = {}
        self._audits: list[KnowledgeAccessAudit] = []
        self._lock = RLock()

    def bind_role(self, context: UserContext, role_key: str, knowledge_base_ids: set[str]) -> None:
        self._ensure_admin(context)
        normalized = self._normalize(role_key, knowledge_base_ids)
        with self._lock:
            old_ids = sorted(self._role_scopes.get((context.tenant_id, role_key), set()))
            self._role_scopes[(context.tenant_id, role_key)] = normalized
            self._audits.append(KnowledgeAccessAudit(context.tenant_id, "role", role_key, old_ids, sorted(normalized), context.user_id))

    def bind_agent(self, context: UserContext, agent_key: str, knowledge_base_ids: set[str]) -> None:
        self._ensure_admin(context)
        normalized = self._normalize(agent_key, knowledge_base_ids)
        with self._lock:
            old_ids = sorted(self._agent_scopes.get((context.tenant_id, agent_key), set()))
            self._agent_scopes[(context.tenant_id, agent_key)] = normalized
            self._audits.append(KnowledgeAccessAudit(context.tenant_id, "agent", agent_key, old_ids, sorted(normalized), context.user_id))

    def resolve(self, context: UserContext, role_key: str, agent_key: str | None = None) -> set[str]:
        with self._lock:
            if agent_key is not None:
                return set(self._agent_scopes.get((context.tenant_id, agent_key), set()))
            return set(self._role_scopes.get((context.tenant_id, role_key), set()))

    def list_audits(self, context: UserContext, *, limit: int = 100) -> list[KnowledgeAccessAudit]:
        self._ensure_admin(context)
        with self._lock:
            return [audit for audit in self._audits if audit.tenant_id == context.tenant_id][-limit:]

    @staticmethod
    def _normalize(key: str, knowledge_base_ids: set[str]) -> set[str]:
        if not key.strip():
            raise PolicyError("岗位或数字员工标识不能为空")
        return {value.strip() for value in knowledge_base_ids if value.strip()}

    @staticmethod
    def _ensure_admin(context: UserContext) -> None:
        if context.role != "super_admin":
            raise PolicyError("只有超级管理员可以调整知识库范围")


class PostgresKnowledgeAccessRegistry:
    """Durable tenant-scoped knowledge bindings using a connection or pool."""

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

    def bind_role(self, context: UserContext, role_key: str, knowledge_base_ids: set[str]) -> None:
        self._bind(context, "role", role_key, knowledge_base_ids)

    def bind_agent(self, context: UserContext, agent_key: str, knowledge_base_ids: set[str]) -> None:
        self._bind(context, "agent", agent_key, knowledge_base_ids)

    def _bind(self, context: UserContext, binding_type: str, binding_key: str, knowledge_base_ids: set[str]) -> None:
        KnowledgeAccessRegistry._ensure_admin(context)
        normalized = KnowledgeAccessRegistry._normalize(binding_key, knowledge_base_ids)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT knowledge_base_id FROM workbench_knowledge_access_bindings WHERE tenant_id = %s AND binding_type = %s AND binding_key = %s",
                        (context.tenant_id, binding_type, binding_key),
                    )
                    old_ids = sorted(str(row[0]) for row in cursor.fetchall())
                    cursor.execute(
                        "DELETE FROM workbench_knowledge_access_bindings WHERE tenant_id = %s AND binding_type = %s AND binding_key = %s",
                        (context.tenant_id, binding_type, binding_key),
                    )
                    for knowledge_base_id in sorted(normalized):
                        cursor.execute(
                            """
                            INSERT INTO workbench_knowledge_access_bindings
                                (tenant_id, binding_type, binding_key, knowledge_base_id, granted_by)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (context.tenant_id, binding_type, binding_key, knowledge_base_id, context.user_id),
                        )
                    cursor.execute(
                        """
                        INSERT INTO workbench_knowledge_access_audits
                            (tenant_id, binding_type, binding_key, old_knowledge_base_ids,
                             new_knowledge_base_ids, actor_id)
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        """,
                        (
                            context.tenant_id, binding_type, binding_key,
                            json.dumps(old_ids), json.dumps(sorted(normalized)), context.user_id,
                        ),
                    )

    def resolve(self, context: UserContext, role_key: str, agent_key: str | None = None) -> set[str]:
        binding_type = "agent" if agent_key is not None else "role"
        binding_key = agent_key if agent_key is not None else role_key
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT knowledge_base_id
                    FROM workbench_knowledge_access_bindings
                    WHERE tenant_id = %s AND binding_type = %s AND binding_key = %s
                    ORDER BY knowledge_base_id
                    """,
                    (context.tenant_id, binding_type, binding_key),
                )
                return {str(row[0]) for row in cursor.fetchall()}

    def list_audits(self, context: UserContext, *, limit: int = 100) -> list[KnowledgeAccessAudit]:
        KnowledgeAccessRegistry._ensure_admin(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tenant_id, binding_type, binding_key, old_knowledge_base_ids,
                           new_knowledge_base_ids, actor_id, occurred_at
                    FROM workbench_knowledge_access_audits
                    WHERE tenant_id = %s
                    ORDER BY occurred_at DESC, id DESC
                    LIMIT %s
                    """,
                    (context.tenant_id, limit),
                )
                return [
                    KnowledgeAccessAudit(
                        tenant_id=str(row[0]), binding_type=str(row[1]), binding_key=str(row[2]),
                        old_knowledge_base_ids=list(row[3] or []), new_knowledge_base_ids=list(row[4] or []),
                        actor_id=str(row[5]),
                        occurred_at=row[6] if isinstance(row[6], datetime) else datetime.fromisoformat(str(row[6])),
                    )
                    for row in cursor.fetchall()
                ]
