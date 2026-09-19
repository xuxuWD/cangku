"""B2+B3 任务与运行层租户清场的**真库**语义（2026-09-19 清场扩围）。

覆盖（只有真库能证伪）：
  1. **整层清空**：任务 / 提案两条 / 运行记录及其全部子表 / 运行事件 —— 逐表归零；
  2. **批发上限下的收敛**：`limit=1` 时多轮循环仍把整层清空（分批循环有效）；
  3. **他租户零影响** 与 **复清幂等**；
  4. `workbench_plan_versions`（商业化套餐版本目录）**永不清理**；
  5. 任务域事件流随任务级联消失（已裁决接受）；
  6. 服务端到端：`execute_delete` 面名含 `tasks_and_runs`、逐表归零。

口径：DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip；目标库须已完成全部迁移。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import PostgresAuditStore
from app.commercial.lifecycle import (
    CommercialLifecycleService,
    LifecycleJob,
    PostgresExportPackageStore,
    PostgresLifecycleJobStore,
    PostgresRetentionPolicyStore,
)
from app.commercial.repository import PostgresCommercialRepository
from app.commercial.retention import PostgresRetentionPurgeStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-b23-purge"
OTHER = "test-b23-purge-other"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

LAYER_TABLES = (
    "workbench_run_records",
    "workbench_run_artifacts",
    "workbench_run_acceptance_decisions",
    "workbench_run_promotions",
    "workbench_tool_actions",
    "workbench_execution_idempotency",
    "workbench_runtime_states",
    "workbench_runtime_events",
    "workbench_tasks",
    "workbench_audit_events",
    "workbench_plan_proposals",
    "workbench_orchestration_proposals",
)

_CLEAN_ORDER = (
    "workbench_run_artifacts",
    "workbench_run_acceptance_decisions",
    "workbench_run_promotions",
    "workbench_tool_actions",
    "workbench_execution_idempotency",
    "workbench_runtime_states",
    "workbench_runtime_events",
    "workbench_run_records",
    "workbench_audit_events",
    "workbench_tasks",
    "workbench_plan_proposals",
    "workbench_orchestration_proposals",
    "workbench_plan_versions",
    "workbench_conversations",
    "workbench_audit_log",
    "workbench_lifecycle_jobs",
)


def _clean(connection) -> None:
    tenants = [TENANT, OTHER]
    with connection.cursor() as cursor:
        for table in _CLEAN_ORDER:
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = ANY(%s)", (tenants,))
        # 租户表主键列是 `id`（不是 `tenant_id`），单独一条。
        cursor.execute("DELETE FROM workbench_tenants WHERE id = ANY(%s)", (tenants,))


@pytest.fixture()
def connection():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _clean(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'deleting')",
            (TENANT, "客户B23", "owner-b23"),
        )
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'active')",
            (OTHER, "客户B23乙", "owner-b23-2"),
        )
    yield connection
    _clean(connection)
    connection.close()


def _seed(connection, tenant: str, suffix: str) -> None:
    """种满任务 / 提案 / 运行域（两任务各带一条运行与子行）+ 运行事件 + 套餐版本目录一行。"""
    with connection.cursor() as cursor:
        for index in (1, 2):
            task_id = f"task-{suffix}-{index}"
            run_id = f"run-{suffix}-{index}"
            cursor.execute(
                """
                INSERT INTO workbench_tasks
                    (id, tenant_id, project_id, created_by, employee_key, title, risk_level, budget_cents,
                     idempotency_key, request_fingerprint, status, created_at)
                VALUES (%s, %s, NULL, 'user-b23', 'employee-key', '清场样本', 'low', 0, %s, %s, 'queued', %s)
                """,
                (task_id, tenant, f"idem-{task_id}", f"fp-{task_id}", NOW - timedelta(days=200)),
            )
            cursor.execute(
                "INSERT INTO workbench_audit_events (task_id, tenant_id, action, actor_id, actor_role) "
                "VALUES (%s, %s, 'task.created', 'user-b23', 'employee')",
                (task_id, tenant),
            )
            cursor.execute(
                "INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status, started_at) "
                "VALUES (%s, %s, %s, 'mock', 'completed', %s)",
                (run_id, tenant, task_id, NOW - timedelta(days=200)),
            )
            cursor.execute(
                "INSERT INTO workbench_run_artifacts (tenant_id, run_id, artifact_id, virtual_path, change_kind, bytes, sha256, created_at) "
                "VALUES (%s, %s, %s, '/workspace/a.txt', 'created', 1, 'sha256:x', now())",
                (tenant, run_id, f"art-{run_id}"),
            )
            cursor.execute(
                "INSERT INTO workbench_run_acceptance_decisions (tenant_id, run_id, decision_id, decision, reason, idempotency_key, decided_by, decided_by_role, structural_verdict, created_at) "
                "VALUES (%s, %s, %s, 'confirmed', '', %s, 'admin', 'customer_admin', 'met', now())",
                (tenant, run_id, f"dec-{run_id}", f"idem-dec-{run_id}"),
            )
            cursor.execute(
                "INSERT INTO workbench_run_promotions (tenant_id, run_id, task_id, title, promoted_by, created_at) "
                "VALUES (%s, %s, %s, '标题', 'admin', now())",
                (tenant, run_id, task_id),
            )
            cursor.execute(
                "INSERT INTO workbench_tool_actions (tenant_id, action_id, run_id, task_id, step_id, tool_key, args_digest, args_json, plan_digest, risk_level, requires_approval, status, requested_by, requested_at, decided_by, decided_at) "
                "VALUES (%s, %s, %s, %s, 'step-1', 'shell', 'd', '{}'::jsonb, 'p', 'low', false, 'approved', 'admin', now(), 'admin', now())",
                (tenant, f"act-{run_id}", run_id, task_id),
            )
            cursor.execute(
                "INSERT INTO workbench_runtime_states (run_id, tenant_id, task_id, status, context, plan, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'completed', '{}'::jsonb, '{}'::jsonb, now(), now())",
                (run_id, tenant, task_id),
            )
            cursor.execute(
                "INSERT INTO workbench_runtime_events (run_id, tenant_id, sequence, event_type, occurred_at) "
                "VALUES (%s, %s, 1, 'step.started', now())",
                (run_id, tenant),
            )
        cursor.execute(
            "INSERT INTO workbench_plan_proposals (proposal_id, task_id, tenant_id, goal, steps, generator_key, created_by, idempotency_key, status, created_at) "
            "VALUES (%s, %s, %s, '目标', '[]'::jsonb, 'mock', 'user-b23', %s, 'pending_review', now())",
            (f"prop-{suffix}", f"task-{suffix}-1", tenant, f"idem-prop-{suffix}"),
        )
        cursor.execute(
            "INSERT INTO workbench_orchestration_proposals (proposal_id, tenant_id, kind, current_value, proposed_value, rationale, status, created_by, created_at) "
            "VALUES (%s, %s, 'autonomy', 'a', 'b', 'r', 'pending_review', 'admin', now())",
            (f"orch-{suffix}", tenant),
        )
        cursor.execute(
            "INSERT INTO workbench_plan_versions (tenant_id, plan_key, version, limits, effective_at) "
            "VALUES (%s, 'standard', 1, '{}'::jsonb, now()) ON CONFLICT DO NOTHING",
            (tenant,),
        )


def _counts(connection, tenant: str, tables=LAYER_TABLES) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s", (tenant,))
            counts[table] = int(cursor.fetchone()[0])
    return counts


def test_whole_task_and_run_layer_is_emptied_and_spares_other_tenants(connection) -> None:
    _seed(connection, TENANT, "target")
    _seed(connection, OTHER, "other")
    before = _counts(connection, TENANT)
    assert before["workbench_tasks"] == 2 and before["workbench_run_records"] == 2
    assert before["workbench_runtime_events"] == 2 and before["workbench_audit_events"] == 2

    store = PostgresRetentionPurgeStore(connection)
    counts = store.purge_all_for_tenant(TENANT)

    assert set(_counts(connection, TENANT).values()) == {0}, "整层必须逐表归零（含运行事件与任务事件流）"
    assert counts["runs"] == 2 and counts["tasks"] == 2
    assert counts["run_artifacts"] == 2 and counts["runtime_events"] == 2
    assert counts["plan_proposals"] == 1 and counts["orchestration_proposals"] == 1
    # 商业化套餐版本目录**不是运行期数据** ⇒ 永不清理。
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_plan_versions WHERE tenant_id = %s", (TENANT,))
        assert int(cursor.fetchone()[0]) == 1
    # 他租户零影响：逐表行数原样（含执行幂等 0 —— 该表本用例未种）。
    assert _counts(connection, OTHER) == {
        "workbench_run_records": 2,
        "workbench_run_artifacts": 2,
        "workbench_run_acceptance_decisions": 2,
        "workbench_run_promotions": 2,
        "workbench_tool_actions": 2,
        "workbench_execution_idempotency": 0,
        "workbench_runtime_states": 2,
        "workbench_runtime_events": 2,
        "workbench_tasks": 2,
        "workbench_audit_events": 2,
        "workbench_plan_proposals": 1,
        "workbench_orchestration_proposals": 1,
    }
    # 复清幂等：整层已空 ⇒ 全零。
    assert set(store.purge_all_for_tenant(TENANT).values()) == {0}


def test_batching_converges_even_with_limit_one(connection) -> None:
    """`limit=1`（每轮每面仅删 1 行）仍把两层清空 —— 证明分批循环真的收敛，而不是只删一轮。"""
    _seed(connection, TENANT, "batched")
    store = PostgresRetentionPurgeStore(connection)

    counts = store.purge_all_for_tenant(TENANT, limit=1)

    assert counts["runs"] == 2 and counts["tasks"] == 2, "两轮以上才可能清完 2 条任务 / 2 条运行"
    assert set(_counts(connection, TENANT).values()) == {0}


def test_delete_all_for_tenant_alias_returns_total_rows(connection) -> None:
    _seed(connection, TENANT, "alias")
    store = PostgresRetentionPurgeStore(connection)

    deleted = store.delete_all_for_tenant(TENANT)

    # 逐表种子行数（不含执行幂等，本用例未种）：任务 2 + 运行 2 + 子表 2×5 + 运行事件 2 + 提案 2 = **18**。
    # ⚠️ 任务域事件流（`audit_events` 2 行）由**级联**消失，**不计入**本返回值 —— 返回值是「本原语显式删的行数」，
    # 不拿级联充数（级联删除由 `test_whole_...` 的逐表归零断言覆盖）。
    assert deleted == 18, "别名必须返回本原语显式删除的行数之和（不拿「调用成功」当计数、不含级联行）"
    assert set(_counts(connection, TENANT).values()) == {0}


def test_service_delete_reports_and_clears_the_task_and_run_face(connection) -> None:
    _seed(connection, TENANT, "e2e")
    audit = AuditService(PostgresAuditStore(connection))
    service = CommercialLifecycleService(
        PostgresCommercialRepository(connection),
        job_store=PostgresLifecycleJobStore(connection),
        retention_store=PostgresRetentionPolicyStore(connection),
        export_store=PostgresExportPackageStore(connection),
        audit=audit,
        retention_purge_store=PostgresRetentionPurgeStore(connection),
    )
    job = service.job_store.create(
        LifecycleJob(
            tenant_id=TENANT,
            kind="delete",
            status="cooling_down",
            requested_by="admin-b23",
            execute_after=NOW,
            final_exported=True,
            confirmed_by="admin-b23",
            confirmed_at=NOW,
        )
    )

    service.execute_delete(TENANT, now=NOW)

    assert set(_counts(connection, TENANT).values()) == {0}
    records, total = audit.store.query(TENANT, actions=[AuditAction.COMMERCIAL_DELETION_EXECUTED])
    assert total == 1
    assert records[0].detail["cleared_categories"] == ["tasks_and_runs"]
    assert service.get_job(job.id).status == "completed"