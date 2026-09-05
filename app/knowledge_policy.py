from __future__ import annotations

from threading import RLock

from .domain import PolicyError, UserContext


class KnowledgeAccessRegistry:
    """Tenant-scoped knowledge-base bindings for roles and digital employees."""

    def __init__(self) -> None:
        self._role_scopes: dict[tuple[str, str], set[str]] = {}
        self._agent_scopes: dict[tuple[str, str], set[str]] = {}
        self._lock = RLock()

    def bind_role(self, context: UserContext, role_key: str, knowledge_base_ids: set[str]) -> None:
        self._ensure_admin(context)
        normalized = self._normalize(role_key, knowledge_base_ids)
        with self._lock:
            self._role_scopes[(context.tenant_id, role_key)] = normalized

    def bind_agent(self, context: UserContext, agent_key: str, knowledge_base_ids: set[str]) -> None:
        self._ensure_admin(context)
        normalized = self._normalize(agent_key, knowledge_base_ids)
        with self._lock:
            self._agent_scopes[(context.tenant_id, agent_key)] = normalized

    def resolve(self, context: UserContext, role_key: str, agent_key: str | None = None) -> set[str]:
        with self._lock:
            if agent_key is not None:
                return set(self._agent_scopes.get((context.tenant_id, agent_key), set()))
            return set(self._role_scopes.get((context.tenant_id, role_key), set()))

    @staticmethod
    def _normalize(key: str, knowledge_base_ids: set[str]) -> set[str]:
        if not key.strip():
            raise PolicyError("岗位或数字员工标识不能为空")
        return {value.strip() for value in knowledge_base_ids if value.strip()}

    @staticmethod
    def _ensure_admin(context: UserContext) -> None:
        if context.role != "super_admin":
            raise PolicyError("只有超级管理员可以调整知识库范围")
