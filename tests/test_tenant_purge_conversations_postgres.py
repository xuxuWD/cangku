"""B1 会话层租户清场的**真库**语义（2026-09-19 清场扩围）。

只有真库能证伪的性质：
  1. **整层六张表**一趟清（`execution_idempotency` → 流帧 → 流态 → 成员 → 消息 → 会话），
     且**顺序不可换**——先删会话行会被外键直接拒绝（本文件把「为什么是这个顺序」写成可执行断言）；
  2. **他租户零影响**（逐表对照）；
  3. 组合仓储返回的行数 = 逐表实际删除行数（不拿「调用成功」当计数）；
  4. 生命周期服务端到端：`execute_delete` 后审计 `cleared_categories` 含 `conversations`、逐表归零。

口径（沿用既有真库用例先例）：DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip；
目标库须已完成全部迁移（023/036/039/027）；本文件**不建表、不迁移**，缺表显式失败。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

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
from app.conversation.purge import PostgresConversationLayerPurgeStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-b1-purge"
OTHER = "test-b1-purge-other"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

# 六张表（顺序 = 清场顺序）；逐表取证用。
LAYER_TABLES = (
    "workbench_execution_idempotency",
    "workbench_conversation_stream_frames",
    "workbench_conversation_stream_state",
    "workbench_conversation_members",
    "workbench_conversation_messages",
    "workbench_conversations",
)
ROWS_PER_TENANT = 6  # 幂等 1 + 帧 1 + 流态 1 + 成员 1 + 消息 1 + 会话 1


def _clean(connection) -> None:
    with connection.cursor() as cursor:
        for table in (
            "workbench_execution_idempotency",
            "workbench_conversation_stream_frames",
            "workbench_conversation_stream_state",
            "workbench_conversation_members",
            "workbench_conversation_messages",
            "workbench_conversations",
            "workbench_audit_log",
            "workbench_lifecycle_jobs",
        ):
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = ANY(%s)", ([TENANT, OTHER],))
        cursor.execute("DELETE FROM workbench_tenants WHERE id = ANY(%s)", ([TENANT, OTHER],))


@pytest.fixture()
def connection():
    psycopg_module = pytest.importorskip("psycopg")
    connection = psycopg_module.connect(DSN, autocommit=True)
    _clean(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'deleting')",
            (TENANT, "客户B1", "owner-b1"),
        )
        cursor.execute(
            "INSERT INTO workbench_tenants (id, name, owner_id, status) VALUES (%s, %s, %s, 'active')",
            (OTHER, "客户B1乙", "owner-b1-2"),
        )
    yield connection
    _clean(connection)
    connection.close()


def _seed(connection, tenant: str, suffix: str) -> None:
    """给该租户种满六张表各一行（幂等行的 `message_id` 留空，避免再依赖消息行）。"""
    conversation_id = f"conv-{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_conversations (tenant_id, conversation_id, operator_id, status) VALUES (%s, %s, 'user-b1', 'active')",
            (tenant, conversation_id),
        )
        cursor.execute(
            "INSERT INTO workbench_conversation_messages (tenant_id, message_id, conversation_id, role, content) VALUES (%s, %s, %s, 'user', '你好')",
            (tenant, f"msg-{suffix}", conversation_id),
        )
        cursor.execute(
            "INSERT INTO workbench_conversation_members (tenant_id, conversation_id, member_id, permission, added_by) VALUES (%s, %s, 'user-b1-2', 'read', 'user-b1')",
            (tenant, conversation_id),
        )
        cursor.execute(
            "INSERT INTO workbench_conversation_stream_frames (tenant_id, conversation_id, run_id, seq, kind, payload, is_terminal, created_at) "
            "VALUES (%s, %s, %s, 1, 'step.started', '{}'::jsonb, false, now())",
            (tenant, conversation_id, f"run-{suffix}"),
        )
        cursor.execute(
            "INSERT INTO workbench_conversation_stream_state (tenant_id, conversation_id, run_id, last_seq, frame_count, byte_count, is_terminal, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, 1, 2, false, 'streaming', now(), now())",
            (tenant, conversation_id, f"run-{suffix}"),
        )
        cursor.execute(
            "INSERT INTO workbench_execution_idempotency (tenant_id, actor_id, conversation_id, idempotency_key, message_id, run_id, approval_id, outcome, http_status, created_at) "
            "VALUES (%s, 'user-b1', %s, %s, NULL, NULL, NULL, 'pending_approval', 202, now())",
            (tenant, conversation_id, f"idem-{suffix}"),
        )


def _counts(connection, tenant: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in LAYER_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s", (tenant,))
            counts[table] = int(cursor.fetchone()[0])
    return counts


def test_layer_purge_empties_all_six_tables_and_spares_other_tenants(connection) -> None:
    _seed(connection, TENANT, "target")
    _seed(connection, OTHER, "other")
    assert set(_counts(connection, TENANT).values()) == {1}, "前提：目标租户六张表各一行"
    assert set(_counts(connection, OTHER).values()) == {1}, "前提：他租户六张表各一行"

    store = PostgresConversationLayerPurgeStore(connection)
    deleted = store.delete_all_for_tenant(TENANT)

    assert deleted == ROWS_PER_TENANT, "返回值必须是逐表实际删除行数之和"
    assert set(_counts(connection, TENANT).values()) == {0}, "整层六张表必须归零"
    # 他租户零影响：六张表行数原样。
    assert set(_counts(connection, OTHER).values()) == {1}
    # 幂等：重复清已空的租户返回 0，不报错。
    assert store.delete_all_for_tenant(TENANT) == 0


def test_deleting_the_parent_row_first_is_rejected_by_the_database(connection) -> None:
    """把「为什么必须先子后父」写成可执行事实：直接删会话行会被外键拒绝。

    依据：`workbench_conversation_messages` / `..._stream_frames` / `..._stream_state` /
    `workbench_execution_idempotency` 对会话行的外键**均无 `ON DELETE CASCADE`**（真库 `pg_constraint` 实测）。
    本用例若变绿（不再抛错），说明有人给这些外键加了级联或删了外键 ⇒ 清场顺序的前提变了，必须重审。
    """
    psycopg = pytest.importorskip("psycopg")
    _seed(connection, TENANT, "fk")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM workbench_conversations WHERE tenant_id = %s", (TENANT,))


def test_service_delete_reports_and_clears_the_conversation_face(connection) -> None:
    """端到端（真库）：`execute_delete` 清会话层 + 审计如实列面名 + 六表归零。"""
    _seed(connection, TENANT, "e2e")
    audit = AuditService(PostgresAuditStore(connection))
    service = CommercialLifecycleService(
        PostgresCommercialRepository(connection),
        job_store=PostgresLifecycleJobStore(connection),
        retention_store=PostgresRetentionPolicyStore(connection),
        export_store=PostgresExportPackageStore(connection),
        audit=audit,
        conversation_store=PostgresConversationLayerPurgeStore(connection),
    )
    job = service.job_store.create(
        LifecycleJob(
            tenant_id=TENANT,
            kind="delete",
            status="cooling_down",
            requested_by="admin-b1",
            execute_after=NOW,
            final_exported=True,
            confirmed_by="admin-b1",
            confirmed_at=NOW,
        )
    )

    service.execute_delete(TENANT, now=NOW)

    assert set(_counts(connection, TENANT).values()) == {0}
    records, total = audit.store.query(TENANT, actions=[AuditAction.COMMERCIAL_DELETION_EXECUTED])
    assert total == 1
    assert records[0].detail["cleared_categories"] == ["conversations"]
    assert service.get_job(job.id).status == "completed"