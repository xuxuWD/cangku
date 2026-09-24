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
    InvalidShare,
    RoleNotAvailable,
)
from app.workforce.store import (
    InMemoryWorkforceDirectoryStore,
    PostgresWorkforceDirectoryStore,
)

ADMIN = UserContext("t-1", "admin-1", "super_admin")
OTHER_ADMIN = UserContext("t-2", "admin-2", "super_admin")
CEO = UserContext("t-1", "ceo-1", "ceo")
OWNER_EMPLOYEE = UserContext("t-1", "u-owner", "employee")
OTHER_EMPLOYEE = UserContext("t-1", "u-other", "employee")


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


def test_directory_management_requires_super_admin() -> None:
    """管理档仍仅超管；**读档**（`list_roles`）自 2026-09-24 闸门拆分起对登录用户放开。

    口径源：`docs/contracts/gate-split-review-2026-09-24.md`（V1=C）。
    """
    store = InMemoryWorkforceDirectoryStore()

    with pytest.raises(PolicyError):
        store.create_role(CEO, role_key="content-operator", name="岗位")
    # ⚠️ 行为按设计变更：读档放开 ⇒ 登录用户不再被拒（岗位列表只返回 active，此处空库 ⇒ 空结果）。
    assert store.list_roles(CEO) == ([], 0)
    # 跨模块只读方法（V3=A）**不动**
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


# ------------------------------------------------------------ B2 归属与共享（迁移 045）


def _seed_owned_store() -> InMemoryWorkforceDirectoryStore:
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_employee(
        ADMIN,
        agent_key="content-writer",
        name="内容创作",
        role_key="content-operator",
        owner_user_id="u-owner",
    )
    return store


def test_employee_creation_resolves_owner_server_side() -> None:
    """归属人**由服务端决定**（一切输入默认不可信）：非管理员恒为自己，`super_admin` 可指定。"""
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")

    # 员工侧：请求体指定他人 ⇒ 被服务端覆盖回自己
    mine = store.create_employee(
        OWNER_EMPLOYEE, agent_key="mine", name="我的", role_key="content-operator", owner_user_id="u-other"
    )
    assert mine.owner_user_id == "u-owner"
    assert store.list_employees(OWNER_EMPLOYEE)[0] == [mine]
    assert store.list_employees(OTHER_EMPLOYEE) == ([], 0)

    # 管理员：可指定归属人
    theirs = store.create_employee(
        ADMIN, agent_key="theirs", name="他的", role_key="content-operator", owner_user_id="u-other"
    )
    assert theirs.owner_user_id == "u-other"
    # 管理员不指定 ⇒ 归自己
    admin_own = store.create_employee(ADMIN, agent_key="admin-own", name="管理员的", role_key="content-operator")
    assert admin_own.owner_user_id == "admin-1"
    # `super_admin` 是管理视角：看得到本租户全部
    assert {item.agent_key for item in store.list_employees(ADMIN)[0]} == {"mine", "theirs", "admin-own"}


def test_shares_extend_visibility_and_are_owner_scoped() -> None:
    store = _seed_owned_store()

    share = store.add_share(OWNER_EMPLOYEE, "content-writer", grantee_user_id="u-sharee", permission="use")
    assert (share.grantee_user_id, share.permission, share.granted_by) == ("u-sharee", "use", "u-owner")

    # 被授权人可见；无关同事不可见
    assert [
        item.agent_key
        for item in store.list_employees(UserContext("t-1", "u-sharee", "employee"))[0]
    ] == ["content-writer"]
    assert store.list_employees(OTHER_EMPLOYEE) == ([], 0)

    # 仅归属人可管理：他人 / 跨租户一律 404（不泄露存在性）
    with pytest.raises(DirectoryNotFound):
        store.add_share(OTHER_EMPLOYEE, "content-writer", grantee_user_id="u-x", permission="read")
    with pytest.raises(DirectoryNotFound):
        store.add_share(
            UserContext("t-2", "u-owner", "employee"), "content-writer", grantee_user_id="u-x", permission="read"
        )
    with pytest.raises(DirectoryNotFound):
        store.list_shares(OTHER_EMPLOYEE, "content-writer")
    with pytest.raises(DirectoryNotFound):
        store.remove_share(OTHER_EMPLOYEE, "content-writer", "u-sharee")
    # `super_admin` 亦不例外（共享归归属人管；管理员处置员工走 update_employee）
    with pytest.raises(DirectoryNotFound):
        store.add_share(ADMIN, "content-writer", grantee_user_id="u-x", permission="read")

    items, total = store.list_shares(OWNER_EMPLOYEE, "content-writer")
    assert (total, [item.grantee_user_id for item in items]) == (1, ["u-sharee"])

    # 幂等：复删 / 本就不是共享者 ⇒ False（调用方据此不重复写审计）
    assert store.remove_share(OWNER_EMPLOYEE, "content-writer", "u-nobody") is False
    assert store.remove_share(OWNER_EMPLOYEE, "content-writer", "u-sharee") is True
    assert store.remove_share(OWNER_EMPLOYEE, "content-writer", "u-sharee") is False
    assert store.list_shares(OWNER_EMPLOYEE, "content-writer")[1] == 0


@pytest.mark.parametrize("permission", ["admin", "", "READ", " read", "use,read"])
def test_add_share_rejects_invalid_permission(permission: str) -> None:
    """档位**逐字**匹配（与路由层 `pattern` 同口径，不做 strip / lower 归一）。"""
    store = _seed_owned_store()

    with pytest.raises(InvalidShare):
        store.add_share(OWNER_EMPLOYEE, "content-writer", grantee_user_id="u-x", permission=permission)


def test_add_share_rejects_blank_grantee() -> None:
    store = _seed_owned_store()

    with pytest.raises(InvalidShare):
        store.add_share(OWNER_EMPLOYEE, "content-writer", grantee_user_id="   ", permission="read")


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
    # 迁移 045 起员工读模型末尾追加 `owner_user_id` / `visibility`（**追加在末尾**，既有列序号不变）。
    row = ("t-1", "content-writer", "内容创作", "", "content-operator", "active", "admin-1", None, None, "admin-1", "private")
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
    # `super_admin` 是管理视角 ⇒ **不加**可见性过滤（故无额外参数）
    assert statements[0][1] == ("t-1", "content-operator", "active", 10, 0)
    assert "SELECT COUNT(*) FROM workbench_digital_employees" in statements[1][0]
    assert total == 1
    assert [item.agent_key for item in items] == ["content-writer"]
    assert items[0].owner_user_id == "admin-1"
    assert items[0].visibility == "private"


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


def test_postgres_list_employees_pushes_visibility_filter_into_sql() -> None:
    """非 `super_admin` 的可见性过滤**下推 SQL**（不是取全量再筛）——两套实现同口径。"""
    row = ("t-1", "content-writer", "内容创作", "", "content-operator", "active", "admin-1", None, None, "u-owner", "private")
    connection = RecordingConnection([[row], (1,)])

    items, total = PostgresWorkforceDirectoryStore(connection).list_employees(OWNER_EMPLOYEE, limit=10)

    statement, params = connection.cursor_instance.statements[0]
    assert "owner_user_id = %s" in statement
    assert "workbench_employee_shares" in statement
    # 归属人参数出现两次（owner 判定 + 共享子查询的 grantee 判定），租户外层参数一次
    assert params == ("t-1", "u-owner", "t-1", "u-owner", 10, 0)
    assert total == 1
    assert [item.agent_key for item in items] == ["content-writer"]
    assert items[0].owner_user_id == "u-owner"


def test_postgres_create_employee_writes_server_resolved_owner() -> None:
    """员工侧创建：`owner_user_id` 由服务端置为调用者本人并**写入该列**。"""
    row = ("t-1", "content-writer", "内容创作", "", "content-operator", "active", "u-owner", None, None, "u-owner", "private")
    connection = RecordingConnection([("active",), row])

    employee = PostgresWorkforceDirectoryStore(connection).create_employee(
        OWNER_EMPLOYEE, agent_key="content-writer", name="内容创作", role_key="content-operator"
    )

    statement, params = connection.cursor_instance.statements[1]
    assert "INSERT INTO workbench_digital_employees" in statement
    assert "owner_user_id" in statement.split("VALUES")[0]
    assert params == ("t-1", "content-writer", "内容创作", "", "content-operator", "active", "u-owner", "u-owner")
    assert employee.owner_user_id == "u-owner"


def test_postgres_agent_config_columns_map_after_trunk_columns() -> None:
    """迁移 045 起配置列**整体后移两位**（`owner_user_id` / `visibility` 插在员工列之后）。

    用一条满列行钉住 `_hydrate_agent_config` 的下标 —— 错位会**静默串字段**
    （把提示词读成模型键之类），这类错在假连接测试之外很难被发现。
    """
    row = (
        "t-1", "content-writer", "内容创作", "", "content-operator", "active", "admin-1", None, None,
        "u-owner", "private",
        "提示词", "deepseek-chat", 0.5, ["knowledge_search"], {"short_term_enabled": True},
        "full_auto", "critical", 30, 1234,
    )
    connection = RecordingConnection([row])

    employee = PostgresWorkforceDirectoryStore(connection).read_agent_config(ADMIN, "content-writer")

    statement, params = connection.cursor_instance.statements[0]
    assert "owner_user_id, visibility, system_prompt" in statement
    assert params == ("t-1", "content-writer")
    assert employee.owner_user_id == "u-owner"
    assert employee.visibility == "private"
    assert employee.system_prompt == "提示词"
    assert employee.model_key == "deepseek-chat"
    assert employee.temperature == 0.5
    assert employee.tool_allowlist == ("knowledge_search",)
    assert employee.memory_policy == {"short_term_enabled": True}
    assert employee.autonomy_level == "full_auto"
    assert employee.risk_threshold == "critical"
    assert employee.approval_timeout_minutes == 30
    assert employee.daily_budget_cents == 1234


def test_postgres_share_management_requires_ownership() -> None:
    """PG 侧同口径：他人 / 跨租户 `DirectoryNotFound`（不泄露存在性），查的是 `owner_user_id`。"""
    connection = RecordingConnection([("u-someone-else",)])
    store = PostgresWorkforceDirectoryStore(connection)

    with pytest.raises(DirectoryNotFound):
        store.add_share(OWNER_EMPLOYEE, "content-writer", grantee_user_id="u-x", permission="read")

    assert "SELECT owner_user_id FROM workbench_digital_employees" in connection.cursor_instance.statements[0][0]
    # 归属人不符 ⇒ 不得继续写共享行
    assert len(connection.cursor_instance.statements) == 1


# ------------------------------------------------------------ 可见性 / 配置读档（2026-09-24 修复）


def _agent_config_row(owner: str):
    return (
        "t-1", "content-writer", "内容创作", "", "content-operator", "active", "admin-1", None, None,
        owner, "private",
        "提示词", "deepseek-chat", 0.5, ["knowledge_search"], {"short_term_enabled": True},
        "full_auto", "critical", 30, 1234,
    )


def test_postgres_config_read_allows_read_share() -> None:
    """`read` 档读 config：PG 侧也要查共享表并放行（与内存实现同口径）。"""
    connection = RecordingConnection([_agent_config_row("u-owner"), ("read",)])
    reader = UserContext("t-1", "u-read", "employee")

    employee = PostgresWorkforceDirectoryStore(connection).read_agent_config(reader, "content-writer")

    assert employee.agent_key == "content-writer"
    statements = connection.cursor_instance.statements
    assert "SELECT permission FROM workbench_employee_shares" in statements[1][0]
    assert statements[1][1] == ("t-1", "content-writer", "u-read")


def test_postgres_config_read_rejects_use_share() -> None:
    """`use` 档**不可读** config（V4=A）——两档必须真的不同。"""
    connection = RecordingConnection([_agent_config_row("u-owner"), ("use",)])
    user = UserContext("t-1", "u-use", "employee")

    with pytest.raises(PolicyError):
        PostgresWorkforceDirectoryStore(connection).read_agent_config(user, "content-writer")


def test_postgres_visible_agent_keys_owner_union_shares() -> None:
    """`visible_agent_keys` 下推 SQL（`owner ∪ shares`）；`super_admin` 不受限且不查库。"""
    connection = RecordingConnection([[("a-owner",), ("shared-agent",)]])

    keys = PostgresWorkforceDirectoryStore(connection).visible_agent_keys(OWNER_EMPLOYEE)

    assert keys == {"a-owner", "shared-agent"}
    statement, params = connection.cursor_instance.statements[0]
    assert "workbench_employee_shares" in statement
    assert params == ("t-1", "u-owner", "t-1", "u-owner")

    unrestricted = RecordingConnection([])
    assert PostgresWorkforceDirectoryStore(unrestricted).visible_agent_keys(ADMIN) is None
    assert unrestricted.cursor_instance.statements == []


@pytest.mark.parametrize("role", ["employee", "department_lead", "ceo", "super_admin"])
def test_directory_read_roles_are_the_four_business_roles(role: str) -> None:
    """读档 / 创建档白名单 = 四档业务角色（施工材料 §2）；`super_admin` 亦可读。"""
    store = InMemoryWorkforceDirectoryStore()

    assert store.list_roles(UserContext("t-1", f"u-{role}", role)) == ([], 0)


def test_customer_admin_is_excluded_from_directory_read_and_create() -> None:
    """`customer_admin` 不在目录面（读 / 创建）白名单（2026-09-24 修复）。

    依据：`permission-matrix.md` §3「数字员工」四行 `customer_admin` 一律 ❌
    + 施工材料 §2「四档角色」。
    """
    store = InMemoryWorkforceDirectoryStore()
    ca = UserContext("t-1", "ca-1", "customer_admin")

    with pytest.raises(PolicyError):
        store.list_roles(ca)
    with pytest.raises(PolicyError):
        store.list_employees(ca)
    with pytest.raises(PolicyError):
        store.create_employee(ca, agent_key="ca-agent", name="越权", role_key="content-operator")
    # 管理档 / 跨模块只读方法本就不放行（逐字不变）
    with pytest.raises(PolicyError):
        store.known_keys(ca)


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


# ------------------------------------------------------------ 治理读取的岗位停用连带


def test_read_agent_governance_follows_role_disabled_cascade() -> None:
    """岗位停用连带：岗位停用后，其下属员工的治理读取同样返回 `None`（口径同 `agent_is_active`）。

    §15 #11 / 段二 §1.4：`agent_key` 路由到真实执行前须「存在且启用」，实施口径 =
    写路径闸门 `ensure_agent_binding_available`（员工 active **且** 岗位 active），
    但**不要求 `super_admin`**（执行入口操作者可以是任意角色）。
    """
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    store.create_employee(ADMIN, agent_key="content-writer", name="内容创作", role_key="content-operator")
    store.update_agent_config(
        ADMIN, "content-writer", autonomy_level="full_auto", risk_threshold="critical"
    )

    assert store.read_agent_governance(ADMIN, "content-writer") == ("full_auto", "critical")
    # 非管理角色同样可读（不要求 super_admin），租户隔离仍生效
    assert store.read_agent_governance(CEO, "content-writer") == ("full_auto", "critical")

    store.update_role(ADMIN, "content-operator", status="disabled")

    assert store.read_agent_governance(ADMIN, "content-writer") is None
    assert store.agent_is_active(ADMIN, "content-writer") is False  # 两条读路径口径一致


def test_postgres_read_agent_governance_joins_role_status() -> None:
    """PG 仓储：治理读取必须 JOIN 岗位并同时要求员工与岗位 `active`（无 `_ensure_admin` 门槛）。"""
    connection = RecordingConnection([("full_auto", "critical")])
    store = PostgresWorkforceDirectoryStore(connection)

    assert store.read_agent_governance(CEO, "Content-Writer") == ("full_auto", "critical")
    statement, params = connection.cursor_instance.statements[0]
    assert "JOIN workbench_job_roles" in statement
    assert "employee.status = 'active' AND role.status = 'active'" in statement
    assert params == ("t-1", "content-writer")

    assert PostgresWorkforceDirectoryStore(RecordingConnection([None])).read_agent_governance(
        ADMIN, "content-writer"
    ) is None
