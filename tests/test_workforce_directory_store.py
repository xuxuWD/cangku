"""岗位与数字员工目录仓储：标识规范化、租户隔离、权限、归属校验、分页。

先写测试（此时实现尚不存在，收集即红），再写实现使其转绿。
"""

from __future__ import annotations

import pytest

from app.domain import PolicyError, UserContext
from app.workforce.models import (
    DirectoryConflict,
    DirectoryNotFound,
    InvalidDirectoryKey,
    InvalidDirectoryName,
    RoleNotAvailable,
)
from app.workforce.store import (
    InMemoryWorkforceDirectoryStore,
    PostgresWorkforceDirectoryStore,
)

ADMIN = UserContext("t-1", "admin-1", "super_admin")
OTHER_ADMIN = UserContext("t-2", "admin-2", "super_admin")
CEO = UserContext("t-1", "ceo-1", "ceo")


# ------------------------------------------------------------ 标识与名称规范化


def test_create_role_normalizes_key_and_scopes_tenant() -> None:
    store = InMemoryWorkforceDirectoryStore()

    role = store.create_role(ADMIN, role_key="  Content-Operator  ", name=" 自媒体运营岗 ")

    assert role.role_key == "content-operator"
    assert role.name == "自媒体运营岗"
    assert role.status == "active"
    assert store.list_roles(ADMIN)[0] == [role]
    # 他租户看不到
    assert store.list_roles(OTHER_ADMIN) == ([], 0)


@pytest.mark.parametrize("bad_key", ["", "   ", "运营岗", "bad key", "-lead", "a" * 65])
def test_create_role_rejects_invalid_key(bad_key: str) -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(InvalidDirectoryKey):
        store.create_role(ADMIN, role_key=bad_key, name="岗位")


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 61])
def test_create_role_requires_valid_name(bad_name: str) -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(InvalidDirectoryName):
        store.create_role(ADMIN, role_key="content-operator", name=bad_name)


def test_create_role_conflicts_on_duplicate_key() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")

    with pytest.raises(DirectoryConflict):
        store.create_role(ADMIN, role_key="Content-Operator", name="重复岗位")


def test_directory_requires_super_admin() -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(PolicyError):
        store.create_role(CEO, role_key="content-operator", name="岗位")
    with pytest.raises(PolicyError):
        store.list_roles(CEO)
    with pytest.raises(PolicyError):
        store.known_keys(CEO)


# ------------------------------------------------------------ 岗位读写


def test_update_role_applies_partial_changes() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")

    renamed = store.update_role(ADMIN, "content-operator", name="内容运营岗")
    assert renamed.name == "内容运营岗"

    disabled = store.update_role(ADMIN, "content-operator", status="disabled")
    assert disabled.status == "disabled"
    # 未传的字段保持原值，不被清空
    assert disabled.name == "内容运营岗"
    assert disabled.description == ""


def test_update_role_missing_key_raises_not_found() -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(DirectoryNotFound):
        store.update_role(ADMIN, "nobody", name="岗位")


# ------------------------------------------------------------ 数字员工读写


def test_create_employee_requires_existing_active_role() -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(RoleNotAvailable):
        store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")

    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.update_role(ADMIN, "content-operator", status="disabled")
    with pytest.raises(RoleNotAvailable):
        store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")


def test_create_employee_conflicts_on_duplicate_key() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")

    with pytest.raises(DirectoryConflict):
        store.create_employee(ADMIN, agent_key="content-writer", name="重复员工", role_key="content-operator")


def test_update_employee_can_move_role_but_rejects_unavailable_target() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_role(ADMIN, role_key="geo-operator", name="GEO 运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")

    moved = store.update_employee(ADMIN, "content-writer", role_key="geo-operator")
    assert moved.role_key == "geo-operator"

    store.update_role(ADMIN, "geo-operator", status="disabled")
    with pytest.raises(RoleNotAvailable):
        store.update_employee(ADMIN, "content-writer", role_key="geo-operator")


def test_update_employee_missing_key_raises_not_found() -> None:
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(DirectoryNotFound):
        store.update_employee(ADMIN, "nobody", name="员工")


# ------------------------------------------------------------ 列表与分页


def test_list_roles_paginates_with_total() -> None:
    store = InMemoryWorkforceDirectoryStore()
    for index in range(3):
        store.create_role(ADMIN, role_key=f"role-{index}", name=f"岗位 {index}")

    page, total = store.list_roles(ADMIN, limit=2, offset=0)
    assert total == 3
    assert [item.role_key for item in page] == ["role-0", "role-1"]

    page, total = store.list_roles(ADMIN, limit=2, offset=2)
    assert total == 3
    assert [item.role_key for item in page] == ["role-2"]


def test_list_employees_filters_by_role_and_status() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_role(ADMIN, role_key="geo-operator", name="GEO 运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")
    store.create_employee(ADMIN, agent_key="geo-analyst", name="GEO 分析", role_key="geo-operator")
    store.update_employee(ADMIN, "geo-analyst", status="disabled")

    all_items, total = store.list_employees(ADMIN)
    assert total == 2
    assert [item.agent_key for item in all_items] == ["content-writer", "geo-analyst"]

    only_active, total = store.list_employees(ADMIN, status="active")
    assert total == 1
    assert [item.agent_key for item in only_active] == ["content-writer"]

    by_role, total = store.list_employees(ADMIN, role_key="geo-operator")
    assert total == 1
    assert [item.agent_key for item in by_role] == ["geo-analyst"]


def test_known_keys_includes_disabled_and_scopes_tenant() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")
    store.update_employee(ADMIN, "content-writer", status="disabled")
    store.create_role(OTHER_ADMIN, role_key="other-role", name="他租户岗位")

    role_keys, agent_keys = store.known_keys(ADMIN)

    assert role_keys == {"content-operator"}
    assert agent_keys == {"content-writer"}


# ------------------------------------------------------------ PostgreSQL 实现


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple | None]] = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return self.rows.pop(0)

    def fetchone(self):
        return self.rows.pop(0)


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_postgres_create_role_inserts_with_conflict_guard() -> None:
    row = ("t-1", "content-operator", "自媒体运营岗", "", "active", "admin-1", None, None)
    connection = RecordingConnection([row])

    role = PostgresWorkforceDirectoryStore(connection).create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")

    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO workbench_job_roles" in statement
    assert "ON CONFLICT (tenant_id, role_key) DO NOTHING" in statement
    assert "RETURNING" in statement
    assert params == ("t-1", "content-operator", "自媒体运营岗", "", "active", "admin-1")
    assert role.role_key == "content-operator"


def test_postgres_create_role_reports_conflict_when_no_row_returned() -> None:
    connection = RecordingConnection([None])

    with pytest.raises(DirectoryConflict):
        PostgresWorkforceDirectoryStore(connection).create_role(ADMIN, role_key="content-operator", name="岗位")


def test_postgres_update_role_uses_coalesce_and_detects_missing_row() -> None:
    connection = RecordingConnection([None])
    store = PostgresWorkforceDirectoryStore(connection)

    with pytest.raises(DirectoryNotFound):
        store.update_role(ADMIN, "content-operator", name="新名字")

    statement, params = connection.cursor_instance.statements[0]
    assert "UPDATE workbench_job_roles" in statement
    assert "COALESCE(%s, name)" in statement
    assert "updated_at = now()" in statement
    assert "WHERE tenant_id = %s AND role_key = %s" in statement
    assert params == ("新名字", None, None, "t-1", "content-operator")


def test_postgres_create_employee_checks_role_status_before_insert() -> None:
    connection = RecordingConnection([("disabled",), None])
    store = PostgresWorkforceDirectoryStore(connection)

    with pytest.raises(RoleNotAvailable):
        store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")

    statement, params = connection.cursor_instance.statements[0]
    assert "SELECT status FROM workbench_job_roles" in statement
    assert params == ("t-1", "content-operator")
    # 岗位不可用时不得继续写员工
    assert len(connection.cursor_instance.statements) == 1


def test_postgres_list_employees_applies_filters_and_count() -> None:
    row = ("t-1", "content-writer", "内容创作", "", "content-operator", "active", "admin-1", None, None)
    # 假连接按真实 psycopg 的形状返回：fetchall → 行列表，fetchone → 单个行元组。
    connection = RecordingConnection([[row], (1,)])

    items, total = PostgresWorkforceDirectoryStore(connection).list_employees(
        ADMIN, role_key="content-operator", status="active", limit=10, offset=0
    )

    statements = connection.cursor_instance.statements
    assert "FROM workbench_digital_employees" in statements[0][0]
    assert "AND role_key = %s" in statements[0][0]
    assert "AND status = %s" in statements[0][0]
    assert "LIMIT %s OFFSET %s" in statements[0][0]
    assert statements[0][1] == ("t-1", "content-operator", "active", 10, 0)
    assert "SELECT COUNT(*) FROM workbench_digital_employees" in statements[1][0]
    assert total == 1
    assert [item.agent_key for item in items] == ["content-writer"]


def test_postgres_known_keys_queries_both_tables_scoped_by_tenant() -> None:
    connection = RecordingConnection([[("content-operator",)], [("content-writer",)]])

    role_keys, agent_keys = PostgresWorkforceDirectoryStore(connection).known_keys(ADMIN)

    statements = connection.cursor_instance.statements
    assert "SELECT role_key FROM workbench_job_roles" in statements[0][0]
    assert statements[0][1] == ("t-1",)
    assert "SELECT agent_key FROM workbench_digital_employees" in statements[1][0]
    assert statements[1][1] == ("t-1",)
    assert role_keys == {"content-operator"}
    assert agent_keys == {"content-writer"}


# ------------------------------------------------------------ 可用性判定（阶段 2 写路径闸门）


def test_is_active_reflects_status_format_and_tenant() -> None:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")

    # 归一后命中（与 D5 同口径），非法格式按「不可用」处理而不是抛异常
    assert store.role_is_active(ADMIN, "Content-Operator") is True
    assert store.role_is_active(ADMIN, "nobody") is False
    assert store.role_is_active(ADMIN, "运营岗") is False
    assert store.role_is_active(OTHER_ADMIN, "content-operator") is False

    assert store.agent_is_active(ADMIN, "Content-Writer") is True
    assert store.agent_is_active(ADMIN, "geo-analyst") is False

    store.update_role(ADMIN, "content-operator", status="disabled")
    assert store.role_is_active(ADMIN, "content-operator") is False
    # 岗位停用连带约束其下属员工（口径收严：员工不能脱离岗位独立存在）
    assert store.agent_is_active(ADMIN, "content-writer") is False

    with pytest.raises(PolicyError):
        store.role_is_active(CEO, "content-operator")


def test_postgres_is_active_reads_status_row_normalized() -> None:
    connection = RecordingConnection([("active",)])
    store = PostgresWorkforceDirectoryStore(connection)

    assert store.role_is_active(ADMIN, "  Content-Operator  ") is True
    statement, params = connection.cursor_instance.statements[0]
    assert "SELECT status FROM workbench_job_roles" in statement
    assert params == ("t-1", "content-operator")

    assert PostgresWorkforceDirectoryStore(RecordingConnection([None])).role_is_active(ADMIN, "nobody") is False


def test_postgres_agent_is_active_joins_own_and_role_status() -> None:
    """员工可用 = 员工自身 active 且所属岗位 active；一次 JOIN 查完。"""
    connection = RecordingConnection([("active", "disabled")])
    store = PostgresWorkforceDirectoryStore(connection)

    assert store.agent_is_active(ADMIN, "Content-Writer") is False
    statement, params = connection.cursor_instance.statements[0]
    assert "LEFT JOIN workbench_job_roles" in statement
    assert params == ("t-1", "content-writer")

    assert PostgresWorkforceDirectoryStore(RecordingConnection([("active", "active")])).agent_is_active(ADMIN, "content-writer") is True
    assert PostgresWorkforceDirectoryStore(RecordingConnection([("disabled", "active")])).agent_is_active(ADMIN, "content-writer") is False
    assert PostgresWorkforceDirectoryStore(RecordingConnection([None])).agent_is_active(ADMIN, "nobody") is False
    # 所属岗位缺失时 LEFT JOIN 出 NULL，同样按不可用处理
    assert PostgresWorkforceDirectoryStore(RecordingConnection([("active", None)])).agent_is_active(ADMIN, "content-writer") is False
