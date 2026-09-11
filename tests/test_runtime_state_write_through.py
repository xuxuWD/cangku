"""写路径无丢写：用「写入即编码、读取即解码」的回环存储跑 Mock 全流程。

这是本设计最关键的性质测试——只要任何一处修改没有经过 append / save_checkpoint，
下面断言就会失败；同时也覆盖「重启后仍能读到」的语义（读取拿到的是解码后的新对象）。

另外覆盖装配：memory 只在 development 允许，postgres 注入连接即得持久化实现。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.bootstrap import build_runtime_state_store
from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEventType
from app.runtime.mock import MockRuntime
from app.runtime.serialization import decode_state, encode_state
from app.runtime.state import RuntimeState, RuntimeStateStore
from app.runtime.state_postgres import PostgresRuntimeStateStore
from app.settings import Settings

TWO_WRITES = [
    {"step_id": "s1", "kind": "write", "tool": "file.write"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]


def context(*, tenant_id: str = "t-1", user_id: str = "u-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id=tenant_id, user_id=user_id, role_key="content-operator", mode="product_manager",
        project_id=None, task_id="task-1", device_id=f"device:{user_id}", knowledge_scope=(),
        file_scope=(), budget_cents=100, risk_level="low", policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


class RoundTripStore:
    """把每次写入编码成快照、每次读取解码成新对象，模拟真实的「落库 + 重新加载」。

    接口与 RuntimeStateStore 完全一致，因此可以直接替换给 MockRuntime 使用。
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def create(self, context: RuntimeContext, plan: AgentPlan, *, run_id: str | None = None) -> RuntimeState:
        state = RuntimeState(run_id=run_id or f"run-{uuid4().hex[:12]}", context=context, plan=plan)
        self.rows[state.run_id] = encode_state(state)
        return decode_state(self.rows[state.run_id])

    def get(self, run_id: str) -> RuntimeState:
        if run_id not in self.rows:
            raise KeyError(run_id)
        return decode_state(self.rows[run_id])

    def list_for_tenant(self, tenant_id: str, *, statuses=None) -> list[RuntimeState]:
        states = [decode_state(row) for row in self.rows.values() if row["tenant_id"] == tenant_id]
        if statuses is not None:
            states = [state for state in states if state.status in statuses]
        return states

    def append(self, state: RuntimeState, event) -> None:
        state.events.append(event)
        self.rows[state.run_id] = encode_state(state)

    def save_checkpoint(self, state: RuntimeState) -> dict:
        state.checkpoint = {
            "status": state.status,
            "completed_steps": list(state.completed_steps),
            "next_step": len(state.completed_steps),
        }
        self.rows[state.run_id] = encode_state(state)
        return dict(state.checkpoint)


def reloaded(store: RoundTripStore, run_id: str) -> RuntimeState:
    """模拟「另一个进程/重启后」重新加载。"""
    return store.get(run_id)


def test_start_run_is_fully_persisted() -> None:
    store = RoundTripStore()
    runtime = MockRuntime(store)

    run_id = runtime.start_run(context(), AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]))
    state = reloaded(store, run_id)

    assert state.status == "completed"
    assert state.usage == {"tool_calls": 1, "successful_tools": 1}
    assert state.completed_steps == ["s1"]
    assert [event.event_type for event in state.events][0] is RuntimeEventType.PLAN_CREATED
    assert reloaded(store, run_id).checkpoint["status"] == "completed"


def test_control_actions_survive_reload() -> None:
    store = RoundTripStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(context(), AgentPlan.from_steps(TWO_WRITES))
    assert reloaded(store, run_id).status == "running"

    runtime.pause_run(run_id, "等待确认")
    assert reloaded(store, run_id).status == "paused"

    runtime.resume_run(run_id)
    assert reloaded(store, run_id).status == "running"

    runtime.cancel_run(run_id, "用户取消")
    cancelled = reloaded(store, run_id)
    assert cancelled.status == "cancelled"
    assert cancelled.checkpoint["status"] == "cancelled"
    assert any(event.event_type is RuntimeEventType.RUN_FAILED for event in cancelled.events)


def test_request_approval_is_persisted_without_explicit_checkpoint() -> None:
    # request_approval 只发事件、不调用 save_checkpoint；整行 upsert 必须让它同样落库。
    store = RoundTripStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(context(), AgentPlan.from_steps(TWO_WRITES))

    approval_id = runtime.request_approval(run_id, {"tool": "file.write"})

    state = reloaded(store, run_id)
    assert state.approvals[approval_id] == "pending"
    assert any(
        event.event_type is RuntimeEventType.APPROVAL_REQUESTED and event.payload.get("approval_id") == approval_id
        for event in state.events
    )


def test_decide_approval_is_persisted() -> None:
    store = RoundTripStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(context(), AgentPlan.from_steps(TWO_WRITES))

    runtime.decide_approval(run_id, "s1", True)
    assert reloaded(store, run_id).status == "running"
    assert reloaded(store, run_id).approvals["s1"] == "approved"

    runtime.decide_approval(run_id, "s2", False)
    failed = reloaded(store, run_id)
    assert failed.status == "failed"
    assert failed.approvals == {"s1": "approved", "s2": "rejected"}


def test_replay_run_is_persisted() -> None:
    store = RoundTripStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(context(), AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]))

    runtime.replay_run(run_id, from_step="s1")

    events = reloaded(store, run_id).events
    assert events[-1].event_type is RuntimeEventType.CHECKPOINT_SAVED
    assert events[-1].payload.get("replay") is True


def test_list_for_tenant_reads_from_the_store() -> None:
    store = RoundTripStore()
    runtime = MockRuntime(store)
    mine = runtime.start_run(context(), AgentPlan.from_steps(TWO_WRITES))
    runtime.start_run(context(tenant_id="t-2", user_id="u-9"), AgentPlan.from_steps(TWO_WRITES))

    active = store.list_for_tenant("t-1", statuses=("running", "paused"))

    assert [state.run_id for state in active] == [mine]


def test_memory_store_and_round_trip_store_behave_alike() -> None:
    memory = RuntimeStateStore()
    persisted = RoundTripStore()
    plan = AgentPlan.from_steps(TWO_WRITES)

    memory_run = MockRuntime(memory).start_run(context(), plan)
    persisted_run = MockRuntime(persisted).start_run(context(), plan)

    left, right = memory.get(memory_run), persisted.get(persisted_run)
    assert (left.status, left.usage, left.approvals, left.completed_steps) == (
        right.status, right.usage, right.approvals, right.completed_steps
    )
    assert [event.event_type for event in left.events] == [event.event_type for event in right.events]


def test_build_runtime_state_store_memory_in_development() -> None:
    store = build_runtime_state_store(Settings(env="development", storage_backend="memory"))

    assert isinstance(store, RuntimeStateStore)


def test_build_runtime_state_store_rejects_memory_outside_development() -> None:
    with pytest.raises(ValueError):
        build_runtime_state_store(Settings(env="production", storage_backend="memory"))


def test_build_runtime_state_store_selects_postgres_with_injected_connection() -> None:
    store = build_runtime_state_store(
        Settings(
            env="development",
            storage_backend="postgres",
            database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        ),
        connection=object(),
        migrate=False,
    )

    assert isinstance(store, PostgresRuntimeStateStore)
