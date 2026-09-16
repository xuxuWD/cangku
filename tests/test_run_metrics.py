from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.contracts import AgentPlan, RuntimeContext
from app.runtime.records import InMemoryRunRecordStore, RunRecord
from app.runtime.run_metrics import RunMetricsService
from app.runtime.state import RuntimeState


def context(run_id: str = "run-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id="u-1",
        role_key="content-operator",
        mode="product_manager",
        project_id=None,
        task_id="task-1",
        device_id="device:u-1",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def state_with_usage() -> RuntimeState:
    plan = AgentPlan.from_steps(
        [{"step_id": f"s{i}", "kind": "read", "tool": "knowledge.search"} for i in range(3)]
    )
    state = RuntimeState(run_id="run-1", context=context(), plan=plan)
    state.completed_steps = ["s0", "s1"]
    # 知识命中数由事件写入时增量累加到 usage（2026-09-16 改造：事件独立成 append-only 表，
    # 运行状态对象上不再有全量事件可统计；口径不变 = `tool.result` 且 payload knowledge_hit is True）。
    state.usage = {"tool_calls": 5, "successful_tools": 4, "knowledge_hits": 1}
    state.event_count = 3
    return state


def test_record_state_captures_counts_and_finishes_terminal_status() -> None:
    store = InMemoryRunRecordStore()
    service = RunMetricsService(store)
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    state = state_with_usage()
    state.status = "completed"

    record = service.record_state(
        tenant_id="t-1",
        proposal_id="plan-1",
        runtime_key="mock",
        state=state,
        latency_ms=42,
        now=now,
    )

    assert record.run_id == "run-1"
    assert record.task_id == "task-1"
    assert record.proposal_id == "plan-1"
    assert record.runtime_key == "mock"
    assert record.status == "completed"
    assert record.step_count == 3
    assert record.completed_step_count == 2
    assert record.tool_calls == 5
    assert record.successful_tools == 4
    assert record.knowledge_hits == 1
    assert record.latency_ms == 42
    assert record.started_at == now
    assert record.finished_at == now
    assert store.get("t-1", "run-1").status == "completed"


def test_knowledge_hits_come_from_the_incremental_usage_counter() -> None:
    """知识命中读 `usage["knowledge_hits"]`（事件写入时增量累加）。

    缺该键 ⇒ 0：**存量老运行无回填**，其命中数就是 0（改造后的新运行从 0 开始累积）。
    """
    service = RunMetricsService(InMemoryRunRecordStore())
    state = state_with_usage()
    state.usage.pop("knowledge_hits")

    record = service.record_state(
        tenant_id="t-1",
        proposal_id=None,
        runtime_key="mock",
        state=state,
        latency_ms=0,
        now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )

    assert record.knowledge_hits == 0


def test_appended_events_are_counted_towards_knowledge_hits() -> None:
    """写入链路：append 命中事件 → 增量写进 `usage` → 运行记录读到该计数。"""
    from app.runtime.contracts import RuntimeEvent, RuntimeEventType
    from app.runtime.state import RuntimeStateStore

    state_store = RuntimeStateStore()
    state = state_store.create(context(), AgentPlan.from_steps([]))
    for sequence, payload in (
        (1, {"knowledge_hit": True}),
        (2, {"knowledge_hit": False}),
    ):
        state_store.append(
            state, RuntimeEvent("run-1", sequence, RuntimeEventType.TOOL_RESULT, payload)
        )

    record = RunMetricsService(InMemoryRunRecordStore()).record_state(
        tenant_id="t-1",
        proposal_id=None,
        runtime_key="mock",
        state=state,
        latency_ms=0,
        now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )

    assert state.usage["knowledge_hits"] == 1
    assert record.knowledge_hits == 1


def test_record_state_leaves_finished_at_empty_while_running() -> None:
    store = InMemoryRunRecordStore()
    service = RunMetricsService(store)
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    state = state_with_usage()
    state.status = "running"

    record = service.record_state(
        tenant_id="t-1",
        proposal_id=None,
        runtime_key="mock",
        state=state,
        latency_ms=0,
        now=now,
    )

    assert record.status == "running"
    assert record.finished_at is None


def seed(store: InMemoryRunRecordStore) -> None:
    base = datetime(2026, 9, 11, tzinfo=UTC)
    store.upsert(
        RunRecord(
            run_id="run-1", tenant_id="t-1", task_id="task-1", runtime_key="mock",
            status="completed", started_at=base, tool_calls=2, successful_tools=2, latency_ms=100,
        )
    )
    store.upsert(
        RunRecord(
            run_id="run-2", tenant_id="t-1", task_id="task-2", runtime_key="mock",
            status="failed", started_at=base + timedelta(minutes=1), tool_calls=2, successful_tools=0, latency_ms=200,
        )
    )
    store.upsert(
        RunRecord(
            run_id="run-3", tenant_id="t-1", task_id="task-3", runtime_key="agentscope",
            status="completed", started_at=base + timedelta(minutes=2), tool_calls=0, successful_tools=0, latency_ms=300,
        )
    )
    store.upsert(
        RunRecord(
            run_id="run-9", tenant_id="t-other", task_id="task-9", runtime_key="mock",
            status="completed", started_at=base, tool_calls=10, successful_tools=10, latency_ms=999,
        )
    )


def test_summary_computes_rates_and_nearest_rank_p95() -> None:
    store = InMemoryRunRecordStore()
    seed(store)
    service = RunMetricsService(store)

    summary = service.summary("t-1")

    assert summary["tenant_id"] == "t-1"
    assert summary["runtime_key"] is None
    assert summary["run_count"] == 3
    assert summary["task_completion_rate"] == pytest.approx(2 / 3)
    assert summary["tool_success_rate"] == pytest.approx(0.5)
    assert summary["knowledge_hit_rate"] == 0.0
    assert summary["latency_p95_ms"] == 300


def test_summary_by_runtime_is_grouped_and_sorted() -> None:
    store = InMemoryRunRecordStore()
    seed(store)
    service = RunMetricsService(store)

    summary = service.summary("t-1")

    assert [item["runtime_key"] for item in summary["by_runtime"]] == ["agentscope", "mock"]
    mock = summary["by_runtime"][1]
    assert mock["run_count"] == 2
    assert mock["task_completion_rate"] == pytest.approx(0.5)
    assert mock["tool_success_rate"] == pytest.approx(0.5)
    assert mock["latency_p95_ms"] == 200


def test_summary_filters_by_runtime_key() -> None:
    store = InMemoryRunRecordStore()
    seed(store)
    service = RunMetricsService(store)

    summary = service.summary("t-1", runtime_key="mock")

    assert summary["run_count"] == 2
    assert summary["runtime_key"] == "mock"
    assert [item["runtime_key"] for item in summary["by_runtime"]] == ["mock"]
    assert summary["latency_p95_ms"] == 200


def test_summary_without_samples_is_all_zero() -> None:
    service = RunMetricsService(InMemoryRunRecordStore())

    summary = service.summary("t-empty")

    assert summary["run_count"] == 0
    assert summary["task_completion_rate"] == 0.0
    assert summary["tool_success_rate"] == 0.0
    assert summary["knowledge_hit_rate"] == 0.0
    assert summary["latency_p95_ms"] == 0
    assert summary["by_runtime"] == []
