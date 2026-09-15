"""`PostgresSkillStore` 的**真库**回归（P4 技能层，迁移 030）。

口径（沿用 `tests/test_commercial_lifecycle_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**。
  - 目标库必须是**已完成全部迁移（含 030）**的库；本文件**不建表、不迁移**。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清。

重点验证（规格 §3 + 反假）：
  1. `workbench_skills` / `workbench_skill_bindings` 两表真库可写读（含 JSONB allowed_tools）。
  2. 状态机流转变更真库持久化（submitted→approved→enabled→disabled）。
  3. 同 key 多版本并存；list_enabled_for_agent 只含 enabled。
  4. 生命周期 `list_all_for_tenant` / `delete_all_for_tenant` 真库可跑。
"""

from __future__ import annotations

import os

import pytest

from app.domain import UserContext
from app.skills.models import SkillStatus
from app.skills.service import SkillService
from app.skills.store import PostgresSkillStore
from app.skills.validator import SkillPackageValidator

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-skills-pg"
ALICE = "acct-pg-alice"
ADMIN = "acct-pg-admin"
CATALOG_TOOLS = frozenset({"fs.list", "fs.read", "fs.stat", "cmd.run", "fs.write", "fs.overwrite", "fs.delete", "artifact.export"})
SOURCES = frozenset({"first-party"})
SHA256_OK = "b" * 64


@pytest.fixture()
def service():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    store = PostgresSkillStore(connection)
    svc = SkillService(
        store,
        SkillPackageValidator(),
        allowed_sources=SOURCES,
        catalog_tool_keys=CATALOG_TOOLS,
    )
    yield svc, connection
    _purge(connection)
    connection.close()


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_skill_bindings WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_skills WHERE tenant_id = %s", (TENANT,))


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


# ------------------------------------------------------------ 表结构与持久化

def test_skill_persists_with_jsonb_allowed_tools(service) -> None:
    svc, connection = service
    skill = svc.submit_skill(
        _alice(), skill_key="summarize", version="1.0.0", name="摘要",
        description="生成结构化摘要", license="Apache-2.0",
        allowed_tools=["fs.read", "fs.stat"], source_key="first-party",
        content_sha256=SHA256_OK,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, allowed_tools, content_sha256 FROM workbench_skills "
            "WHERE tenant_id = %s AND skill_key = %s AND version = %s",
            (TENANT, skill.skill_key, skill.version),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row[0] == "submitted"
    assert set(row[1]) == {"fs.read", "fs.stat"}  # JSONB 读回
    assert row[2] == SHA256_OK


def test_state_machine_persists_in_postgres(service) -> None:
    """submitted→approved→enabled→disabled 全过程真库可写回，状态在行上可见。"""
    svc, connection = service
    svc.submit_skill(
        _alice(), skill_key="flow", version="1.0.0", name="流转",
        description="状态机验证", license="MIT",
        allowed_tools=["fs.list"], source_key="first-party", content_sha256=SHA256_OK,
    )
    svc.review_skill(_admin(), "flow", "1.0.0", approved=True)
    svc.enable_skill(_admin(), "flow", "1.0.0")
    svc.disable_skill(_admin(), "flow", "1.0.0")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, reviewed_by FROM workbench_skills "
            "WHERE tenant_id = %s AND skill_key = %s AND version = %s",
            (TENANT, "flow", "1.0.0"),
        )
        row = cursor.fetchone()
    assert row[0] == "disabled"
    assert row[1] == ADMIN


def test_multi_version_coexists_and_enabled_only_expands(service) -> None:
    svc, connection = service
    svc.submit_skill(
        _alice(), skill_key="v", version="1.0.0", name="v1",
        description="版本一", license="BSD-3",
        allowed_tools=["fs.list"], source_key="first-party", content_sha256=SHA256_OK,
    )
    svc.submit_skill(
        _alice(), skill_key="v", version="2.0.0", name="v2",
        description="版本二", license="BSD-3",
        allowed_tools=["fs.read"], source_key="first-party", content_sha256=SHA256_OK,
    )
    svc.review_skill(_admin(), "v", "2.0.0", approved=True)
    svc.enable_skill(_admin(), "v", "2.0.0")
    svc.bind_skill(_admin(), "agent-pg", "v")

    # 只有 enabled 版本参与展开（1.0.0 未审核不出现）。
    tools = svc.expanded_tools_for_agent(_admin(), "agent-pg")
    assert tools == ("fs.read",)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workbench_skills WHERE tenant_id = %s AND skill_key = %s",
            (TENANT, "v"),
        )
        assert cursor.fetchone()[0] == 2


# ------------------------------------------------------------ 生命周期（对称 P3 N2）

def test_lifecycle_list_and_delete_for_tenant(service) -> None:
    svc, connection = service
    svc.submit_skill(
        _alice(), skill_key="lc-1", version="1.0.0", name="生命周期一",
        description="生命周期验证", license="Apache-2.0",
        allowed_tools=["fs.list"], source_key="first-party", content_sha256=SHA256_OK,
    )
    listed = svc.store.list_all_for_tenant(TENANT)
    assert len(listed) >= 1
    deleted = svc.store.delete_all_for_tenant(TENANT)
    assert deleted >= 1
    assert svc.store.list_all_for_tenant(TENANT) == []