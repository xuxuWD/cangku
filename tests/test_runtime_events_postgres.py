"""`workbench_runtime_events`（迁移 `034_runtime_events`）的**真库**回归测试。

口径（沿用 `tests/test_tool_action_store_postgres.py` 的先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**，
    因此不影响默认 `pytest` 全量（无库环境不会红）。
  - 目标库必须是**已完成全部迁移（含 `034_runtime_events`）**的库；本文件**不建表、不迁移**，
    缺表时应**显式失败**而不是静默跳过。
  - 只操作本文件的两个测试租户，每个用例前后自清。

覆盖（本改造的库层不可判定项）：
  - 迁移形状：状态行的行内 `events` 列被移除、事件表按约定建列并带 `(run_id, sequence)` 主键；
  - 一次 `append` = 一行事件（append-only），状态行只保留计数；
  - `after_sequence` 增量读取（游标不回退不重复）、sequence 同 run 内唯一且单调递增；
  - 事件查询严格以 `run_id` 为界（不新增跨租户路径）；
  - `purge_events_before` 只删超期行、返回删除行数，且**绝不触碰审计表**。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType
from app.runtime.mock import MockRuntime
from app.runtime.state_postgres import PostgresRuntimeStateStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-runtime-events-pg"
OTHER_TENANT = "test-runtime-events-pg-other"
RUN = "run-events-pg"
OTHER_RUN = "run-events-pg-other"

# 迁移 034 的表结构口径（与其他并行任务约定的固定命名，不得改名）。
EVENT_COLUMNS = ("run_id", "tenant_id", "sequence", "event_type", "payload", "occurred_at")
# 本文件写审计行用的动作名（「清理不碰审计」用例专用，前后自清）。
AUDIT_ACTION = "run.events.purge_test"


def context(tenant_id: str = TENANT, *, task_id: str = "task-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id=tenant_id, user_id="u-1", role_key="content-operator", mode="product_manager",
        project_id=None, task_id=task_id, device_id="device:u-1", knowledge_scope=(),
        file_scope=(), budget_cents=100, risk_level="low", policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def read_plan() -> AgentPlan:
    return AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}])


@pytest.fixture()
def connection():
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(DSN, autocommit=True)
    _purge(conn)
    yield conn
    _purge(conn)
    conn.close()


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        for tenant in (TENANT, OTHER_TENANT):
            cursor.execute("DELETE FROM workbench_runtime_events WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_runtime_states WHERE tenant_id = %s", (tenant,))


def _count(connection, table: str, **filters) -> int:
    clauses = [f"{column} = %s" for column in filters]
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {' AND '.join(clauses)}",
            tuple(filters.values()),
        )
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def _columns(connection, table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return {str(name): str(kind) for name, kind in cursor.fetchall()}


# ------------------------------------------------------------ 迁移形状


def test_migration_creates_the_event_table_with_the_agreed_shape(connection) -> None:
    columns = _columns(connection, "workbench_runtime_events")

    assert tuple(columns) == EVENT_COLUMNS
    assert columns["payload"] == "jsonb"
    assert columns["occurred_at"] == "timestamp with time zone"
    assert columns["run_id"] == "text" and columns["tenant_id"] == "text"
    assert columns["sequence"] == "integer"

    with connection.cursor() as cursor:
        # 主键 (run_id, sequence)：同一 run 内序号唯一（并发/重放不会写出重复序号）。
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'workbench_runtime_events'::regclass AND contype = 'p'"
        )
        primary_keys = {str(row[0]) for row in cursor.fetchall()}
        assert primary_keys == {"PRIMARY KEY (run_id, sequence)"}

        # 两个约定索引：租户/运行/序号（读取）与 occurred_at（保留期清理）。
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'workbench_runtime_events'"
        )
        indexes = {str(name): str(definition) for name, definition in cursor.fetchall()}
    assert any("(tenant_id, run_id, sequence)" in value for value in indexes.values())
    assert any("(occurred_at)" in value for value in indexes.values())


def test_migration_removed_the_inline_events_column_from_the_state_row(connection) -> None:
    columns = _columns(connection, "workbench_runtime_states")

    # 判定依据：事件必须只存在于事件表；状态行内的无界 JSONB 列已删除。
    assert "events" not in columns
    # 状态行保留事件计数（供「下一条序号」与知识命中口径使用）。
    assert columns["event_count"] == "integer"


def test_duplicate_sequence_within_a_run_is_rejected(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_runtime_events (run_id, tenant_id, sequence, event_type, payload) "
            "VALUES (%s, %s, 1, %s, '{}'::jsonb)",
            (RUN, TENANT, RuntimeEventType.PLAN_CREATED.value),
        )
        with pytest.raises(Exception):
            cursor.execute(
                "INSERT INTO workbench_runtime_events (run_id, tenant_id, sequence, event_type, payload) "
                "VALUES (%s, %s, 1, %s, '{}'::jsonb)",
                (RUN, TENANT, RuntimeEventType.RUN_COMPLETED.value),
            )


# ------------------------------------------------------------ 写入 → 读取


def test_append_writes_one_event_row_per_call_and_keeps_the_count(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    state = store.create(context(), read_plan(), run_id=RUN)

    store.append(state, RuntimeEvent(RUN, 1, RuntimeEventType.PLAN_CREATED, {"step_count": 1}))
    store.append(
        state,
        RuntimeEvent(RUN, 2, RuntimeEventType.TOOL_RESULT, {"status": "success", "ACCESS_TOKEN": "泄露"}),
    )

    assert _count(connection, "workbench_runtime_events", run_id=RUN) == 2
    assert store.list_events(RUN) == [
        RuntimeEvent(RUN, 1, RuntimeEventType.PLAN_CREATED, {"step_count": 1}),
        RuntimeEvent(RUN, 2, RuntimeEventType.TOOL_RESULT, {"status": "success", "ACCESS_TOKEN": "[已隐藏]"}),
    ]
    # 计数随 append 落库：重新加载（模拟另一进程/重启）后仍知道已写过多少条事件。
    assert store.get(RUN).event_count == 2


def test_events_are_stored_redacted_before_write(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    state = store.create(context(), read_plan(), run_id=RUN)

    store.append(state, RuntimeEvent(RUN, 1, RuntimeEventType.TOOL_RESULT, {"cookie": "session=abc"}))

    with connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM workbench_runtime_events WHERE run_id = %s", (RUN,))
        payload = cursor.fetchone()[0]
    # 脱敏发生在写入前：数据库中不存在原始敏感值。
    assert payload == {"cookie": "[已隐藏]"}


def test_list_events_after_sequence_returns_only_newer_events(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    state = store.create(context(), read_plan(), run_id=RUN)
    for sequence in (1, 2, 3):
        store.append(state, RuntimeEvent(RUN, sequence, RuntimeEventType.STEP_STARTED, {"sequence": sequence}))

    assert [event.sequence for event in store.list_events(RUN, 1)] == [2, 3]
    assert [event.sequence for event in store.list_events(RUN, 3)] == []
    assert [event.sequence for event in store.list_events(RUN, 0)] == [1, 2, 3]


def test_mock_runtime_keeps_sequences_monotonic_across_store_reloads(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    runtime = MockRuntime(store)

    run_id = runtime.start_run(context(), read_plan())
    started = runtime.stream_events(run_id)
    runtime.pause_run(run_id, "等待确认")
    runtime.cancel_run(run_id, "测试取消")

    sequences = [event.sequence for event in runtime.stream_events(run_id)]
    # start_run 后每个动作都会重新从库里读状态 ⇒ 这条断言正是「计数必须落库」的回归。
    assert sequences[: len(started)] == [event.sequence for event in started]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(set(sequences)) == len(sequences)
    assert store.get(run_id).event_count == len(sequences)


def test_events_are_scoped_strictly_by_run_id(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    mine = store.create(context(TENANT), read_plan(), run_id=RUN)
    other = store.create(context(OTHER_TENANT, task_id="task-2"), read_plan(), run_id=OTHER_RUN)
    store.append(mine, RuntimeEvent(RUN, 1, RuntimeEventType.PLAN_CREATED, {}))
    store.append(other, RuntimeEvent(OTHER_RUN, 1, RuntimeEventType.PLAN_CREATED, {}))

    assert [event.run_id for event in store.list_events(RUN)] == [RUN]
    assert [event.run_id for event in store.list_events(OTHER_RUN)] == [OTHER_RUN]
    # 查不到的 run 不返回任何行（不因缺少 WHERE 而泄出他人事件）。
    assert store.list_events("run-events-pg-missing") == []
    assert _count(connection, "workbench_runtime_events", tenant_id=TENANT) == 1


# ------------------------------------------------------------ 保留期清理


def test_purge_events_before_deletes_only_expired_rows_and_returns_the_count(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    mine = store.create(context(TENANT), read_plan(), run_id=RUN)
    other = store.create(context(OTHER_TENANT, task_id="task-2"), read_plan(), run_id=OTHER_RUN)
    for sequence in (1, 2, 3):
        store.append(mine, RuntimeEvent(RUN, sequence, RuntimeEventType.STEP_STARTED, {}))
    store.append(other, RuntimeEvent(OTHER_RUN, 1, RuntimeEventType.PLAN_CREATED, {}))

    expired = datetime.now(UTC) - timedelta(days=31)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE workbench_runtime_events SET occurred_at = %s WHERE run_id = %s AND sequence <= 2",
            (expired, RUN),
        )

    assert store.purge_events_before(datetime.now(UTC) - timedelta(days=30)) == 2

    assert [event.sequence for event in store.list_events(RUN)] == [3]
    assert [event.sequence for event in store.list_events(OTHER_RUN)] == [1]
    # 计数不回退：清理旧事件后序号继续递增（不会复用已删序号 ⇒ 不出现重复/回退）。
    assert store.get(RUN).event_count == 3

    assert store.purge_events_before(datetime.now(UTC) + timedelta(days=1)) == 2
    assert store.list_events(RUN) == []
    assert store.list_events(OTHER_RUN) == []


def test_purge_never_touches_the_audit_log(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    state = store.create(context(), read_plan(), run_id=RUN)
    store.append(state, RuntimeEvent(RUN, 1, RuntimeEventType.PLAN_CREATED, {}))

    with connection.cursor() as cursor:
        # 本用例自带前置清理 + 按 action 计数：判定只针对本用例插入的审计行。
        cursor.execute(
            "DELETE FROM workbench_audit_log WHERE tenant_id = %s AND action = %s",
            (TENANT, AUDIT_ACTION),
        )
        cursor.execute(
            "INSERT INTO workbench_audit_log (action, actor_id, tenant_id, target_type, target_id, detail) "
            "VALUES (%s, 'u-1', %s, 'run', %s, '{}'::jsonb)",
            (AUDIT_ACTION, TENANT, RUN),
        )
    before = _count(connection, "workbench_audit_log", tenant_id=TENANT, action=AUDIT_ACTION)

    assert store.purge_events_before(datetime.now(UTC) + timedelta(days=1)) == 1

    # 审计不可删除（delivery-remaining-checklist 10.1）：保留期清理只动运行事件表。
    after = _count(connection, "workbench_audit_log", tenant_id=TENANT, action=AUDIT_ACTION)
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM workbench_audit_log WHERE tenant_id = %s AND action = %s",
            (TENANT, AUDIT_ACTION),
        )
    assert before == 1
    assert after == before


# ------------------------------------------------------------ 零残留回滚


def test_remove_drops_the_runs_events_too(connection) -> None:
    store = PostgresRuntimeStateStore(connection)
    state = store.create(context(), read_plan(), run_id=RUN)
    store.append(state, RuntimeEvent(RUN, 1, RuntimeEventType.PLAN_CREATED, {}))

    store.remove(RUN)

    assert _count(connection, "workbench_runtime_events", run_id=RUN) == 0
    assert _count(connection, "workbench_runtime_states", run_id=RUN) == 0
    with pytest.raises(KeyError):
        store.get(RUN)
