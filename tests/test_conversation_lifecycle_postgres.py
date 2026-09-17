"""P2c-4 **真库**回归：会话模式列、导出、物理删除（级联与保留）、审计不动。

口径：沿用 `tests/test_run_artifacts_postgres.py` 先例——
DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip；目标库须已完成全部迁移（含 `038`）；
本文件**不建表、不迁移**；只操作本文件声明的租户，用例前后自清。

覆盖规格 §4「P2c-4（产品项）真库用例」的库级部分：
  ① `mode` 列：存量默认 `craft`、受控取值（CHECK 拦非法值）、`set_mode` 落库；
  ② **物理删除**：消息 / 帧 / 流状态 / 幂等行计数为 0；会话行仍在（`deleted_at` 非空 + `title=''`）；
     幂等行**引用消息行**（复合外键）⇒ 删除必须「先删幂等行」（本用例即证）；
  ③ **保留不删**：运行记录 / 产物登记 / 审计行在删除后**仍在**（审计不含正文，且复删不新增审计）；
  ④ **复删幂等**：各计数为 0，且不再删除、不再写审计；
  ⑤ 归属：他人 / 跨租户删除一律「未找到」，且数据仍在；
  ⑥ **导出**：只含本人（跨租户与他人不可见）、含归档、分页 `limit`/`offset` 生效、
     **上限如实告知**（注入小上限 ⇒ `truncated` + `limit_reason`，不静默截断）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import PostgresAuditStore
from app.conversation.idempotency import ExecutionIdempotencyRecord, PostgresExecutionIdempotencyStore
from app.conversation.models import ConversationNotFound, ConversationStatus
from app.conversation.service import MAX_EXPORT_ITEMS, EXPORT_LIMIT_REASON, ConversationService
from app.conversation.store import PostgresConversationStore
from app.conversation.stream import PostgresStreamStore
from app.domain import UserContext

DSN = __import__("os").environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-lifecycle-pg"
TENANT_OTHER = "test-lifecycle-pg-other"
OWNER = "u-owner"
OTHER = "u-other"
RUN = "run-lifecycle-1"
RUN_OTHER = "run-lifecycle-other"


def _run_id(tenant: str) -> str:
    return RUN if tenant == TENANT else RUN_OTHER


def _purge(connection) -> None:
    tenants = (TENANT, TENANT_OTHER)
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM workbench_execution_idempotency WHERE tenant_id IN (%s, %s)", tenants
        )
        cursor.execute(
            "DELETE FROM workbench_conversation_messages WHERE tenant_id IN (%s, %s)", tenants
        )
        cursor.execute(
            "DELETE FROM workbench_conversation_stream_frames WHERE tenant_id IN (%s, %s)", tenants
        )
        cursor.execute(
            "DELETE FROM workbench_conversation_stream_state WHERE tenant_id IN (%s, %s)", tenants
        )
        cursor.execute("DELETE FROM workbench_run_artifacts WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute("DELETE FROM workbench_conversations WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute("DELETE FROM workbench_run_records WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute("DELETE FROM workbench_audit_log WHERE tenant_id IN (%s, %s)", tenants)


@pytest.fixture()
def env():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    with connection.cursor() as cursor:
        for tenant_id, run_id in ((TENANT, RUN), (TENANT_OTHER, RUN_OTHER)):
            cursor.execute(
                """
                INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status)
                VALUES (%s, %s, %s, 'mock', 'completed')
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, tenant_id, f"task-{run_id}"),
            )
    audit_store = PostgresAuditStore(connection)
    store = PostgresConversationStore(connection)
    stream_store = PostgresStreamStore(connection)
    idempotency = PostgresExecutionIdempotencyStore(connection)
    service = ConversationService(
        store,
        audit=AuditService(audit_store),
        stream_store=stream_store,
        idempotency_store=idempotency,
    )
    yield {
        "connection": connection,
        "store": store,
        "stream": stream_store,
        "idempotency": idempotency,
        "service": service,
        "audit": audit_store,
    }
    _purge(connection)
    connection.close()


def _owner(tenant: str = TENANT, user_id: str = OWNER) -> UserContext:
    return UserContext(tenant, user_id, "employee")


def _seed(env, *, tenant: str = TENANT, user_id: str = OWNER, title: str = "会话标题") -> str:
    run_id = _run_id(tenant)
    conversation = env["service"].create_conversation(_owner(tenant, user_id), title=title)
    conversation_id = conversation.conversation_id
    context = _owner(tenant, user_id)
    first = env["store"].append_message(context, conversation_id, role="user", content="第一条")
    env["store"].append_message(context, conversation_id, role="assistant", content="第二条")
    env["stream"].append_frame(tenant, conversation_id, run_id, kind="message.user", payload={"message_id": first.message_id})
    env["stream"].set_terminal(
        tenant, conversation_id, run_id, status="completed", expires_at=datetime.now(UTC) + timedelta(days=7)
    )
    # 幂等行**引用消息行**（复合外键）——删除顺序由此决定：幂等行必须先于消息行。
    env["idempotency"].insert(
        ExecutionIdempotencyRecord(
            tenant_id=tenant,
            actor_id=user_id,
            conversation_id=conversation_id,
            idempotency_key="k-1",
            outcome="executed",
            http_status=201,
            message_id=first.message_id,
            run_id=run_id,
        )
    )
    with env["connection"].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_run_artifacts
                (artifact_id, tenant_id, run_id, virtual_path, change_kind, bytes, sha256, expires_at)
            VALUES (%s, %s, %s, '/workspace/a.txt', 'created', 12, %s, now() + interval '30 days')
            ON CONFLICT DO NOTHING
            """,
            (f"art-{conversation_id[:8]}", tenant, run_id, "sha256:" + "0" * 64),
        )
    return conversation_id


def _count(connection, table: str, tenant: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s", (tenant,))  # noqa: S608 - 表名为本文件常量
        row = cursor.fetchone()
    return int(row[0])


def _audit_count(connection, tenant: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM workbench_audit_log WHERE tenant_id = %s", (tenant,))
        row = cursor.fetchone()
    return int(row[0])


# ------------------------------------------------------------ ① mode 列


def test_mode_column_defaults_and_check(env) -> None:
    conversation = env["store"].create_conversation(_owner(), title="模式")
    assert conversation.mode.value == "craft"  # 存量语义：默认 craft = 现状
    with env["connection"].cursor() as cursor:
        cursor.execute(
            "SELECT mode, deleted_at FROM workbench_conversations WHERE tenant_id = %s AND conversation_id = %s",
            (TENANT, conversation.conversation_id),
        )
        row = cursor.fetchone()
    assert row[0] == "craft" and row[1] is None
    # 受控取值：CHECK 直接拦非法值（绕过接口的 SQL 写入同样被拒）。
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises(psycopg.errors.CheckViolation):
        with env["connection"].cursor() as cursor:
            cursor.execute(
                "UPDATE workbench_conversations SET mode = 'turbo' WHERE tenant_id = %s AND conversation_id = %s",
                (TENANT, conversation.conversation_id),
            )


def test_set_mode_persists_and_is_owner_only(env) -> None:
    conversation = env["store"].create_conversation(_owner(), title="模式")
    updated = env["service"].set_conversation_mode(_owner(), conversation.conversation_id, "plan")
    assert updated.mode.value == "plan"
    assert env["store"].get_conversation(_owner(), conversation.conversation_id).mode.value == "plan"
    with pytest.raises(ConversationNotFound):
        env["service"].set_conversation_mode(_owner("test-lifecycle-pg-other", "u-x"), conversation.conversation_id, "ask")
    with pytest.raises(ConversationNotFound):
        env["service"].set_conversation_mode(_owner(TENANT, OTHER), conversation.conversation_id, "ask")


# ------------------------------------------------------------ ②③④⑤ 物理删除


def test_delete_purges_content_keeps_runs_artifacts_and_audit(env) -> None:
    conversation = _seed(env)
    before_audit = _audit_count(env["connection"], TENANT)
    assert before_audit >= 1  # 会话创建审计已在（删除不得清掉既有审计行）

    outcome = env["service"].delete_conversation(_owner(), conversation)
    assert outcome.deleted is True and outcome.already_deleted is False
    assert (outcome.message_count, outcome.frame_count, outcome.stream_state_count, outcome.idempotency_count) == (2, 1, 1, 1)

    # 内容行**真删**（不是墓碑）：四张表计数为 0。
    assert _count(env["connection"], "workbench_conversation_messages", TENANT) == 0
    assert _count(env["connection"], "workbench_conversation_stream_frames", TENANT) == 0
    assert _count(env["connection"], "workbench_conversation_stream_state", TENANT) == 0
    assert _count(env["connection"], "workbench_execution_idempotency", TENANT) == 0

    # 会话行仍在（软删 + 标题清空）；全部读路径「未找到」。
    raw = env["store"].get_conversation_including_deleted(_owner(), conversation)
    assert raw.deleted_at is not None and raw.title == "" and raw.status is ConversationStatus.ACTIVE
    with pytest.raises(ConversationNotFound):
        env["store"].get_conversation(_owner(), conversation)
    with pytest.raises(ConversationNotFound):
        env["store"].list_messages(_owner(), conversation)
    items, total = env["store"].list_conversations(_owner())
    assert total == 0 and conversation not in [item.conversation_id for item in items]

    # 保留：运行记录 / 产物登记**不动**；审计行数不减少（既有行仍在）。
    assert _count(env["connection"], "workbench_run_records", TENANT) == 1
    assert _count(env["connection"], "workbench_run_artifacts", TENANT) == 1
    assert _audit_count(env["connection"], TENANT) >= before_audit
    with env["connection"].cursor() as cursor:
        cursor.execute(
            "SELECT detail FROM workbench_audit_log WHERE tenant_id = %s AND action = 'conversation.deleted'",
            (TENANT,),
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    detail = rows[0][0]
    assert detail["message_count"] == 2 and detail["frame_count"] == 1
    assert "第一条" not in str(detail) and "会话标题" not in str(detail)


def test_delete_is_idempotent_and_does_not_repeat_audit(env) -> None:
    conversation = _seed(env)
    env["service"].delete_conversation(_owner(), conversation)
    after_first = _audit_count(env["connection"], TENANT)

    again = env["service"].delete_conversation(_owner(), conversation)
    assert again.deleted is True and again.already_deleted is True
    assert (again.message_count, again.frame_count, again.stream_state_count, again.idempotency_count) == (0, 0, 0, 0)
    assert _audit_count(env["connection"], TENANT) == after_first  # 复删不新增审计


def test_delete_by_others_or_cross_tenant_is_not_found_and_keeps_data(env) -> None:
    conversation = _seed(env)
    for context in (_owner(TENANT, OTHER), _owner(TENANT_OTHER, OWNER)):
        with pytest.raises(ConversationNotFound):
            env["service"].delete_conversation(context, conversation)
    assert _count(env["connection"], "workbench_conversation_messages", TENANT) == 2
    assert _count(env["connection"], "workbench_execution_idempotency", TENANT) == 1


# ------------------------------------------------------------ ⑥ 导出


def test_export_mine_scopes_pagination_and_limit(env) -> None:
    mine = _seed(env, title="我的 A")
    mine_archived = _seed(env, title="我的 B")
    env["service"].archive_conversation(_owner(), mine_archived)
    foreign = _seed(env, tenant=TENANT_OTHER, user_id=OWNER, title="他租户")
    other_user = _seed(env, user_id=OTHER, title="他人")

    page = env["service"].export_mine(_owner(), limit=1, offset=0)
    assert page.total_conversations == 2 and page.total_messages == 4
    assert len(page.conversations) == 1
    first_id, first_messages = page.conversations[0]
    assert first_id.conversation_id in {mine, mine_archived}
    assert len(first_messages) == 2 and page.truncated is False and page.limit_reason is None

    second = env["service"].export_mine(_owner(), limit=1, offset=1)
    assert len(second.conversations) == 1
    assert second.conversations[0][0].conversation_id != first_id.conversation_id
    # 含归档状态；不含他人 / 他租户会话。
    ids = {first_id.conversation_id, second.conversations[0][0].conversation_id}
    assert foreign not in ids and other_user not in ids
    statuses = {first_id.status.value, second.conversations[0][0].status.value}
    assert statuses == {"active", "archived"}

    # 上限如实告知（注入小上限）：不静默截断，且**单页装入条目不超限**。
    capped = ConversationService(
        env["store"],
        audit=AuditService(env["audit"]),
        stream_store=env["stream"],
        idempotency_store=env["idempotency"],
        max_export_items=3,
    )
    limited = capped.export_mine(_owner(), limit=50, offset=0)
    assert limited.truncated is True and limited.limit_reason == EXPORT_LIMIT_REASON
    packed = len(limited.conversations) + sum(len(items) for _item, items in limited.conversations)
    assert packed <= 3
    assert MAX_EXPORT_ITEMS == 50000


def test_export_writes_audit(env) -> None:
    _seed(env)
    env["service"].export_mine(_owner(), limit=50, offset=0)
    with env["connection"].cursor() as cursor:
        cursor.execute(
            "SELECT detail FROM workbench_audit_log WHERE tenant_id = %s AND action = %s",
            (TENANT, AuditAction.CONVERSATION_EXPORTED.value),
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == {"conversation_count": 1, "message_count": 2, "truncated": False}