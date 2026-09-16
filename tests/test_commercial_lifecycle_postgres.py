"""`PostgresLifecycleJobStore.list_for_tenant` 的**真库**确定性排序回归。

背景（E2+E3 真库演练暴露，已证实）：`list_for_tenant` 原 SQL **无 `ORDER BY`**，而
`execute_delete` 取 `jobs[-1]` 作「最近的删除作业」⇒ 同租户多条 `kind=delete` 时依赖物理行序、
可能选错作业。本文件把「加确定性排序后语义确定」变成可重复的真库回归。

口径（沿用 `tests/test_tool_action_store_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**，
    因此不影响默认 `pytest` 全量（无库环境不会红）。
  - 目标库必须是**已完成全部迁移（含 006/007）**的库；本文件**不建表、不迁移**，
    缺表时应**显式失败**而不是静默跳过。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清（按外键逆序删）。
  - ✅ **覆盖现状**：本文件**已纳入** `.github/workflows/ci.yml` 的 `postgres` job 命令，
    与 `test_tool_action_store_postgres.py`、`test_dsh_execution_postgres.py` 一并真跑，
    且该 job 强制 `tests > 0 and skipped == 0 and failed == 0`（由 `tests/test_ci_assets.py` 静态守护）。
    **✅ 已在真实 GitHub Actions 实跑**：push `e602a44` 触发 run `34870650538`
    （GitHub 显示 `2026-09-14T16:46Z` = 本地 `2026-09-15 00:46`），该 job `conclusion=success`，
    日志末行 `真库用例：tests=33 skipped=0 failed=0`（含本文件 2 条）。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.commercial.lifecycle import ExportPackage, LifecycleJob, PostgresExportPackageStore, PostgresLifecycleJobStore
from app.commercial.repository import ResourceNotFound

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-lifecycle-pg"


@pytest.fixture()
def store():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_tenants (id, name, owner_id, status)
            VALUES (%s, '客户PG', 'owner-pg', 'deleting')
            ON CONFLICT (id) DO NOTHING
            """,
            (TENANT,),
        )
        cursor.execute("DELETE FROM workbench_lifecycle_jobs WHERE tenant_id = %s", (TENANT,))
    yield PostgresLifecycleJobStore(connection)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_lifecycle_jobs WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_tenants WHERE id = %s", (TENANT,))
    connection.close()


def _job(job_id: str, requested_at: datetime) -> LifecycleJob:
    return LifecycleJob(
        tenant_id=TENANT,
        kind="delete",
        status="cooling_down",
        requested_by="admin-pg",
        execute_after=requested_at,
        id=job_id,
        requested_at=requested_at,
        final_exported=True,
    )


def test_list_for_tenant_orders_by_created_at_then_id(store) -> None:
    """插入顺序与时间顺序不一致时，真库仍按 `created_at, id` 升序返回。"""
    # 故意先插入时间更晚的 ⇒ 插入顺序 != 时间顺序（无 ORDER BY 时末位会选错）。
    store.create(_job("job-newer", datetime(2026, 9, 12, 8, 0, tzinfo=UTC)))
    store.create(_job("job-older", datetime(2026, 9, 10, 8, 0, tzinfo=UTC)))

    listed = store.list_for_tenant(TENANT, kind="delete")

    assert [job.id for job in listed] == ["job-older", "job-newer"]


def test_list_for_tenant_breaks_same_timestamp_ties_by_id(store) -> None:
    """同刻多行：先**证实真库中两行确实同刻**，再断言次级键 `id` 使顺序仍确定。"""
    same = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    store.create(_job("job-b", same))
    store.create(_job("job-a", same))

    # 前提校验：把「同刻」由**假定**变成**断言**。若 `create` 把 `created_at` 落成 `now()`、
    # 或列类型把亚秒精度截断 ⇒ 两行其实不同刻，此时本断言先红，
    # 避免出现「看似在验并列、实际两行不同刻」的假守护。
    with store.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, created_at FROM workbench_lifecycle_jobs WHERE tenant_id = %s ORDER BY id",
            (TENANT,),
        )
        rows = cursor.fetchall()

    assert [row[0] for row in rows] == ["job-a", "job-b"]
    assert rows[0][1] == rows[1][1] == same, (
        f"真库两行未真正同刻：{rows[0][1]!r} / {rows[1][1]!r}"
    )

    listed = store.list_for_tenant(TENANT, kind="delete")

    assert [job.id for job in listed] == ["job-a", "job-b"]


# ---------------------------------------------------------------------------
# 组 10.7 加固（2026-09-16）：导出包过期清理的真库语义
# 口径：docs/api-contract.md「GET /api/v1/commercial/exports/{package_id}」——
# 过期包由 worker 周期任务按 `expires_at` 物理清理（`DELETE ... WHERE expires_at <= now`）。
# ---------------------------------------------------------------------------


@pytest.fixture()
def export_store():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_tenants (id, name, owner_id, status)
            VALUES (%s, '客户PG', 'owner-pg', 'deleting')
            ON CONFLICT (id) DO NOTHING
            """,
            (TENANT,),
        )
        cursor.execute("DELETE FROM workbench_export_packages WHERE tenant_id = %s", (TENANT,))
    yield PostgresExportPackageStore(connection)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_export_packages WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_tenants WHERE id = %s", (TENANT,))
    connection.close()


def test_purge_expired_removes_only_rows_past_expiry(export_store) -> None:
    """真库：`expires_at <= now` 的行被物理删除（正点即过期），未过期行留存。"""
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    expired = ExportPackage(
        tenant_id=TENANT, payload={"tenant_id": TENANT},
        created_at=now - timedelta(days=7), expires_at=now, id="export-pg-expired",
    )
    fresh = ExportPackage(
        tenant_id=TENANT, payload={"tenant_id": TENANT},
        created_at=now, expires_at=now + timedelta(seconds=1), id="export-pg-fresh",
    )
    export_store.save(expired)
    export_store.save(fresh)

    removed = export_store.purge_expired(now=now)

    # 清理是**全局**的（跨租户，同 `run_pending_jobs` 口径）⇒ 只对「本租户两行」的下场做断言，
    # 计数按 `>= 1` 判（真库中若残留他处过期行，不应让本用例假红）。
    assert removed >= 1
    assert export_store.get(fresh.id, tenant_id=TENANT).id == fresh.id
    with pytest.raises(ResourceNotFound):
        export_store.get(expired.id, tenant_id=TENANT)
