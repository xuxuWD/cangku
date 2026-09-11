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


def test_memory_registry_exposes_audit_history_only_to_super_admin() -> None:
    registry = KnowledgeAccessRegistry()
    admin = UserContext("t-1", "admin", "super_admin")
    registry.bind_role(admin, "content-operator", {"kb-content"})

    audits = registry.list_audits(admin)
    assert audits[0].binding_key == "content-operator"
    assert audits[0].new_knowledge_base_ids == ["kb-content"]

    with pytest.raises(PolicyError):
        registry.list_audits(UserContext("t-1", "u-1", "employee"))


def test_binding_keys_are_normalized_on_write_and_lookup() -> None:
    """口径 D5：绑定键与目录标识同口径（去空白 + 转小写），写入与查找都归一一处生效。"""
    registry = KnowledgeAccessRegistry()
    admin = UserContext("t-1", "admin", "super_admin")

    registry.bind_role(admin, "  Content-Operator  ", {"kb-content"})
    registry.bind_agent(admin, "Content-Writer", {"kb-brand"})

    employee = UserContext("t-1", "u-1", "employee")
    assert registry.resolve(employee, "content-operator") == {"kb-content"}
    assert registry.resolve(employee, "CONTENT-OPERATOR") == {"kb-content"}
    assert registry.resolve(employee, "content-operator", "content-writer") == {"kb-brand"}
    # 审计里记录的也是归一键，避免出现同一身份的两种写法
    assert registry.list_audits(admin)[0].binding_key == "content-operator"


@pytest.mark.parametrize("bad_key", ["", "   "])
def test_binding_rejects_blank_key(bad_key: str) -> None:
    registry = KnowledgeAccessRegistry()

    with pytest.raises(PolicyError):
        registry.bind_role(UserContext("t-1", "admin", "super_admin"), bad_key, {"kb-content"})


@pytest.mark.parametrize("bad_key", ["运营岗", "bad key", "-lead", "a" * 65])
def test_binding_rejects_key_outside_directory_format(bad_key: str) -> None:
    """D5 同时收紧格式：绑定键必须与目录标识同格式，否则既无法纳管也无法再改写。"""
    registry = KnowledgeAccessRegistry()

    with pytest.raises(PolicyError):
        registry.bind_role(UserContext("t-1", "admin", "super_admin"), bad_key, {"kb-content"})


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


def test_postgres_registry_normalizes_binding_key() -> None:
    connection = Connection([[('kb-old',)], []])
    registry = PostgresKnowledgeAccessRegistry(connection)

    registry.bind_role(UserContext("t-1", "admin", "super_admin"), "  Content-Operator  ", {"kb-content"})

    statements = connection.cursor_value.statements
    deletes = [params for sql, params in statements if "DELETE FROM workbench_knowledge_access_bindings" in sql]
    inserts = [params for sql, params in statements if "INSERT INTO workbench_knowledge_access_bindings" in sql]
    assert deletes[0][2] == "content-operator"
    assert inserts[0][2] == "content-operator"
    assert inserts[0][3] == "kb-content"


def test_postgres_registry_replaces_role_bindings_transactionally() -> None:
    connection = Connection([[('kb-old',)], [('kb-content',), ('kb-brand',)]])
    registry = PostgresKnowledgeAccessRegistry(connection)
    admin = UserContext("t-1", "admin", "super_admin")

    registry.bind_role(admin, "content-operator", {"kb-new"})
    assert registry.resolve(UserContext("t-1", "u-1", "employee"), "content-operator") == {"kb-content", "kb-brand"}
    assert connection.transactions == 1
    assert any("DELETE FROM workbench_knowledge_access_bindings" in sql for sql, _ in connection.cursor_value.statements)
    assert any("workbench_knowledge_access_audits" in sql for sql, _ in connection.cursor_value.statements)
