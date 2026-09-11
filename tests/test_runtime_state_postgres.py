"""PostgreSQL 运行时状态仓储：SQL 形状、按 run_id 读取、租户列表与损坏行失败。

先写测试：整行 upsert、get 缺失抛 KeyError、list_for_tenant 带租户与可选状态过滤、解码失败抛 InvalidRuntimeState。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.contracts import AgentPlan, RuntimeContext
from app.runtime.serialization import InvalidRuntimeState, encode_plan, encode_state
from app.runtime.state import RuntimeState
from app.runtime.state_postgres import PostgresRuntimeStateStore


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        return self.rows.pop(0)


class RecordingTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_count += 1
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)
        self.transaction_count = 0

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def context() -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1", user_id="u-1", role_key="content-operator", mode="product_manager",
        project_id=None, task_id="task-1", device_id="device:u-1", knowledge_scope=(),
        file_scope=(), budget_cents=100, risk_level="low", policy_version="policy-1",
        expires_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )


def plan() -> AgentPlan:
    return AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}])


def state() -> RuntimeState:
    value = RuntimeState(
        run_id="run-1", context=context(), plan=plan(), created_at=datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
    )
    value.status = "running"
    value.completed_steps = ["s1"]
    value.approvals = {"s2": "pending"}
    value.usage = {"tool_calls": 1, "successful_tools": 1}
    value.checkpoint = {"status": "running"}
    return value


def row() -> tuple:
    encoded = encode_state(state())
    return (
        encoded["run_id"],
        encoded["tenant_id"],
        encoded["task_id"],
        encoded["status"],
        encoded["context"],
        encoded["plan"],
        encoded["events"],
        encoded["completed_steps"],
        encoded["approvals"],
        encoded["usage"],
        encoded["checkpoint"],
        encoded["created_at"],
    )


def test_create_upserts_all_columns() -> None:
    connection = RecordingConnection([row()])
    store = PostgresRuntimeStateStore(connection)

    created = store.create(context(), plan(), run_id="run-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO workbench_runtime_states" in statement
    assert "ON CONFLICT (run_id) DO UPDATE" in statement
    assert "updated_at = now()" in statement
    assert len(params) == 12
    assert params[0] == "run-1"
    assert params[3] == "running"
    assert created.run_id == "run-1"


def test_append_and_save_checkpoint_rewrite_the_row() -> None:
    import json

    from app.runtime.contracts import RuntimeEvent, RuntimeEventType

    connection = RecordingConnection([row(), row()])
    store = PostgresRuntimeStateStore(connection)
    target = state()

    store.append(target, RuntimeEvent("run-1", 1, RuntimeEventType.PLAN_CREATED, {"step_count": 1}))
    saved = store.save_checkpoint(target)

    statements = connection.cursor_instance.statements
    assert "INSERT INTO workbench_runtime_states" in statements[0][0]
    assert "INSERT INTO workbench_runtime_states" in statements[1][0]
    assert statements[1][1][0] == "run-1"
    # checkpoint 列（第 11 个参数）写入的是标准三键结构。
    assert json.loads(statements[1][1][10]) == {
        "status": "running",
        "completed_steps": ["s1"],
        "next_step": 1,
    }
    assert saved == {"status": "running", "completed_steps": ["s1"], "next_step": 1}


def test_get_scopes_by_run_id_and_missing_raises_key_error() -> None:
    connection = RecordingConnection([row()])
    store = PostgresRuntimeStateStore(connection)

    found = store.get("run-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE run_id = %s" in statement
    assert params == ("run-1",)
    assert found.approvals == {"s2": "pending"}
    assert found.checkpoint == {"status": "running"}

    empty = PostgresRuntimeStateStore(RecordingConnection([None]))
    with pytest.raises(KeyError):
        empty.get("run-missing")


def test_list_for_tenant_without_status_filter() -> None:
    connection = RecordingConnection([[row()]])
    store = PostgresRuntimeStateStore(connection)

    listed = store.list_for_tenant("t-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "tenant_id = %s" in statement
    assert "ORDER BY created_at DESC" in statement
    assert params == ("t-1",)
    assert [item.run_id for item in listed] == ["run-1"]


def test_list_for_tenant_applies_status_filter() -> None:
    connection = RecordingConnection([[row()]])
    store = PostgresRuntimeStateStore(connection)

    store.list_for_tenant("t-1", statuses=("running", "paused"))

    statement, params = connection.cursor_instance.statements[0]
    assert "status = ANY(%s)" in statement
    assert params == ("t-1", ["running", "paused"])


def test_corrupt_row_raises_invalid_state() -> None:
    encoded = encode_state(state())
    encoded["plan"] = "not-a-plan"
    broken = tuple(encoded[key] for key in (
        "run_id", "tenant_id", "task_id", "status", "context", "plan", "events",
        "completed_steps", "approvals", "usage", "checkpoint", "created_at",
    ))

    store = PostgresRuntimeStateStore(RecordingConnection([broken]))

    with pytest.raises(InvalidRuntimeState):
        store.get("run-1")


def test_plan_column_round_trips_through_store() -> None:
    connection = RecordingConnection([row()])
    store = PostgresRuntimeStateStore(connection)

    found = store.get("run-1")

    assert found.plan == plan()
    assert [step.requires_approval for step in found.plan.steps] == [False]


def test_sql_and_plan_encoding_are_consistent() -> None:
    # 存储写入的 plan 列必须与 encode_plan 一致，避免两套编码漂移。
    assert encode_state(state())["plan"] == encode_plan(plan())


def test_created_at_is_loaded_as_aware_datetime() -> None:
    store = PostgresRuntimeStateStore(RecordingConnection([row()]))

    found = store.get("run-1")

    assert found.created_at.tzinfo is not None
    assert found.created_at == datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def test_expired_context_still_round_trips() -> None:
    expired = RuntimeContext(
        tenant_id="t-1", user_id="u-1", role_key="content-operator", mode="product_manager",
        project_id=None, task_id="task-1", device_id="device:u-1", knowledge_scope=(),
        file_scope=(), budget_cents=0, risk_level="low", policy_version="policy-1",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    value = RuntimeState(run_id="run-1", context=expired, plan=plan())
    encoded = encode_state(value)
    payload = (
        encoded["run_id"], encoded["tenant_id"], encoded["task_id"], encoded["status"],
        encoded["context"], encoded["plan"], encoded["events"], encoded["completed_steps"],
        encoded["approvals"], encoded["usage"], encoded["checkpoint"], encoded["created_at"],
    )

    found = PostgresRuntimeStateStore(RecordingConnection([payload])).get("run-1")

    assert found.context.expires_at == datetime(2020, 1, 1, tzinfo=UTC)
    assert found.context.is_valid_at(datetime(2026, 9, 11, tzinfo=UTC)) is False
    assert found.context.is_valid_at(datetime(2020, 1, 1, tzinfo=UTC) - timedelta(seconds=1)) is True
