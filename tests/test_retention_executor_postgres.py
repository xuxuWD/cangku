"""保留策略执行器的**真库**语义（B-4 选项 C，2026-09-19）。

覆盖四类**只有真库才能证伪**的性质（单元测不了 FK 与谓词）：
  1. 账本**结转恒等式**：真库 `SUM` 前后逐分不变（含**过期冲正对**这一错位情形）+ 结转行内容 + 同
     `cutoff` 重放幂等 + 迟到过期行并入净额；
  2. 运行域**先子后父**：7 张表一趟清（漏一张子表 ⇒ 外键直接拒删父行）、新鲜运行不受影响；
  3. 任务域**防孤儿谓词**：有未过期运行的任务本轮跳过，其运行过期后下一轮可删；任务审计事件随之级联；
  4. `events` / `audit` 两面**不被本执行器触碰**（运行事件与审计日志原样留存）；提案域按龄删而
     `workbench_plan_versions`（商业化套餐版本目录）**永不删**。

口径（沿用 `tests/test_commercial_lifecycle_postgres.py` 先例）：
  - DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；**未设置即整体 skip**；目标库须已完成全部迁移
    （含 006/007/027/037/040/042）；本文件**不建表、不迁移**，缺表显式失败；
  - 只操作本文件的两个固定租户，用例前后按外键逆序自清。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.models import AuditAction
from app.commercial.retention import PostgresRetentionPurgeStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-retention-pg"
OTHER = "test-retention-pg-other"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=180)
USAGE_CUTOFF = NOW - timedelta(days=365)

# 清理顺序 = 外键逆序（幂等行引用会话 / 消息 / 运行，必须先删）。
_CLEANUP_STATEMENTS: tuple[str, ...] = (
    "DELETE FROM workbench_run_artifacts WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_run_acceptance_decisions WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_run_promotions WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_tool_actions WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_execution_idempotency WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_runtime_states WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_runtime_events WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_run_records WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_audit_events WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_tasks WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_plan_proposals WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_orchestration_proposals WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_plan_versions WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_usage_ledger WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_audit_log WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_retention_policies WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_lifecycle_jobs WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_conversation_messages WHERE tenant_id = ANY(%s)",
    "DELETE FROM workbench_conversations WHERE tenant_id = ANY(%s)",
)


def _clean(connection) -> None:
    tenants = [TENANT, OTHER]
    with connection.cursor() as cursor:
        for statement in _CLEANUP_STATEMENTS:
            cursor.execute(statement, (tenants,))


@pytest.fixture()
def connection():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _clean(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'active') "
            "ON CONFLICT (id) DO NOTHING",
            (TENANT, "客户保留", "owner-retention"),
        )
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'active') "
            "ON CONFLICT (id) DO NOTHING",
            (OTHER, "客户保留乙", "owner-retention-2"),
        )
    yield connection
    _clean(connection)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_tenants WHERE id = ANY(%s)", ([TENANT, OTHER],))
    connection.close()


def _count(connection, table: str, run_id: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s AND run_id = %s", (TENANT, run_id))
        return int(cursor.fetchone()[0])


def _seed_run(connection, run_id: str, *, started_at: datetime, task_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status, started_at)
            VALUES (%s, %s, %s, 'mock', 'completed', %s)
            """,
            (run_id, TENANT, task_id, started_at),
        )


def _seed_run_children(connection, run_id: str, task_id: str) -> None:
    """给该运行写满**全部**子表行（含幂等行所需的会话前置）。"""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_run_artifacts (tenant_id, run_id, artifact_id, virtual_path, change_kind, bytes, sha256, created_at) "
            "VALUES (%s, %s, %s, '/workspace/a.txt', 'created', 3, 'sha256:aaa', %s)",
            (TENANT, run_id, f"art-{run_id}", NOW),
        )
        cursor.execute(
            "INSERT INTO workbench_run_acceptance_decisions (tenant_id, run_id, decision_id, decision, reason, idempotency_key, decided_by, decided_by_role, structural_verdict, created_at) "
            "VALUES (%s, %s, %s, 'confirmed', '', %s, 'admin', 'customer_admin', 'met', %s)",
            (TENANT, run_id, f"dec-{run_id}", f"idem-dec-{run_id}", NOW),
        )
        cursor.execute(
            "INSERT INTO workbench_run_promotions (tenant_id, run_id, task_id, title, promoted_by, created_at) "
            "VALUES (%s, %s, %s, '沉淀标题', 'admin', %s)",
            (TENANT, run_id, task_id, NOW),
        )
        cursor.execute(
            "INSERT INTO workbench_tool_actions (tenant_id, action_id, run_id, task_id, step_id, tool_key, args_digest, args_json, plan_digest, risk_level, requires_approval, status, requested_by, requested_at, decided_by, decided_at) "
            "VALUES (%s, %s, %s, %s, 'step-1', 'shell', 'digest', '{}'::jsonb, 'plan', 'low', false, 'approved', 'admin', %s, 'admin', %s)",
            (TENANT, f"act-{run_id}", run_id, task_id, NOW, NOW),
        )
        cursor.execute(
            "INSERT INTO workbench_conversations (tenant_id, conversation_id, operator_id, status) VALUES (%s, %s, 'admin', 'active') "
            "ON CONFLICT (tenant_id, conversation_id) DO NOTHING",
            (TENANT, f"conv-{run_id}"),
        )
        cursor.execute(
            "INSERT INTO workbench_execution_idempotency (tenant_id, actor_id, conversation_id, idempotency_key, message_id, run_id, approval_id, outcome, http_status, created_at) "
            "VALUES (%s, 'admin', %s, %s, NULL, %s, NULL, 'pending_approval', 202, %s)",
            (TENANT, f"conv-{run_id}", f"idem-exec-{run_id}", run_id, NOW),
        )
        cursor.execute(
            "INSERT INTO workbench_runtime_states (run_id, tenant_id, task_id, status, context, plan, created_at, updated_at) "
            "VALUES (%s, %s, %s, 'completed', '{}'::jsonb, '{}'::jsonb, %s, %s)",
            (run_id, TENANT, task_id, NOW, NOW),
        )


# ---------------------------------------------------------------- 账本结转（真库恒等式）


def test_carry_over_keeps_sum_cent_exact_and_marks_the_row(connection) -> None:
    from app.commercial.usage import (
        CARRYOVER_REASON,
        PostgresUsageLedger,
        UsageEntry,
        carryover_idempotency_key,
    )

    ledger = PostgresUsageLedger(connection)
    expired_at = NOW - timedelta(days=500)
    ledger.append(UsageEntry(idempotency_key="old-1", tenant_id=TENANT, units=100, cost_cents=250, occurred_at=expired_at))
    ledger.append(UsageEntry(idempotency_key="old-2", tenant_id=TENANT, units=50, cost_cents=125, occurred_at=expired_at))
    # **过期冲正对**：原件与冲正行都在窗口外（接口层做不出这种形态，直接落库构造）。
    ledger.append(UsageEntry(idempotency_key="old-3", tenant_id=TENANT, units=30, cost_cents=75, occurred_at=expired_at))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_usage_ledger (id, tenant_id, idempotency_key, units, cost_cents, reversal_of, occurred_at) "
            "SELECT 'usage-rev-old', tenant_id, 'reversal:old-3', -units, -cost_cents, id, %s FROM workbench_usage_ledger "
            "WHERE tenant_id = %s AND idempotency_key = 'old-3'",
            (expired_at, TENANT),
        )
    ledger.append(UsageEntry(idempotency_key="fresh", tenant_id=TENANT, units=7, cost_cents=3, occurred_at=NOW - timedelta(days=1)))

    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    result = ledger.carry_over_before(TENANT, cutoff=USAGE_CUTOFF)

    assert result == {"rows": 4, "units": 150, "cost_cents": 375}, "过期集合含冲正对 ⇒ 净额按对求和"
    assert (ledger.total(TENANT), ledger.total_cost_cents(TENANT)) == (units_before, cents_before)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT units, cost_cents, reversal_of, reason, actor_id, occurred_at, idempotency_key "
            "FROM workbench_usage_ledger WHERE tenant_id = %s AND reason = %s",
            (TENANT, CARRYOVER_REASON),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM workbench_usage_ledger WHERE tenant_id = %s", (TENANT,))
        total_rows = int(cursor.fetchone()[0])

    assert len(rows) == 1, "结转行必须恰好一行"
    assert total_rows == 2, "结转后应剩「结转行 + 窗口内明细」两行"
    units, cost_cents, reversal_of, reason, actor_id, occurred_at, key = rows[0]
    assert (int(units), int(cost_cents)) == (150, 375)
    assert reversal_of is None and reason == CARRYOVER_REASON and actor_id == "system:worker"
    assert occurred_at == USAGE_CUTOFF
    assert key == carryover_idempotency_key(USAGE_CUTOFF)


def test_carry_over_replay_and_late_row_absorption_on_real_db(connection) -> None:
    from app.commercial.usage import CARRYOVER_REASON, PostgresUsageLedger, UsageEntry

    ledger = PostgresUsageLedger(connection)
    ledger.append(
        UsageEntry(
            idempotency_key="old",
            tenant_id=TENANT,
            units=9,
            cost_cents=11,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    first = ledger.carry_over_before(TENANT, cutoff=USAGE_CUTOFF)
    second = ledger.carry_over_before(TENANT, cutoff=USAGE_CUTOFF)

    assert first == {"rows": 1, "units": 9, "cost_cents": 11}
    assert second == {"rows": 0, "units": 0, "cost_cents": 0}

    # 迟到行：业务时间在截止时刻之前、写入时刻在首轮之后 ⇒ 并入既有结转行（累加），总额不变。
    ledger.append(
        UsageEntry(
            idempotency_key="late",
            tenant_id=TENANT,
            units=4,
            cost_cents=6,
            occurred_at=USAGE_CUTOFF - timedelta(days=1),
        )
    )
    before_units, before_cents = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    third = ledger.carry_over_before(TENANT, cutoff=USAGE_CUTOFF)

    assert third == {"rows": 1, "units": 4, "cost_cents": 6}
    assert (ledger.total(TENANT), ledger.total_cost_cents(TENANT)) == (before_units, before_cents)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT units, cost_cents FROM workbench_usage_ledger WHERE tenant_id = %s AND reason = %s",
            (TENANT, CARRYOVER_REASON),
        )
        rows = cursor.fetchall()
    assert [(int(row[0]), int(row[1])) for row in rows] == [(13, 17)]


# ---------------------------------------------------------------- 运行域先子后父


def test_run_domain_is_purged_child_first_and_fresh_runs_survive(connection) -> None:
    store = PostgresRetentionPurgeStore(connection)
    task_id = "task-old-runs"
    _seed_task(connection, task_id, created_at=NOW - timedelta(days=300))
    _seed_run(connection, "run-expired", started_at=NOW - timedelta(days=200), task_id=task_id)
    _seed_run_children(connection, "run-expired", task_id)
    _seed_run(connection, "run-fresh", started_at=NOW - timedelta(days=2), task_id=task_id)
    _seed_run_children(connection, "run-fresh", task_id)
    # 运行事件与审计日志：属 `events` / `audit` 两面 ⇒ 本执行器**不得触碰**。
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_runtime_events (run_id, tenant_id, sequence, event_type, occurred_at) "
            "VALUES ('run-expired', %s, 1, 'step.started', %s)",
            (TENANT, NOW - timedelta(days=200)),
        )
        cursor.execute(
            "INSERT INTO workbench_audit_log (action, tenant_id, occurred_at) VALUES ('test.legacy', %s, %s)",
            (TENANT, NOW - timedelta(days=400)),
        )

    counts = store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)

    assert counts["runs"] == 1
    assert counts["run_artifacts"] == 1
    assert counts["run_acceptance_decisions"] == 1
    assert counts["run_promotions"] == 1
    assert counts["tool_actions"] == 1
    assert counts["execution_idempotency"] == 1
    assert counts["runtime_states"] == 1
    for table in (
        "workbench_run_artifacts",
        "workbench_run_acceptance_decisions",
        "workbench_run_promotions",
        "workbench_tool_actions",
        "workbench_execution_idempotency",
        "workbench_runtime_states",
    ):
        assert _count(connection, table, "run-expired") == 0, f"{table} 未清干净"
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_run_records WHERE tenant_id = %s AND run_id = 'run-expired'", (TENANT,))
        assert int(cursor.fetchone()[0]) == 0

    # 新鲜运行与其子行、以及 events / audit 两面原样留存。
    for table in (
        "workbench_run_artifacts",
        "workbench_run_acceptance_decisions",
        "workbench_run_promotions",
        "workbench_tool_actions",
        "workbench_execution_idempotency",
        "workbench_runtime_states",
    ):
        assert _count(connection, table, "run-fresh") == 1, f"{table} 误删了新鲜运行的行"
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_run_records WHERE tenant_id = %s AND run_id = 'run-fresh'", (TENANT,))
        assert int(cursor.fetchone()[0]) == 1
        cursor.execute("SELECT COUNT(*) FROM workbench_runtime_events WHERE tenant_id = %s AND run_id = 'run-expired'", (TENANT,))
        assert int(cursor.fetchone()[0]) == 1, "运行事件属 events 面：本执行器不得删除"
        cursor.execute("SELECT COUNT(*) FROM workbench_audit_log WHERE tenant_id = %s AND action = 'test.legacy'", (TENANT,))
        assert int(cursor.fetchone()[0]) == 1, "审计面永不删除"


# ---------------------------------------------------------------- 任务域防孤儿谓词


def test_task_with_any_unexpired_run_is_skipped_then_deleted_next_round(connection) -> None:
    store = PostgresRetentionPurgeStore(connection)
    _seed_task(connection, "task-guarded", created_at=NOW - timedelta(days=300))
    _seed_run(connection, "run-young", started_at=NOW - timedelta(days=5), task_id="task-guarded")
    _seed_task(connection, "task-full-expired", created_at=NOW - timedelta(days=300))
    _seed_run(connection, "run-old", started_at=NOW - timedelta(days=200), task_id="task-full-expired")
    _seed_task(connection, "task-no-runs", created_at=NOW - timedelta(days=300))
    _seed_task(connection, "task-fresh", created_at=NOW - timedelta(days=3))

    counts = store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)

    assert counts["tasks"] == 2, "只应删「运行全部过期」与「无运行」的两条"
    assert _task_exists(connection, "task-guarded") is True, "有未过期运行 ⇒ 本轮必须跳过（防孤儿运行）"
    assert _task_exists(connection, "task-full-expired") is False
    assert _task_exists(connection, "task-no-runs") is False
    assert _task_exists(connection, "task-fresh") is True

    # 运行过期后下一轮即可删（谓词按当轮重新求值）。
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE workbench_run_records SET started_at = %s WHERE tenant_id = %s AND run_id = 'run-young'",
            (NOW - timedelta(days=200), TENANT),
        )
    second = store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)
    assert second["runs"] == 1 and second["tasks"] == 1
    assert _task_exists(connection, "task-guarded") is False


def test_task_audit_events_cascade_with_the_deleted_task(connection) -> None:
    store = PostgresRetentionPurgeStore(connection)
    _seed_task(connection, "task-with-audit", created_at=NOW - timedelta(days=300))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_audit_events (task_id, tenant_id, action, actor_id, actor_role) "
            "VALUES ('task-with-audit', %s, 'task.created', 'admin', 'employee')",
            (TENANT,),
        )

    store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM workbench_audit_events WHERE tenant_id = %s AND task_id = 'task-with-audit'",
            (TENANT,),
        )
        assert int(cursor.fetchone()[0]) == 0, "任务域事件流随任务级联删除（已裁决接受的代价）"


# ---------------------------------------------------------------- 提案域与套餐版本目录


def test_proposals_purged_by_age_but_commercial_plan_versions_kept(connection) -> None:
    store = PostgresRetentionPurgeStore(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_plan_proposals (proposal_id, task_id, tenant_id, goal, steps, generator_key, created_by, idempotency_key, status, created_at) "
            "VALUES ('prop-old', 'task-x', %s, '目标', '[]'::jsonb, 'mock', 'admin', 'idem-prop-old', 'pending_review', %s)",
            (TENANT, NOW - timedelta(days=300)),
        )
        cursor.execute(
            "INSERT INTO workbench_plan_proposals (proposal_id, task_id, tenant_id, goal, steps, generator_key, created_by, idempotency_key, status, created_at) "
            "VALUES ('prop-fresh', 'task-y', %s, '目标', '[]'::jsonb, 'mock', 'admin', 'idem-prop-fresh', 'pending_review', %s)",
            (TENANT, NOW - timedelta(days=1)),
        )
        cursor.execute(
            "INSERT INTO workbench_orchestration_proposals (proposal_id, tenant_id, kind, current_value, proposed_value, rationale, status, created_by, created_at) "
            "VALUES ('orch-old', %s, 'autonomy', 'a', 'b', 'r', 'pending_review', 'admin', %s)",
            (TENANT, NOW - timedelta(days=300)),
        )
        cursor.execute(
            "INSERT INTO workbench_orchestration_proposals (proposal_id, tenant_id, kind, current_value, proposed_value, rationale, status, created_by, created_at) "
            "VALUES ('orch-fresh', %s, 'autonomy', 'a', 'b', 'r', 'pending_review', 'admin', %s)",
            (TENANT, NOW - timedelta(days=1)),
        )
        cursor.execute(
            "INSERT INTO workbench_plan_versions (tenant_id, plan_key, version, limits, effective_at) "
            "VALUES (%s, 'standard', 1, '{}'::jsonb, %s) ON CONFLICT DO NOTHING",
            (TENANT, NOW - timedelta(days=500)),
        )

    counts = store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)

    assert counts["plan_proposals"] == 1 and counts["orchestration_proposals"] == 1
    with connection.cursor() as cursor:
        cursor.execute("SELECT proposal_id FROM workbench_plan_proposals WHERE tenant_id = %s ORDER BY proposal_id", (TENANT,))
        assert [row[0] for row in cursor.fetchall()] == ["prop-fresh"]
        cursor.execute("SELECT proposal_id FROM workbench_orchestration_proposals WHERE tenant_id = %s ORDER BY proposal_id", (TENANT,))
        assert [row[0] for row in cursor.fetchall()] == ["orch-fresh"]
        cursor.execute("SELECT COUNT(*) FROM workbench_plan_versions WHERE tenant_id = %s", (TENANT,))
        assert int(cursor.fetchone()[0]) == 1, "商业化套餐版本目录不是运行期数据 ⇒ 永不按龄清理"


def test_purge_is_scoped_to_the_target_tenant(connection) -> None:
    store = PostgresRetentionPurgeStore(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'active') "
            "ON CONFLICT (id) DO NOTHING",
            (OTHER, "客户保留乙", "owner-retention-2"),
        )
        cursor.execute(
            "INSERT INTO workbench_tasks (id, tenant_id, project_id, created_by, employee_key, title, risk_level, budget_cents, idempotency_key, request_fingerprint, status, created_at) "
            "VALUES ('task-other', %s, NULL, 'user-1', 'employee-key', '他租户旧任务', 'low', 0, 'idem-other', 'fp-other', 'queued', %s)",
            (OTHER, NOW - timedelta(days=300)),
        )

    counts = store.purge_expired_for_tenant(TENANT, cutoff=CUTOFF)

    assert counts["tasks"] == 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_tasks WHERE tenant_id = %s AND id = 'task-other'", (OTHER,))
        assert int(cursor.fetchone()[0]) == 1, "清理必须以租户为界，绝不跨租户"


# ---------------------------------------------------------------- 服务层端到端（真库）


def test_service_end_to_end_writes_audit_and_is_stable_on_replay(connection) -> None:
    from app.audit.service import AuditService
    from app.audit.store import PostgresAuditStore
    from app.commercial.lifecycle import (
        CommercialLifecycleService,
        PostgresExportPackageStore,
        PostgresLifecycleJobStore,
        PostgresRetentionPolicyStore,
    )
    from app.commercial.repository import PostgresCommercialRepository
    from app.commercial.usage import PostgresUsageLedger, UsageEntry

    audit_store = PostgresAuditStore(connection)
    service = CommercialLifecycleService(
        PostgresCommercialRepository(connection),
        job_store=PostgresLifecycleJobStore(connection),
        retention_store=PostgresRetentionPolicyStore(connection),
        export_store=PostgresExportPackageStore(connection),
        audit=AuditService(audit_store),
        usage_ledger=PostgresUsageLedger(connection),
        retention_purge_store=PostgresRetentionPurgeStore(connection),
    )
    ledger = PostgresUsageLedger(connection)
    ledger.append(
        UsageEntry(
            idempotency_key="old-usage",
            tenant_id=TENANT,
            units=12,
            cost_cents=34,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    _seed_task(connection, "task-e2e", created_at=NOW - timedelta(days=300))
    _seed_run(connection, "run-e2e", started_at=NOW - timedelta(days=200), task_id="task-e2e")
    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    result = service.purge_expired_data_for_tenant(TENANT, now=NOW)

    assert result["runs_deleted"] == 1 and result["tasks_deleted"] == 1
    assert result["usage_rows_deleted"] == 1 and result["usage_carried_cents"] == 34
    assert (ledger.total(TENANT), ledger.total_cost_cents(TENANT)) == (units_before, cents_before)
    records, total = audit_store.query(TENANT, actions=[AuditAction.COMMERCIAL_RETENTION_PURGED])
    assert total == 1
    assert records[0].detail["runs_deleted"] == 1
    assert records[0].detail["usage_carried_cents"] == 34
    assert records[0].actor_id == "system:worker"

    # 重放：本轮已无过期数据 ⇒ 零值且**不重复写审计**（空转不落审计）。
    replay = service.purge_expired_data_for_tenant(TENANT, now=NOW)
    assert replay == {
        "runs_deleted": 0,
        "run_domain_deleted": 0,
        "tasks_deleted": 0,
        "proposals_deleted": 0,
        "usage_rows_deleted": 0,
        "usage_carried_units": 0,
        "usage_carried_cents": 0,
    }
    _records, total_after = audit_store.query(TENANT, actions=[AuditAction.COMMERCIAL_RETENTION_PURGED])
    assert total_after == 1


def _seed_task(connection, task_id: str, *, created_at: datetime, tenant_id: str = TENANT) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_tasks
                (id, tenant_id, project_id, created_by, employee_key, title, risk_level, budget_cents,
                 idempotency_key, request_fingerprint, status, created_at)
            VALUES (%s, %s, NULL, 'user-1', 'employee-key', '旧任务', 'low', 0, %s, %s, 'queued', %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (task_id, tenant_id, f"idem-{task_id}", f"fp-{task_id}", created_at),
        )


def _task_exists(connection, task_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_tasks WHERE tenant_id = %s AND id = %s", (TENANT, task_id))
        return int(cursor.fetchone()[0]) == 1