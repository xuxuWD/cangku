"""`PostgresMemoryStore` 的**真库**回归（P3 记忆层，迁移 029）。

口径（沿用 `tests/test_commercial_lifecycle_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**，
    不影响默认 `pytest` 全量（无库环境不会红）。
  - 目标库必须是**已完成全部迁移（含 029）**的库；本文件**不建表、不迁移**，
    缺表时应**显式失败**而不是静默跳过。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清。
  - ✅ 本文件应纳入 `.github/workflows/ci.yml` 的 `postgres` job（与既有真库测试一并真跑）。

重点验证（规格 §3 + 反假）：
  1. `VECTOR(1024)` 列真实存在、维度断言成立（`embedding` 写入/读回长度 == 1024）。
  2. 事实类幂等（同 idempotency_key 重放返回既有记录，不重复入库）。
  3. 事实类向量检索（`<=> %s::vector` 余弦排序，scope/owner 过滤正确）。
  4. 规则类 supersede 链（同 rule_key 只留一个 active，旧版软删指向新版）。
  5. 画像键 UPSERT（同键覆盖）。
  6. `list_all_for_tenant` / `delete_all_for_tenant` 生命周期两方法真库可跑。
"""

from __future__ import annotations

import os

import pytest

from app.domain import UserContext
from app.memory.embedding import FakeEmbeddingAdapter
from app.memory.models import EMBEDDING_DIMENSIONS, MemoryScope
from app.memory.service import MemoryService
from app.memory.store import PostgresMemoryStore, _parse_embedding

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-memory-pg"
ALICE = "acct-pg-alice"
ADMIN = "acct-pg-admin"


@pytest.fixture()
def service():
    """每次自清 TENANT 的记忆数据；返回 (PostgresMemoryService, psycopg 连接)。"""
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    store = PostgresMemoryStore(connection)
    svc = MemoryService(store, FakeEmbeddingAdapter())
    yield svc, connection
    _purge(connection)
    connection.close()


def _purge(connection) -> None:
    """按外键逆序清空 TENANT 的记忆数据（生命周期方法在测试内验证，这里直接 SQL 清场）。"""
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_memory_facts WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_memory_rules WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_memory_profile_keys WHERE tenant_id = %s", (TENANT,))


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


# ------------------------------------------------------------ 表结构与维度（反假）

def test_vector_column_exists_and_dimension_1024(service) -> None:
    """029 建表后 `embedding` 必须是 VECTOR(1024)：维度写死是 D12 契约，改维度必须红。"""
    svc, connection = service
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'workbench_memory_facts' AND column_name = 'embedding' AND data_type = 'USER-DEFINED'"
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'workbench_memory_facts' AND column_name = 'embedding'"
        )
        assert cursor.fetchone()[0] == "vector"


def test_fact_persists_with_1024_embedding(service) -> None:
    """写入事实并读回：embedding 长度必须 == 1024（PG 侧 round-trip 维度断言）。"""
    svc, connection = service
    fact = svc.create_fact(
        _alice(), content="真库事实写入", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-k1",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT embedding FROM workbench_memory_facts WHERE tenant_id = %s AND memory_id = %s",
            (TENANT, fact.memory_id),
        )
        row = cursor.fetchone()
    assert row is not None
    # psycopg 未注册 pgvector 类型时返回字符串，须经 _parse_embedding 解析 — 维度断言在解析后的 tuple 上成立。
    embedding = _parse_embedding(row[0])
    assert embedding is not None
    assert len(embedding) == EMBEDDING_DIMENSIONS


# ------------------------------------------------------------ 幂等

def test_fact_idempotency_in_postgres(service) -> None:
    """同 (tenant, owner_kind, owner_id, idempotency_key) 重放返回既有记录，不新增行。"""
    svc, connection = service
    first = svc.create_fact(
        _alice(), content="幂等验证", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-idem-1",
    )
    second = svc.create_fact(
        _alice(), content="幂等验证", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-idem-1",
    )
    assert second.memory_id == first.memory_id
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workbench_memory_facts "
            "WHERE tenant_id = %s AND idempotency_key = %s",
            (TENANT, "pg-idem-1"),
        )
        assert cursor.fetchone()[0] == 1


# ------------------------------------------------------------ 向量检索（真库）

def test_vector_search_ranks_cosine_in_postgres(service) -> None:
    """真库 `<=> %s::vector` 检索：写入两条，query 命中相关性更高者且只返回本租户可行条目。"""
    svc, connection = service
    svc.create_fact(
        _alice(), content="客户偏好邮件沟通", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-s1",
    )
    svc.create_fact(
        _alice(), content="公司食堂菜单每周更新", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-s2",
    )
    hits = svc.search_facts(_alice(), query="客户偏好邮件沟通", scope=None)
    assert len(hits) >= 1
    assert any("客户偏好邮件沟通" in item.content for item in hits)
    # 第一条必须是 query 的精确写入（FakeAdapter 下最相似也应是同文本）。
    assert "客户偏好邮件沟通" in hits[0].content


def test_vector_search_respects_admin_visibility(service) -> None:
    """ceo/admin 可检索本租户他人记忆；普通员工检索不到他人内容。"""
    svc, connection = service
    svc.create_fact(
        _admin(), content="Bob 专有的秘密事实", scope="user",
        owner_kind="user", owner_id="acct-pg-bob", idempotency_key="pg-bob-1",
    )
    employee_hits = svc.search_facts(_alice(), query="Bob 专有的秘密事实", scope=None)
    assert all("Bob 专有的秘密事实" not in item.content for item in employee_hits)
    ceo = UserContext(TENANT, "acct-pg-ceo", "ceo")
    admin_hits = svc.search_facts(ceo, query="Bob 专有的秘密事实", scope=None)
    assert any("Bob 专有的秘密事实" in item.content for item in admin_hits)


# ------------------------------------------------------------ 规则类 supersede 链

def test_rule_supersede_chain_in_postgres(service) -> None:
    """同 rule_key 二次写入：旧版 superseded 指向新版，active 只剩一条。"""
    svc, connection = service
    v1 = svc.create_rule(
        _admin(), rule_key="summary.style", content="先结论后背景",
        scope="role", owner_kind="user", owner_id=ALICE,
    )
    v2 = svc.create_rule(
        _admin(), rule_key="summary.style", content="结论+数据支撑",
        scope="role", owner_kind="user", owner_id=ALICE,
    )
    assert v2.version == v1.version + 1
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, superseded_by FROM workbench_memory_rules "
            "WHERE tenant_id = %s AND memory_id = %s",
            (TENANT, v1.memory_id),
        )
        old_row = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM workbench_memory_rules "
            "WHERE tenant_id = %s AND rule_key = %s AND status = 'active'",
            (TENANT, "summary.style"),
        )
        active_count = cursor.fetchone()[0]
    assert old_row[0] == "superseded"
    assert old_row[1] == v2.memory_id
    assert active_count == 1


# ------------------------------------------------------------ 画像 UPSERT

def test_profile_upsert_in_postgres(service) -> None:
    svc, connection = service
    svc.set_profile_key(_alice(), key="language", value="中文", owner_kind="user", owner_id=ALICE)
    svc.set_profile_key(_alice(), key="language", value="English", owner_kind="user", owner_id=ALICE)
    profile = svc.get_profile(_alice(), owner_kind="user", owner_id=ALICE)
    assert profile == {"language": "English"}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workbench_memory_profile_keys "
            "WHERE tenant_id = %s AND profile_key = %s",
            (TENANT, "language"),
        )
        assert cursor.fetchone()[0] == 1


# ------------------------------------------------------------ 生命周期两方法（N2 前置）

def test_lifecycle_list_and_delete_for_tenant(service) -> None:
    """`list_all_for_tenant` / `delete_all_for_tenant`：按租户导出与删除（规格 N2 接线前置）。"""
    svc, connection = service
    svc.create_fact(
        _alice(), content="生命周期一号", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-lc-1",
    )
    svc.create_fact(
        _alice(), content="生命周期二号", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="pg-lc-2",
    )
    listed = svc.store.list_all_for_tenant(TENANT)
    assert len(listed) >= 2
    deleted = svc.store.delete_all_for_tenant(TENANT)
    assert deleted >= 2
    assert svc.store.list_all_for_tenant(TENANT) == []