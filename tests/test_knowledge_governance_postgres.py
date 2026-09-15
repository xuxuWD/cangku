"""`PostgresKnowledgeGovStore` 的**真库**回归（知识治理层，迁移 032）。

口径（沿用 `tests/test_commercial_lifecycle_postgres.py` / `tests/test_skills_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**。
  - 目标库必须是**已完成全部迁移（含 032）**的库；本文件**不建表、不迁移**。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清。

重点验证（规格 §3 + 反假）：
  1. `workbench_knowledge_documents` 表真库可写读（状态机约束 CHECK 拦截非法值）。
  2. 状态机流转变更真库持久化（draft→published→needs_review→published/archived）。
  3. `list_published_eligible` 谓词守卫真库语义：published 且未过 review_due_at 才可见。
  4. `list_needs_review` / `mark_review_due` 到期扫描候选真库可用。
  5. 生命周期 `list_all_for_tenant` / `delete_all_for_tenant` 真库可跑。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import UserContext
from app.knowledge_governance.models import KnowledgeDocStatus
from app.knowledge_governance.service import KnowledgeGovernanceService
from app.knowledge_governance.store import PostgresKnowledgeGovStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-knowledge-gov-pg"
ADMIN = "acct-pg-admin"


@pytest.fixture()
def service():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    store = PostgresKnowledgeGovStore(connection)
    # N7 裁决 B：系统扫描在未注入 audit 时 fail-closed ⇒ 真库 fixture 注入内存审计（审计落库由其它用例覆盖）。
    svc = KnowledgeGovernanceService(
        store, audit=AuditService(InMemoryAuditStore()), review_grace_days=30
    )
    yield svc, connection
    _purge(connection)
    connection.close()


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_knowledge_documents WHERE tenant_id = %s", (TENANT,))


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


# ------------------------------------------------------------ 表结构与持久化

def test_register_and_status_flow_persists_in_postgres(service) -> None:
    svc, connection = service
    svc.register_document(
        _admin(), document_id="pg-doc-1", title="真库文档", owner_id="acct-owner",
        version="1", source_key="manual",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, owner_id, source_key FROM workbench_knowledge_documents "
            "WHERE tenant_id = %s AND document_id = %s",
            (TENANT, "pg-doc-1"),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row[0] == "draft"
    assert row[1] == "acct-owner"
    assert row[2] == "manual"

    # 状态机流转变更真库持久化
    svc.publish_document(_admin(), "pg-doc-1", owner_id="acct-owner")
    # N6 裁决 A（2026-09-15）：发布即置 review_due_at（首轮复核周期开始）——真库读回验证
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, last_reviewed_at, review_due_at FROM workbench_knowledge_documents "
            "WHERE tenant_id = %s AND document_id = %s",
            (TENANT, "pg-doc-1"),
        )
        row = cursor.fetchone()
    assert row[0] == "published"
    assert row[1] is not None
    assert row[2] is not None, "发布必须置 review_due_at（N6 裁决 A）"
    assert row[2] > row[1], "首轮到期日必须晚于发布时刻"
    svc.store.update_status(_admin(), "pg-doc-1", new_status=KnowledgeDocStatus.NEEDS_REVIEW)
    reviewed = svc.review_document(_admin(), "pg-doc-1", approved=True)
    assert reviewed.status is KnowledgeDocStatus.PUBLISHED
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, last_reviewed_at FROM workbench_knowledge_documents "
            "WHERE tenant_id = %s AND document_id = %s",
            (TENANT, "pg-doc-1"),
        )
        row = cursor.fetchone()
    assert row[0] == "published"
    assert row[1] is not None


def test_draft_can_be_archived_directly(service) -> None:
    """§2.2 口径裁定（2026-09-15）：**draft 可直接归档**（any→archived），真库持久化。"""
    svc, connection = service
    svc.register_document(
        _admin(), document_id="pg-draft-archive", title="未发布即判废", owner_id="",
        version="1", source_key="manual",
    )
    archived = svc.archive_document(_admin(), "pg-draft-archive")
    assert archived.status is KnowledgeDocStatus.ARCHIVED
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM workbench_knowledge_documents WHERE tenant_id = %s AND document_id = %s",
            (TENANT, "pg-draft-archive"),
        )
        assert cursor.fetchone()[0] == "archived"


def test_worker_scan_across_tenants_on_postgres(service) -> None:
    """N3 真库：跨租户候选 SQL（唯一跨租户查询）一次扫描两个租户的到期文档，写回逐条带租户。"""
    svc, connection = service
    other = "test-knowledge-gov-pg-b"
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_knowledge_documents WHERE tenant_id = %s", (other,))
    try:
        now = datetime.now(UTC)
        seeds = (
            (TENANT, "pg-w-a", -1),  # 到期
            (other, "pg-w-b", -2),  # 到期（另一租户）
            (TENANT, "pg-w-future", +1),  # 未到期
        )
        for tenant_id, doc_id, delta_days in seeds:
            ctx = UserContext(tenant_id, ADMIN, "super_admin")
            svc.register_document(
                ctx, document_id=doc_id, title=doc_id, owner_id="acct-owner",
                version="1", source_key="manual",
            )
            svc.publish_document(ctx, doc_id, owner_id="acct-owner")
            svc.store.update_status(
                ctx, doc_id, new_status=KnowledgeDocStatus.PUBLISHED,
                review_due_at=now + timedelta(days=delta_days),
            )

        result = svc.scan_review_due_across_tenants(now=now)
        assert result == {"candidates": 2, "flipped": 2}

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id, document_id, status FROM workbench_knowledge_documents "
                "WHERE document_id IN (%s, %s, %s) ORDER BY tenant_id, document_id",
                ("pg-w-a", "pg-w-b", "pg-w-future"),
            )
            rows = [tuple(row) for row in cursor.fetchall()]
        assert rows == [
            (TENANT, "pg-w-a", "needs_review"),
            (TENANT, "pg-w-future", "published"),
            (other, "pg-w-b", "needs_review"),
        ]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM workbench_knowledge_documents WHERE tenant_id = %s", (other,))


def test_import_register_script_against_postgres(service) -> None:
    """N1 真库：导入脚本经服务层闸门写 `draft` + `source_key='migration'` + owner 留空；重复导入幂等。"""
    svc, connection = service
    from scripts.knowledge_import_register import IMPORT_SOURCE_KEY, ImportEntry, run_import

    entries = [ImportEntry("pg-imp-1", title="存量一", version="2"), ImportEntry("pg-imp-2")]
    report = run_import(svc, _admin(), entries, apply=True)
    assert report.created == ("pg-imp-1", "pg-imp-2")
    assert report.rejected == ()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT document_id, status, source_key, owner_id, version "
            "FROM workbench_knowledge_documents "
            "WHERE tenant_id = %s AND document_id IN (%s, %s) ORDER BY document_id",
            (TENANT, "pg-imp-1", "pg-imp-2"),
        )
        rows = [tuple(row) for row in cursor.fetchall()]
    assert rows == [
        ("pg-imp-1", "draft", IMPORT_SOURCE_KEY, "", "2"),
        ("pg-imp-2", "draft", IMPORT_SOURCE_KEY, "", "1"),
    ]

    # 幂等：重复导入全部 skipped
    second = run_import(svc, _admin(), entries, apply=True)
    assert second.created == ()
    assert second.skipped == ("pg-imp-1", "pg-imp-2")


def test_check_constraint_forbids_illegal_status(service) -> None:
    """CHECK 约束：非法状态值直接落库失败（status IN 白名单）。"""
    svc, connection = service
    with pytest.raises(Exception):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO workbench_knowledge_documents "
                "(tenant_id, document_id, title, owner_id, status, version, source_key, registered_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (TENANT, "pg-bad-status", "非法状态", "o", "evil_status", "1", "manual", ADMIN),
            )


# ------------------------------------------------------------ 谓词守卫（真库语义）

def test_eligible_only_published_and_not_expired(service) -> None:
    svc, connection = service
    svc.register_document(
        _admin(), document_id="pg-ok", title="正常", owner_id="acct-owner",
        version="1", source_key="manual",
    )
    svc.register_document(
        _admin(), document_id="pg-draft", title="未发布", owner_id="acct-owner",
        version="1", source_key="manual",
    )
    svc.publish_document(_admin(), "pg-ok", owner_id="acct-owner")

    now = datetime.now(UTC)
    ids = {d.document_id for d in svc.store.list_published_eligible(_admin(), now=now)}
    # draft 不出现；published 未过期出现
    assert "pg-ok" in ids
    assert "pg-draft" not in ids

    # published + 已过 review_due_at → 从谓词下线（视为过期）
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE workbench_knowledge_documents SET review_due_at = %s "
            "WHERE tenant_id = %s AND document_id = %s",
            (now - timedelta(days=1), TENANT, "pg-ok"),
        )
    ids = {d.document_id for d in svc.store.list_published_eligible(_admin(), now=now)}
    assert "pg-ok" not in ids


def test_mark_review_due_and_scan(service) -> None:
    svc, connection = service
    svc.register_document(
        _admin(), document_id="pg-due", title="到期", owner_id="acct-owner",
        version="1", source_key="manual",
    )
    svc.publish_document(_admin(), "pg-due", owner_id="acct-owner")
    # 手动把 review_due_at 置为过去 → 扫描候选
    past = datetime.now(UTC) - timedelta(days=5)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE workbench_knowledge_documents SET review_due_at = %s "
            "WHERE tenant_id = %s AND document_id = %s",
            (past, TENANT, "pg-due"),
        )
    candidates = svc.store.list_needs_review(_admin(), now=datetime.now(UTC))
    assert any(d.document_id == "pg-due" for d in candidates)

    updated = svc.store.mark_review_due(_admin(), "pg-due", now=datetime.now(UTC))
    assert updated is not None
    assert updated.status is KnowledgeDocStatus.NEEDS_REVIEW

    # 重复扫描：已 needs_review 不再进候选
    assert svc.scan_review_due(_admin()) == 0


# ------------------------------------------------------------ 生命周期（对称 P3/P4 N2）

def test_lifecycle_list_and_delete_for_tenant(service) -> None:
    svc, connection = service
    svc.register_document(
        _admin(), document_id="pg-lc", title="生命周期", owner_id="acct-owner",
        version="1", source_key="manual",
    )
    listed = svc.store.list_all_for_tenant(TENANT)
    assert len(listed) >= 1
    deleted = svc.store.delete_all_for_tenant(TENANT)
    assert deleted >= 1
    assert svc.store.list_all_for_tenant(TENANT) == []