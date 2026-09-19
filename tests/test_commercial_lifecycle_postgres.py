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


# ---------------------------------------------------------------------------
# B-1（2026-09-19）：`PostgresExportPackageStore.list_for_tenant` 的真库口径
# 契约：docs/api-contract.md「GET /api/v1/commercial/exports」——
# 租户限定 + 生成时间倒序（同刻按包号倒序）+ 计数与分页；列表**不取载荷**。
# ---------------------------------------------------------------------------

LIST_TENANT = "test-lifecycle-pg-list"


@pytest.fixture()
def export_list_store():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_tenants (id, name, owner_id, status)
            VALUES (%s, '客户PG', 'owner-pg', 'deleting')
            ON CONFLICT (id) DO NOTHING
            """,
            (LIST_TENANT,),
        )
        cursor.execute("DELETE FROM workbench_export_packages WHERE tenant_id = %s", (LIST_TENANT,))
    yield PostgresExportPackageStore(connection)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_export_packages WHERE tenant_id = %s", (LIST_TENANT,))
        cursor.execute("DELETE FROM workbench_tenants WHERE id = %s", (LIST_TENANT,))
    connection.close()


def _package(package_id: str, created_at: datetime) -> ExportPackage:
    return ExportPackage(
        tenant_id=LIST_TENANT,
        payload={"tenant_id": LIST_TENANT},
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
        id=package_id,
    )


def test_export_package_list_filters_orders_and_counts(export_list_store) -> None:
    now = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    export_list_store.save(_package("export-pg-ls-old", now))
    export_list_store.save(_package("export-pg-ls-b", now + timedelta(minutes=1)))
    export_list_store.save(_package("export-pg-ls-a", now + timedelta(minutes=1)))

    # 前提校验：把「两行同刻」由**假定**变成**断言**（列类型若截断精度 ⇒ 本断言先红，
    # 避免「看似在验并列、实际两行不同刻」的假守护；口径同 `list_for_tenant` 先例）。
    with export_list_store.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, created_at FROM workbench_export_packages WHERE tenant_id = %s AND id LIKE 'export-pg-ls-%%' ORDER BY id",
            (LIST_TENANT,),
        )
        rows = cursor.fetchall()
    assert [row[0] for row in rows] == ["export-pg-ls-a", "export-pg-ls-b", "export-pg-ls-old"]
    assert rows[0][1] == rows[1][1] == now + timedelta(minutes=1), (
        f"真库两行未真正同刻：{rows[0][1]!r} / {rows[1][1]!r}"
    )

    items, total = export_list_store.list_for_tenant(LIST_TENANT, limit=2, offset=0)

    assert total == 3
    # 生成时间倒序（最新在前），同刻按包号倒序 ⇒ 顺序确定（真库不依赖物理行序）。
    assert [item.id for item in items] == ["export-pg-ls-b", "export-pg-ls-a"]
    assert all(item.tenant_id == LIST_TENANT for item in items)
    # 列表是元数据面：不携带载荷。
    assert not hasattr(items[0], "payload")

    page, same_total = export_list_store.list_for_tenant(LIST_TENANT, limit=2, offset=2)

    assert same_total == 3  # 计数不受分页影响
    assert [item.id for item in page] == ["export-pg-ls-old"]

    # 越界 / 无行：空列表 + 计数如实（不报错）。
    beyond, beyond_total = export_list_store.list_for_tenant(LIST_TENANT, limit=10, offset=10)
    assert beyond == [] and beyond_total == 3
    empty, empty_total = export_list_store.list_for_tenant("test-lifecycle-pg-none", limit=10, offset=0)
    assert empty == [] and empty_total == 0


# ---------------------------------------------------------------------------
# B-2（2026-09-19）：**真库**端到端导出载荷——PG 存储 + 读取器 → 只含本租户的真实行
# 契约：docs/api-contract.md「私有部署商业化 G0」导出段（字段口径 / 上限与截断声明）。
# 为什么用真库：读者的字段与计数语义在两套实现下不同（PG 走 SQL），只有真库能证明不是「内存能跑」。
# ---------------------------------------------------------------------------

EXPORT_TENANT = "test-export-pg"
EXPORT_OTHER = "test-export-pg-other"


@pytest.fixture()
def export_db():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    tenants = (EXPORT_TENANT, EXPORT_OTHER)
    tables = (
        "workbench_run_artifacts",
        "workbench_runtime_states",
        "workbench_run_records",
        "workbench_job_roles",
        "workbench_audit_log",
        "workbench_knowledge_documents",
        "workbench_tasks",
        "workbench_accounts",
        "workbench_usage_ledger",
    )
    with connection.cursor() as cursor:
        for tenant in tenants:
            cursor.execute(
                """
                INSERT INTO workbench_tenants (id, name, owner_id, status)
                VALUES (%s, '导出PG', 'owner-pg', 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                (tenant,),
            )
        for table in tables:
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id IN (%s, %s)", tenants)
    yield connection
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute("DELETE FROM workbench_tenants WHERE id IN (%s, %s)", tenants)
    connection.close()


def test_pg_backed_export_payload_reads_own_tenant_and_declares_truncation(export_db) -> None:
    from app.audit.models import AuditAction
    from app.audit.service import AuditService
    from app.audit.store import PostgresAuditStore
    from app.commercial.export_readers import build_export_readers
    from app.commercial.lifecycle import CommercialLifecycleService
    from app.commercial.repository import PostgresCommercialRepository
    from app.domain import UserContext
    from app.knowledge_governance.models import KnowledgeDoc, KnowledgeDocStatus
    from app.knowledge_governance.store import PostgresKnowledgeGovStore
    from app.runtime.records import PostgresRunRecordStore, RunRecord
    from app.workforce.store import PostgresWorkforceDirectoryStore

    context = UserContext(tenant_id=EXPORT_TENANT, user_id="admin-pg", role="super_admin")
    workforce = PostgresWorkforceDirectoryStore(export_db)
    workforce.create_role(context, role_key="pg-role", name="PG 岗位", description="真库岗位")
    workforce.create_role(
        UserContext(tenant_id=EXPORT_OTHER, user_id="admin-pg-2", role="super_admin"),
        role_key="pg-other-role",
        name="他租户岗位",
    )
    runs = PostgresRunRecordStore(export_db)
    for index in range(2):
        runs.upsert(
            RunRecord(
                run_id=f"run-pg-{index}",
                tenant_id=EXPORT_TENANT,
                task_id="task-pg",
                runtime_key="mock",
                status="completed",
                started_at=datetime(2026, 9, 19, 8, index, tzinfo=UTC),
            )
        )
    runs.upsert(
        RunRecord(
            run_id="run-pg-other",
            tenant_id=EXPORT_OTHER,
            task_id="task-pg-other",
            runtime_key="mock",
            status="completed",
            started_at=datetime(2026, 9, 19, 9, 0, tzinfo=UTC),
        )
    )
    audits = AuditService(PostgresAuditStore(export_db))
    audits.record(
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=EXPORT_TENANT, actor_id="admin-pg", target_id="acc-pg"
    )
    audits.record(
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=EXPORT_OTHER, actor_id="admin-pg-2", target_id="acc-other"
    )
    knowledge = PostgresKnowledgeGovStore(export_db)
    knowledge.register_document(
        context,
        doc=KnowledgeDoc(
            tenant_id=EXPORT_TENANT,
            document_id="doc-pg-1",
            title="PG 文档",
            owner_id="owner-pg",
            status=KnowledgeDocStatus.DRAFT,
            version="v1",
            source_key="weknora",
            registered_by="admin-pg",
        ),
    )
    readers = build_export_readers(workforce=workforce, knowledge=knowledge, audits=audits, runs=runs)
    assert set(readers) == {"roles", "agents", "knowledge_documents", "audits", "runs"}

    payload = CommercialLifecycleService(
        PostgresCommercialRepository(export_db), export_readers=readers
    ).build_export_payload(EXPORT_TENANT)

    assert [row["role_key"] for row in payload["resources"]["roles"]] == ["pg-role"]
    assert [row["document_id"] for row in payload["resources"]["knowledge_documents"]] == ["doc-pg-1"]
    assert {row["target_id"] for row in payload["resources"]["audits"]} == {"acc-pg"}
    assert [row["run_id"] for row in payload["resources"]["runs"]] == ["run-pg-1", "run-pg-0"]
    assert payload["unavailable_categories"] == []
    assert payload["truncated_categories"] == {}  # 未超上限：不声明截断

    # 上限压到 1 ⇒ 只有超出上限的类别被声明截断，其余不动（总数来自 SQL COUNT，不是返回条数）。
    capped = CommercialLifecycleService(
        PostgresCommercialRepository(export_db), export_readers=readers, export_category_max_rows=1
    ).build_export_payload(EXPORT_TENANT)

    assert len(capped["resources"]["runs"]) == 1
    assert capped["truncated_categories"] == {"runs": {"exported": 1, "total": 2}}


def test_pg_backed_export_payload_covers_tasks_users_usage(export_db) -> None:
    """B-2b：任务 / 用户 / 用量三类在**真库**上的读取与租户隔离。

    生产里导出作业由 worker 在 PG 上执行 ⇒ 「内存实现能跑」不算证据，本用例走 SQL 路径。
    任务行用直接 SQL 种（避免 `create` 的 outbox / 审计副作用，本用例只验读取路径）。
    """
    from app.accounts.models import Account
    from app.accounts.repository import PostgresAccountRepository
    from app.commercial.export_readers import build_export_readers
    from app.commercial.lifecycle import CommercialLifecycleService
    from app.commercial.repository import PostgresCommercialRepository
    from app.commercial.usage import PostgresUsageLedger, UsageEntry
    from app.repository import PostgresTaskRepository

    with export_db.cursor() as cursor:
        for task_id, tenant in (("task-pg-1", EXPORT_TENANT), ("task-pg-other", EXPORT_OTHER)):
            cursor.execute(
                """
                INSERT INTO workbench_tasks
                    (id, tenant_id, project_id, created_by, employee_key, title,
                     risk_level, budget, idempotency_key, request_fingerprint, status)
                VALUES (%s, %s, 'p-1', 'u-1', 'content-writer', '周报整理', 'low', 5, %s, 'fp', 'queued')
                ON CONFLICT (id) DO NOTHING
                """,
                (task_id, tenant, f"idem-{task_id}"),
            )

    accounts = PostgresAccountRepository(export_db)
    own = accounts.add(
        Account(phone="13900000001", password_hash="scrypt$h", position="内容运营", full_name="张三")
    )
    accounts.mark_approved(own.account_id, role="employee", tenant_id=EXPORT_TENANT, reviewed_by="admin-pg")
    foreign = accounts.add(
        Account(phone="13900000002", password_hash="scrypt$h", position="岗位", full_name="李四")
    )
    accounts.mark_approved(foreign.account_id, role="employee", tenant_id=EXPORT_OTHER, reviewed_by="admin-pg-2")

    usage = PostgresUsageLedger(export_db)
    usage.append(UsageEntry(idempotency_key="run-pg-1", tenant_id=EXPORT_TENANT, units=10, cost_cents=50))
    usage.append(UsageEntry(idempotency_key="run-pg-other", tenant_id=EXPORT_OTHER, units=3, cost_cents=30))

    readers = build_export_readers(
        accounts=accounts, tasks=PostgresTaskRepository(export_db), usage=usage
    )
    assert set(readers) == {"users", "tasks", "usage"}

    payload = CommercialLifecycleService(
        PostgresCommercialRepository(export_db), export_readers=readers
    ).build_export_payload(EXPORT_TENANT)

    assert [row["task_id"] for row in payload["resources"]["tasks"]] == ["task-pg-1"]
    assert [row["phone_masked"] for row in payload["resources"]["users"]] == ["139****0001"]
    assert [row["units"] for row in payload["resources"]["usage"]] == [10]
    for row in payload["resources"]["tasks"] + payload["resources"]["users"] + payload["resources"]["usage"]:
        assert "tenant_id" not in row  # 顶层已给租户；行内不再重复
    assert payload["unavailable_categories"] == []
    assert payload["truncated_categories"] == {}


def test_pg_backed_export_payload_covers_artifacts_and_steps(export_db) -> None:
    """B-2c：产物登记与计划步骤在**真库**上的读取与租户隔离（导出作业在生产走 PG）。"""
    from app.commercial.export_readers import build_export_readers
    from app.commercial.lifecycle import CommercialLifecycleService
    from app.commercial.repository import PostgresCommercialRepository
    from app.runtime.artifacts import PostgresRunArtifactStore
    from app.runtime.contracts import AgentPlan, RuntimeContext
    from app.runtime.records import PostgresRunRecordStore, RunRecord
    from app.runtime.state_postgres import PostgresRuntimeStateStore
    from app.tool_execution.file_ops import FileChange

    runs = PostgresRunRecordStore(export_db)
    for run_id, tenant in (("run-art-pg", EXPORT_TENANT), ("run-art-pg-other", EXPORT_OTHER)):
        runs.upsert(
            RunRecord(
                run_id=run_id,
                tenant_id=tenant,
                task_id=f"task-{run_id}",
                runtime_key="mock",
                status="completed",
                started_at=datetime(2026, 9, 19, 8, 0, tzinfo=UTC),
            )
        )
    artifacts = PostgresRunArtifactStore(export_db, retention_days=30)
    artifacts.register(
        EXPORT_TENANT,
        "run-art-pg",
        [FileChange(virtual_path="/workspace/own.txt", change_kind="created", bytes=11, sha256=f"sha256:{1:064d}")],
    )
    artifacts.register(
        EXPORT_OTHER,
        "run-art-pg-other",
        [FileChange(virtual_path="/workspace/other.txt", change_kind="created", bytes=12, sha256=f"sha256:{2:064d}")],
    )
    states = PostgresRuntimeStateStore(export_db)
    states.create(
        RuntimeContext(
            EXPORT_TENANT, "u-1", "content-operator", "craft", "p-1", "task-1", "dev-1",
            ("kb-1",), ("/ws",), 100, "low", "policy-1", datetime(2026, 9, 30, tzinfo=UTC),
        ),
        AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]),
        run_id="run-art-pg",
    )
    states.create(
        RuntimeContext(
            EXPORT_OTHER, "u-2", "content-operator", "craft", "p-2", "task-2", "dev-2",
            ("kb-1",), ("/ws",), 100, "low", "policy-1", datetime(2026, 9, 30, tzinfo=UTC),
        ),
        AgentPlan.from_steps([{"step_id": "s-other", "kind": "read", "tool": "knowledge.search"}]),
        run_id="run-art-pg-other",
    )

    readers = build_export_readers(artifacts=artifacts, steps=states)
    payload = CommercialLifecycleService(
        PostgresCommercialRepository(export_db), export_readers=readers
    ).build_export_payload(EXPORT_TENANT)

    assert [row["virtual_path"] for row in payload["resources"]["artifacts"]] == ["/workspace/own.txt"]
    assert [(row["run_id"], row["step_id"]) for row in payload["resources"]["steps"]] == [("run-art-pg", "s1")]
    assert payload["unavailable_categories"] == []
    assert payload["truncated_categories"] == {}
