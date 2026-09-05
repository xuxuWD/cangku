import pytest

from app.domain import PolicyError, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry


def test_admin_can_bind_role_and_agent_knowledge_scopes() -> None:
    registry = KnowledgeAccessRegistry()
    admin = UserContext("t-1", "admin", "super_admin")

    registry.bind_role(admin, "content-operator", {"kb-content", "kb-brand"})
    registry.bind_agent(admin, "content-writer", {"kb-content"})

    assert registry.resolve(UserContext("t-1", "u-1", "employee"), "content-operator") == {"kb-content", "kb-brand"}
    assert registry.resolve(UserContext("t-1", "u-1", "employee"), "content-operator", "content-writer") == {"kb-content"}


def test_scope_changes_are_tenant_scoped_and_default_to_empty() -> None:
    registry = KnowledgeAccessRegistry()
    admin = UserContext("t-1", "admin", "super_admin")
    registry.bind_role(admin, "content-operator", {"kb-content"})

    assert registry.resolve(UserContext("t-2", "u-2", "employee"), "content-operator") == set()
    assert registry.resolve(UserContext("t-1", "u-1", "employee"), "unknown-role") == set()

    with pytest.raises(PolicyError):
        registry.bind_role(UserContext("t-1", "lead", "department_lead"), "content-operator", {"kb-other"})
