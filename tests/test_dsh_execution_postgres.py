"""段二-4（dsh 接入）Postgres 分支的**真库**回归测试。

与既有 `tests/test_*_postgres.py` 的区别：那些用 `connection=object()` / `RecordingConnection`
假连接，只断言 SQL 形状与装配；本文件**真的连库**，把此前「登记为未验证」的 Postgres 路径
变成可重复的回归：

  - `workbench_execution_idempotency` 四态写入与读回、复合主键冲突即重放（`ON CONFLICT DO NOTHING`）；
  - `result_check` 库层约束（绕过应用层直接 SQL 插非法 `outcome` ↔ `http_status` 组合必须被 DB 拒）；
  - `PostgresTaskRepository.set_pending_approval` / `delete`；
  - `PostgresRunRecordStore.delete`；
  - ⑥ 失败「显式补偿回滚」的 Postgres 分支（§4.1.3）——四类对象在真库里零残留。

口径（沿用 `tests/test_tool_action_store_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**，
    因此不影响默认 `pytest` 全量（无库环境不会红）。
  - 目标库必须是**已完成全部迁移（含 `027_dsh_tool_execution`）**的库；
    本文件**不建表、不迁移**，缺表时应**显式失败**而不是静默跳过。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清（按外键逆序删）。
  - ⚠️ **覆盖现状（2026-09-14 更新）**：默认 `pytest` 全量（无库环境）下本文件整体 skip；
    真库改由 `.github/workflows/ci.yml` 的 **`postgres` job** 提供该变量并**要求 `skipped == 0`**
    ⇒ 已纳入 CI 守护，不再是"无人跑"。**未验证**：该 job 尚未在 GitHub Actions 上实跑过。
  - ⚠️ **另一处局限（如实声明）**：`_compensate` 仅对实现了 `remove` 的 state_store 才撤销
    运行状态；`PostgresRuntimeStateStore` **已实现 `remove`**（与内存分支对齐）⇒ 两分支下
    ⑥ 失败后 `workbench_runtime_states` 行均被清除。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

from app.conversation.execution import ConversationExecutionError, ConversationExecutionService
from app.conversation.idempotency import (
    ExecutionIdempotencyRecord,
    PostgresExecutionIdempotencyStore,
)
from app.conversation.store import PostgresConversationStore
from app.domain import RiskLevel, Task, TaskNotFound, TaskStatus, UserContext
from app.repository import PostgresTaskRepository
from app.runtime.records import PostgresRunRecordStore, RunRecord, RunRecordNotFound
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.runtime.state_postgres import PostgresRuntimeStateStore
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.errors import ToolExecutionError
from app.tool_execution.service import ToolExecutionResult
from app.workforce.store import InMemoryWorkforceDirectoryStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-dsh-pg"
OTHER_TENANT = "test-dsh-pg-other"
ACTOR = "u-1"
AGENT = "content-writer"
ADMIN = "admin-1"

# 按外键逆序（子表在前）——保证自清不撞外键。
_TABLES_IN_DELETE_ORDER = (
    "workbench_execution_idempotency",
    "workbench_tool_actions",
    # 运行事件（迁移 034）已独立成 append-only 表；无外键，随状态行一起自清。
    "workbench_runtime_events",
    "workbench_runtime_states",
    "workbench_conversation_messages",
    "workbench_conversations",
    "workbench_run_records",
    "workbench_event_outbox",
    "workbench_audit_events",
    "workbench_tasks",
)


# ------------------------------------------------------------------ 夹具与工具


@pytest.fixture()
def connection():
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(DSN, autocommit=True)
    _purge(conn, TENANT)
    yield conn
    _purge(conn, TENANT)
    conn.close()


def _purge(connection, tenant: str) -> None:
    with connection.cursor() as cursor:
        for table in _TABLES_IN_DELETE_ORDER:
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))


def _count(connection, table: str, tenant: str, **filters) -> int:
    clauses = ["tenant_id = %s"]
    params: list[object] = [tenant]
    for column, value in filters.items():
        clauses.append(f"{column} = %s")
        params.append(value)
    where = " AND ".join(clauses)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", tuple(params))
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def _employee() -> UserContext:
    return UserContext(TENANT, ACTOR, "employee")


def _run_record(run_id: str, *, task_id: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        tenant_id=TENANT,
        task_id=task_id,
        runtime_key="mock",
        status="running",
        started_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )


def _seed_fk_parents(connection, *, suffix: str, with_message: bool):
    """建幂等表三条复合外键所需的父行：会话（023）、消息（023）、运行记录（013+027 唯一约束）。"""
    conversations = PostgresConversationStore(connection)
    context = _employee()
    conversation = conversations.create_conversation(context, agent_key=AGENT, title="t")
    message_id = None
    if with_message:
        message = conversations.append_message(
            context, conversation.conversation_id, role="assistant", content="ok"
        )
        message_id = message.message_id
    run_id = f"run-{suffix}"
    PostgresRunRecordStore(connection).upsert(_run_record(run_id, task_id=f"task-{suffix}"))
    return conversation.conversation_id, message_id, run_id


def _idempotency_record(
    conversation_id: str,
    *,
    key: str,
    outcome: str,
    http_status: int,
    message_id: str | None = None,
    run_id: str | None = None,
    approval_id: str | None = None,
) -> ExecutionIdempotencyRecord:
    return ExecutionIdempotencyRecord(
        tenant_id=TENANT,
        actor_id=ACTOR,
        conversation_id=conversation_id,
        idempotency_key=key,
        outcome=outcome,
        http_status=http_status,
        message_id=message_id,
        run_id=run_id,
        approval_id=approval_id,
        created_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )


# ------------------------------------------------------------------ 1) 幂等表四态


@pytest.mark.parametrize(
    "outcome,http_status",
    [("executed", 201), ("pending_approval", 202), ("rejected", 422), ("failed", 502)],
)
def test_idempotency_four_states_round_trip(connection, outcome: str, http_status: int) -> None:
    """四态（executed / pending_approval / rejected / failed）写入后必须能原样读回。"""
    store = PostgresExecutionIdempotencyStore(connection)
    conversation_id, message_id, run_id = _seed_fk_parents(
        connection, suffix=f"four-{outcome}", with_message=True
    )
    record = _idempotency_record(
        conversation_id,
        key=f"k-{outcome}",
        outcome=outcome,
        http_status=http_status,
        # 只有 executed / pending_approval 会追加助手消息；被拒 / 失败时 message_id 为空。
        message_id=message_id if outcome in ("executed", "pending_approval") else None,
        run_id=run_id,
        approval_id="ap-1" if outcome == "pending_approval" else None,
    )

    saved, inserted = store.insert(record)

    assert inserted is True
    assert (saved.outcome, saved.http_status) == (outcome, http_status)
    got = store.get(TENANT, ACTOR, conversation_id, f"k-{outcome}")
    assert got is not None
    assert (got.outcome, got.http_status) == (outcome, http_status)
    assert got.message_id == record.message_id
    assert got.run_id == run_id
    assert got.approval_id == record.approval_id
    assert got.created_at is not None
    assert abs((got.created_at - record.created_at).total_seconds()) < 1


def test_idempotency_conflict_replays_existing_result(connection) -> None:
    """复合主键冲突即重放（`ON CONFLICT DO NOTHING`）：不新增行、返回**库中既有**结果。"""
    store = PostgresExecutionIdempotencyStore(connection)
    conversation_id, message_id, run_id = _seed_fk_parents(
        connection, suffix="conflict", with_message=True
    )
    first = _idempotency_record(
        conversation_id, key="k-dup", outcome="executed", http_status=201,
        message_id=message_id, run_id=run_id,
    )
    saved, inserted = store.insert(first)
    assert inserted is True

    # 同一复合主键再插入、且刻意给出**不同**结果：必须以首次行为准。
    second = _idempotency_record(
        conversation_id, key="k-dup", outcome="failed", http_status=502, run_id=run_id
    )
    replayed, inserted_again = store.insert(second)

    assert inserted_again is False
    assert replayed.message_id == saved.message_id
    assert (replayed.outcome, replayed.http_status) == ("executed", 201)
    # 库中仍只有一行（不新增）。
    assert _count(connection, "workbench_execution_idempotency", TENANT, conversation_id=conversation_id) == 1
    assert store.get(TENANT, ACTOR, conversation_id, "k-dup").outcome == "executed"


def test_idempotency_get_scopes_by_actor_and_conversation(connection) -> None:
    """查询按 (tenant, actor, conversation, key) 四元组归属过滤：换任一维度都查不到。"""
    store = PostgresExecutionIdempotencyStore(connection)
    conversation_id, message_id, run_id = _seed_fk_parents(
        connection, suffix="scope", with_message=True
    )
    store.insert(
        _idempotency_record(
            conversation_id, key="k-scope", outcome="executed", http_status=201,
            message_id=message_id, run_id=run_id,
        )
    )

    assert store.get(TENANT, ACTOR, conversation_id, "k-scope") is not None
    assert store.get(TENANT, "other-actor", conversation_id, "k-scope") is None
    assert store.get(OTHER_TENANT, ACTOR, conversation_id, "k-scope") is None


# ------------------------------------------------------------------ 2) result_check 库层约束


@pytest.mark.parametrize(
    "outcome,http_status",
    [("executed", 409), ("pending_approval", 201), ("rejected", 500), ("failed", 403)],
)
def test_result_check_rejects_illegal_combo_at_db_level(connection, outcome: str, http_status: int) -> None:
    """绕过应用层校验、直接 SQL 插入非法 `outcome` ↔ `http_status` 组合：库层 `result_check` 必须拒。

    `PostgresExecutionIdempotencyStore.insert` 会先跑 `_validate`（应用层）——故此处**不经仓储**，
    直接 INSERT，目的是证明「库层约束真的在」，而不是只有应用层在挡。
    """
    psycopg = pytest.importorskip("psycopg")
    conversation_id, _message_id, run_id = _seed_fk_parents(
        connection, suffix=f"check-{outcome}", with_message=False
    )

    with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workbench_execution_idempotency
                    (tenant_id, actor_id, conversation_id, idempotency_key, message_id,
                     run_id, approval_id, outcome, http_status)
                VALUES (%s, %s, %s, 'raw-illegal', NULL, %s, NULL, %s, %s)
                """,
                (TENANT, ACTOR, conversation_id, run_id, outcome, http_status),
            )

    assert "workbench_execution_idempotency_result_check" in str(excinfo.value)


# ------------------------------------------------------------------ 3) PostgresTaskRepository


def _new_task(**overrides) -> Task:
    base = dict(
        tenant_id=TENANT,
        project_id=None,
        created_by=ACTOR,
        employee_key=AGENT,
        title="对话触发执行",
        risk_level=RiskLevel.MEDIUM,
        budget=0.0,
        idempotency_key="conv-c1-k1",
        request_fingerprint="fp-1",
        status=TaskStatus.QUEUED,
    )
    base.update(overrides)
    return Task(**base)


def test_set_pending_approval_moves_queued_task(connection) -> None:
    """`queued` → `pending_approval`（§3.7 Y2）；重复调用保持幂等（仍是 pending_approval）。"""
    store = PostgresTaskRepository(connection)
    context = _employee()
    created, is_new = store.create(context, _new_task())
    assert is_new is True
    assert created.status is TaskStatus.QUEUED

    updated = store.set_pending_approval(context, created.id)

    assert updated.status is TaskStatus.PENDING_APPROVAL
    assert store.get(context, created.id).status is TaskStatus.PENDING_APPROVAL
    # 再调一次：UPDATE 的 `status = 'queued'` 条件不再命中，但返回值仍应是该任务（不改坏状态）。
    again = store.set_pending_approval(context, created.id)
    assert again.status is TaskStatus.PENDING_APPROVAL


def test_set_pending_approval_is_tenant_scoped(connection) -> None:
    store = PostgresTaskRepository(connection)
    created, _ = store.create(_employee(), _new_task())

    with pytest.raises(TaskNotFound):
        store.set_pending_approval(UserContext(OTHER_TENANT, ACTOR, "employee"), created.id)

    assert store.get(_employee(), created.id).status is TaskStatus.QUEUED


def test_task_delete_removes_task_audit_outbox_and_frees_idempotency_key(connection) -> None:
    """`delete` 的**实际效果**（按实现口径断言，见 `app/repository.py:179`）：

    * 清 `workbench_tasks` + `workbench_audit_events` + `workbench_event_outbox` 三张表；
    * 连带释放 `workbench_tasks` 的 `UNIQUE (tenant_id, created_by, idempotency_key)` 槽位
      ⇒ 同幂等键可再建为**新行**（这正是回滚后"重放该键重新走一遍闸门"所依赖的）。
    """
    store = PostgresTaskRepository(connection)
    context = _employee()
    created, _ = store.create(context, _new_task())
    assert _count(connection, "workbench_audit_events", TENANT, task_id=created.id) == 1
    assert _count(connection, "workbench_event_outbox", TENANT, aggregate_id=created.id) == 1
    # 幂等键索引生效：同键再建不新增，返回既有行。
    again, is_new = store.create(context, _new_task())
    assert is_new is False and again.id == created.id

    store.delete(TENANT, created.id)

    with pytest.raises(TaskNotFound):
        store.get(context, created.id)
    assert _count(connection, "workbench_audit_events", TENANT, task_id=created.id) == 0
    assert _count(connection, "workbench_event_outbox", TENANT, aggregate_id=created.id) == 0
    # 幂等键槽位被释放：同键可再建为新行（新 id）。
    rebuilt, created_again = store.create(context, _new_task())
    assert created_again is True and rebuilt.id != created.id


def test_task_delete_is_tenant_scoped_and_idempotent(connection) -> None:
    store = PostgresTaskRepository(connection)
    context = _employee()
    created, _ = store.create(context, _new_task())

    store.delete(OTHER_TENANT, created.id)  # 异租户：不动它
    assert store.get(context, created.id).id == created.id

    store.delete(TENANT, created.id)
    with pytest.raises(TaskNotFound):
        store.get(context, created.id)
    store.delete(TENANT, created.id)  # 幂等：重复删无副作用
    store.delete(TENANT, "task-does-not-exist")


def test_task_delete_does_not_touch_execution_idempotency(connection) -> None:
    """实现口径：`delete` **不碰** `workbench_execution_idempotency`（两张表无外键/字段关联）。"""
    conversation_id, message_id, run_id = _seed_fk_parents(
        connection, suffix="task-del-idem", with_message=True
    )
    PostgresExecutionIdempotencyStore(connection).insert(
        _idempotency_record(
            conversation_id, key="k-x", outcome="executed", http_status=201,
            message_id=message_id, run_id=run_id,
        )
    )
    store = PostgresTaskRepository(connection)
    created, _ = store.create(_employee(), _new_task())

    store.delete(TENANT, created.id)

    assert PostgresExecutionIdempotencyStore(connection).get(TENANT, ACTOR, conversation_id, "k-x") is not None


# ------------------------------------------------------------------ 4) PostgresRunRecordStore.delete


def test_run_record_delete_is_tenant_scoped_and_idempotent(connection) -> None:
    store = PostgresRunRecordStore(connection)
    store.upsert(_run_record("run-del", task_id="task-del"))

    store.delete(OTHER_TENANT, "run-del")  # 异租户：不动它
    assert store.get(TENANT, "run-del").run_id == "run-del"

    store.delete(TENANT, "run-del")
    with pytest.raises(RunRecordNotFound):
        store.get(TENANT, "run-del")
    store.delete(TENANT, "run-del")  # 幂等：重复删无副作用


# ------------------------------------------------------------------ 5) ⑥ 失败补偿（Postgres 分支）


class _FailingToolExecution:
    """替身：模拟 ⑥ 待批动作落库失败（§4.1.6-1.1① / §4.1.6-5）——`execute` 一律抛 503。"""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        raise ToolExecutionError("审批请求暂时无法登记，请稍后重试", http_status=503)


def _build_execution_service(connection, *, tool_execution=None):
    """全部四个仓储都指向**真库**（承载任务 / 运行记录 / 运行状态 / 幂等）。"""
    task_store = PostgresTaskRepository(connection)
    run_records = PostgresRunRecordStore(connection)
    runtime = RuntimeService(
        task_store,
        state_store=PostgresRuntimeStateStore(connection),
        run_metrics=RunMetricsService(run_records),
    )
    conversations = PostgresConversationStore(connection)
    idempotency = PostgresExecutionIdempotencyStore(connection)
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, ADMIN, "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    # O3 派生授权：AGENT 归属人 = 会话发起人本人（`ACTOR` = `u-1`），使会话对该员工**合法可用**；
    # 否则真库路径下会先拿 `403`（而非本文件要验的 `503`/执行语义）。
    directory.create_employee(UserContext(TENANT, ACTOR, "employee"), agent_key=AGENT, name="内容员工", role_key="writer")

    service = ConversationExecutionService(
        conversations=None,
        conversation_store=conversations,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=tool_execution if tool_execution is not None else _FailingToolExecution(),
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        directory_store=directory,
    )
    return service, conversations, idempotency


def _invocation() -> str:
    return json.dumps({"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": "x"}})


def test_compensation_leaves_no_residue_of_the_four_objects(connection) -> None:
    """⑥ 落库失败（503）：请求结束后 §4.1.3 的**四类对象**在真库里全部查不到。

    四类 = 承载任务 / 运行记录 / 会话消息 / 幂等行（与 `docs/.../2026-09-12-dsh-integration-design.md`
    §4.1.3「落地为显式补偿回滚」一段逐字对应）；重放该键因幂等表确无该键而**重新走一遍闸门**。
    """
    service, conversations, idempotency = _build_execution_service(connection)
    context = _employee()
    conversation = conversations.create_conversation(context, agent_key=AGENT, title="t")

    with pytest.raises(ConversationExecutionError) as excinfo:
        service.handle_message(
            context, conversation.conversation_id, content=_invocation(), idempotency_key="k-503"
        )

    assert excinfo.value.http_status == 503
    assert service.tool_execution.calls == 1
    # ① 承载任务：0（本次新建的已按逆序补偿撤销）
    assert _count(connection, "workbench_tasks", TENANT, created_by=ACTOR) == 0
    assert _count(connection, "workbench_audit_events", TENANT) == 0
    assert _count(connection, "workbench_event_outbox", TENANT, aggregate_type="task") == 0
    # ② 运行记录：0
    assert _count(connection, "workbench_run_records", TENANT) == 0
    # ③ 会话消息：0（首次执行的消息只在 ⑥ 成功后才追加）
    assert conversations.list_messages(context, conversation.conversation_id)[1] == 0
    # ④ 幂等行：0（故不存在「首次 503」的行）
    assert idempotency.get(TENANT, ACTOR, conversation.conversation_id, "k-503") is None

    # 重放同一键：幂等表确无该键 ⇒ 重新走一遍闸门（执行器再被调用一次，仍零残留）。
    with pytest.raises(ConversationExecutionError) as replay:
        service.handle_message(
            context, conversation.conversation_id, content=_invocation(), idempotency_key="k-503"
        )
    assert replay.value.http_status == 503
    assert service.tool_execution.calls == 2
    assert _count(connection, "workbench_tasks", TENANT, created_by=ACTOR) == 0
    assert _count(connection, "workbench_run_records", TENANT) == 0


def test_compensation_leaves_no_runtime_state_row(connection) -> None:
    """已修：⑥ 失败补偿也撤销运行状态行（Postgres 分支与内存分支一致，零残留）。"""
    service, conversations, _idempotency = _build_execution_service(connection)
    context = _employee()
    conversation = conversations.create_conversation(context, agent_key=AGENT, title="t")

    with pytest.raises(ConversationExecutionError):
        service.handle_message(
            context, conversation.conversation_id, content=_invocation(), idempotency_key="k-rs"
        )

    assert _count(connection, "workbench_runtime_states", TENANT) == 0


# ------------------------------------------------------------------ 6) 消息表正文脱敏（§8 U23）

# 合成哨兵（**非真实业务正文**），用于「原文不得落库」的检索断言。
_U23_BODY = "机密正文-U23-真库哨兵"
_U23_PATH = "/workspace/secret-u23-db.txt"


class _SucceedingToolExecution:
    """替身：`outcome=executed`（201），用于驱动**真实写入路径**（Postgres 分支）。"""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        return ToolExecutionResult(outcome="executed", code=201)


def _count_content_like(connection, needle: str) -> int:
    """§5 用例 32②(c1)③ 的**可执行检索**：对 `workbench_conversation_messages.content`（TEXT）
    直接 `LIKE`（该列为 `TEXT` ⇒ **无需 `::text`**）。"""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM workbench_conversation_messages WHERE content LIKE %s',
            (f"%{needle}%",),
        )
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def test_usecase_32_c1_3_no_body_original_in_conversation_messages(connection) -> None:
    """§8 U23：真实写入路径下，`workbench_conversation_messages.content` **全表**检索正文原文 /
    参数值 / 调用 JSON 片段 ⇒ **0 命中**（用例 32②(c1)③ 的真库口径）。

    查询（**验收记录须写明库与查询**）：

        SELECT COUNT(*) FROM workbench_conversation_messages
        WHERE content LIKE '%' || %s || '%';   -- 分别以正文原文 / path 参数值 / '"tool_key"' 传入

    ⚠️ **覆盖现状（2026-09-14 更新）**：默认 `pytest` 全量下本模块整体 skip；真库改由
    `.github/workflows/ci.yml` 的 `postgres` job 提供 `WORKBENCH_TEST_DATABASE_URL` 并要求
    `skipped == 0` ⇒ 该断言已纳入 CI 守护。**未验证**：该 job 尚未在 GitHub Actions 上实跑过。
    """
    service, conversations, _idempotency = _build_execution_service(
        connection, tool_execution=_SucceedingToolExecution()
    )
    context = _employee()
    conversation = conversations.create_conversation(context, agent_key=AGENT, title="t")
    content = json.dumps(
        {"tool_key": "fs.write", "params": {"path": _U23_PATH, "content": _U23_BODY}}
    )

    result = service.handle_message(
        context, conversation.conversation_id, content=content, idempotency_key="k-u23"
    )

    assert result.http_status == 201, result.body
    # 全表检索：正文原文 / 参数值 / 调用 JSON 片段均不得命中。
    for needle in (_U23_BODY, _U23_PATH, '"tool_key"'):
        assert _count_content_like(connection, needle) == 0, needle
    # 「功能没坏」：消息仍在（用户 + 助手各一条）。
    assert conversations.list_messages(context, conversation.conversation_id)[1] == 2
