"""OP-01 权限闸门拆分 —— **真库**回归（迁移 045）。

**为什么需要本文件**：闸门拆分新增的「`owner ∪ shares` 下推 SQL」与
`workbench_employee_shares` 读写，此前**只由假连接 `RecordingConnection` 做文本/参数级断言**
（见 `tests/test_workforce_directory_store.py` 的 `test_postgres_*`）。
文本级断言证明不了：SQL 在真 PostgreSQL 上跑得通、外键真的存在、`ON CONFLICT` 真的按预期走。
⇒ 本文件补上这一段，**是评审材料 §九 第 1 条「真 PG 路径未执行」的收口**。

口径（沿用 `tests/test_skills_postgres.py` 先例）：
  - DSN 从 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**；
  - 目标库须**已完成全部迁移（含 045）**；本文件**不建表、不迁移**；
  - 只操作 `TENANT` 这一个租户的数据，用例前后自清。
"""

from __future__ import annotations

import os

import pytest

from app.domain import PolicyError, UserContext
from app.workforce.store import PostgresWorkforceDirectoryStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring）",
)

TENANT = "test-op01-pg"
OTHER_TENANT = "test-op01-pg-other"

ADMIN = UserContext(TENANT, "acct-op01-admin", "super_admin")
OWNER = UserContext(TENANT, "acct-op01-owner", "employee")
MATE = UserContext(TENANT, "acct-op01-mate", "employee")
STRANGER = UserContext(TENANT, "acct-op01-stranger", "employee")
CUSTOMER_ADMIN = UserContext(TENANT, "acct-op01-custadmin", "customer_admin")
CROSS_TENANT = UserContext(OTHER_TENANT, "acct-op01-x", "employee")

ROLE_KEY = "op01-role"


@pytest.fixture()
def store():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    admin_store = PostgresWorkforceDirectoryStore(connection)
    admin_store.create_role(ADMIN, role_key=ROLE_KEY, name="OP01 岗")
    try:
        yield PostgresWorkforceDirectoryStore(connection)
    finally:
        _purge(connection)
        connection.close()


def _purge(connection) -> None:
    """自清：**先子表后主表**（shares 有指向 employees 的外键）。"""
    with connection.cursor() as cursor:
        for tenant in (TENANT, OTHER_TENANT):
            cursor.execute("DELETE FROM workbench_employee_shares WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_digital_employees WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_job_roles WHERE tenant_id = %s", (tenant,))


# --------------------------------------------------------------------- 归属与可见性


def test_employee_creation_sets_self_as_owner_on_real_db(store) -> None:
    """真库：员工侧创建 ⇒ `owner_user_id` 落库为调用者本人，且 `visibility` 默认最保守。"""
    created = store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)

    assert created.owner_user_id == OWNER.user_id
    assert created.visibility == "private"

    # 回读确认**真的落库了**（不是只在返回值里）
    reread = store.read_agent_owner(OWNER, "a-owner")
    assert reread == OWNER.user_id


def test_list_employees_filters_by_owner_on_real_db(store) -> None:
    """真库：`list_employees` 的 `owner ∪ shares` 下推 SQL 真的过滤（不是取全量再筛）。"""
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)
    store.create_employee(MATE, agent_key="a-mate", name="乙", role_key=ROLE_KEY)

    mine, total = store.list_employees(OWNER)
    assert [e.agent_key for e in mine] == ["a-owner"]
    assert total == 1, "total 必须是**过滤后的命中数**，不是租户全量"

    # 超管：管理视角，本租户全部
    all_of_them, all_total = store.list_employees(ADMIN)
    assert {e.agent_key for e in all_of_them} == {"a-owner", "a-mate"}
    assert all_total == 2

    # `visible_agent_keys`：超管为 None（不受限），普通员工为具体集合 —— 供 roster 复用同一口径
    assert store.visible_agent_keys(ADMIN) is None
    assert store.visible_agent_keys(OWNER) == {"a-owner"}


def test_cross_tenant_isolation_on_real_db(store) -> None:
    """真库：跨租户既看不到、也读不到（按不存在处理，不泄露存在性）。"""
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)

    theirs, total = store.list_employees(CROSS_TENANT)
    assert (theirs, total) == ([], 0)
    assert store.read_agent_owner(CROSS_TENANT, "a-owner") is None


# --------------------------------------------------------------------- 共享


def test_shares_roundtrip_on_real_db(store) -> None:
    """真库：共享三方法往返（两档 `read` / `use`），且**真的扩展可见性**。"""
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)

    # 加共享前：陌生人看不见
    assert store.list_employees(STRANGER)[1] == 0

    share = store.add_share(OWNER, "a-owner", grantee_user_id=MATE.user_id, permission="use")
    assert share.permission == "use"

    # 加共享后：可见，且档位读得回来
    assert [e.agent_key for e in store.list_employees(MATE)[0]] == ["a-owner"]
    assert store.share_permission(OWNER, "a-owner", MATE.user_id) == "use"

    listed, total = store.list_shares(OWNER, "a-owner")
    assert total == 1
    assert [s.grantee_user_id for s in listed] == [MATE.user_id]

    # 陌生人仍看不见
    assert store.list_employees(STRANGER)[1] == 0

    # 撤销 ⇒ 可见性收回；复删幂等
    assert store.remove_share(OWNER, "a-owner", MATE.user_id) is True
    assert store.remove_share(OWNER, "a-owner", MATE.user_id) is False
    assert store.list_employees(MATE)[1] == 0


def test_share_requires_ownership_on_real_db(store) -> None:
    """真库：**仅归属人**可增删共享（他人 ⇒ 按不存在处理，不泄露存在性）。"""
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)

    with pytest.raises(Exception):
        store.add_share(STRANGER, "a-owner", grantee_user_id=MATE.user_id, permission="read")


def test_share_foreign_key_really_exists_on_real_db(store) -> None:
    """真库：迁移 045 的外键**真的在** —— 分两段验，别把两件事混成一件。

    **① 应用层**：`add_share` 指向不存在的员工 ⇒ `DirectoryNotFound`
    （归属人校验**先于**数据库，不泄露存在性 —— 这比数据库报错更好，故不改成 FK 报错）。
    **② 数据库层**：绕过应用层用**裸 SQL** 直插 ⇒ 必须撞 `ForeignKeyViolation`。
    这一条是**结构性断言**，只有真库能验：假连接永远不会发现"迁移忘了建外键"。
    """
    psycopg = pytest.importorskip("psycopg")
    from app.workforce.models import DirectoryNotFound

    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)

    # ① 应用层先拦
    with pytest.raises(DirectoryNotFound):
        store.add_share(OWNER, "no-such-agent", grantee_user_id=MATE.user_id, permission="read")

    # ② 裸 SQL 直插 ⇒ 外键必须拦下
    with store.connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO workbench_employee_shares "
                "(tenant_id, agent_key, grantee_user_id, permission, granted_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (TENANT, "no-such-agent", MATE.user_id, "read", OWNER.user_id),
            )


# --------------------------------------------------------------------- 角色白名单


def test_customer_admin_excluded_on_real_db(store) -> None:
    """真库：`customer_admin` 在读档 / 创建档**两层都排除**（权限矩阵数字员工四行全 ❌）。"""
    with pytest.raises(PolicyError):
        store.list_employees(CUSTOMER_ADMIN)
    with pytest.raises(PolicyError):
        store.create_employee(CUSTOMER_ADMIN, agent_key="a-x", name="丙", role_key=ROLE_KEY)


# --------------------------------------------------------------------- config 读


def test_config_read_follows_share_permission_on_real_db(store) -> None:
    """真库：`read` 档可读 config、`use` 档不可读、陌生人不可读、归属人可读。

    口径源：B1 §3.3② 表 / `api-contract.md` —— `read` = 能看配置、不能派活。
    """
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)
    store.update_agent_config(ADMIN, "a-owner", system_prompt="SECRET-PROMPT")

    assert store.read_agent_config(OWNER, "a-owner").system_prompt == "SECRET-PROMPT"

    store.add_share(OWNER, "a-owner", grantee_user_id=MATE.user_id, permission="read")
    stranger2 = UserContext(TENANT, "acct-op01-use", "employee")
    store.add_share(OWNER, "a-owner", grantee_user_id=stranger2.user_id, permission="use")

    assert store.read_agent_config(MATE, "a-owner").system_prompt == "SECRET-PROMPT"
    with pytest.raises(PolicyError):
        store.read_agent_config(stranger2, "a-owner")
    with pytest.raises(PolicyError):
        store.read_agent_config(STRANGER, "a-owner")


# --------------------------------------------------------------------- 管理档不动


def test_admin_only_methods_stay_locked_on_real_db(store) -> None:
    """真库：本批**不放宽**的方法权限逐字不变（建 / 改岗位、跨模块只读方法）。"""
    for ctx in (OWNER, MATE, CUSTOMER_ADMIN):
        with pytest.raises(PolicyError):
            store.create_role(ctx, role_key="r-x", name="岗")
        with pytest.raises(PolicyError):
            store.known_keys(ctx)

    # 管理动作也仍锁着
    store.create_employee(OWNER, agent_key="a-owner", name="甲", role_key=ROLE_KEY)
    with pytest.raises(PolicyError):
        store.update_employee(OWNER, "a-owner", name="改名")
    with pytest.raises(PolicyError):
        store.update_agent_config(OWNER, "a-owner", system_prompt="x")
