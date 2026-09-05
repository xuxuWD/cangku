import pytest

from app.domain import PolicyError, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.knowledge_policy import PostgresKnowledgeAccessRegistry


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


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute(self, sql, params=()): self.statements.append((sql, params))
    def fetchall(self): return self.rows.pop(0)


class Connection:
    def __init__(self, rows):
        self.cursor_value = Cursor(rows)
        self.transactions = 0

    def transaction(self):
        class Tx:
            def __enter__(_self): self.transactions += 1
            def __exit__(_self, *_args): return False
        return Tx()

    def cursor(self): return self.cursor_value


def test_postgres_registry_replaces_role_bindings_transactionally() -> None:
    connection = Connection([[('kb-old',)], [('kb-content',), ('kb-brand',)]])
    registry = PostgresKnowledgeAccessRegistry(connection)
    admin = UserContext("t-1", "admin", "super_admin")

    registry.bind_role(admin, "content-operator", {"kb-new"})
    assert registry.resolve(UserContext("t-1", "u-1", "employee"), "content-operator") == {"kb-content", "kb-brand"}
    assert connection.transactions == 1
    assert any("DELETE FROM workbench_knowledge_access_bindings" in sql for sql, _ in connection.cursor_value.statements)
    assert any("workbench_knowledge_access_audits" in sql for sql, _ in connection.cursor_value.statements)
