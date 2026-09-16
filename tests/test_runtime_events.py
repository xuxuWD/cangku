"""运行事件的独立存储语义（内存实现 + Mock 运行时）。

背景（2026-09-16「运行事件有界」结构性改造）：事件此前挂在状态行的 `events` JSONB 列里，
既无界、又因「写入 = 整行 upsert」而要重写全部历史事件（写放大 O(n²)）。改造后事件写
`workbench_runtime_events`（append-only，PRIMARY KEY (run_id, sequence)），状态行只保留
事件计数 `event_count`，并由保留期任务按 `occurred_at` 清理。

本文件覆盖**可离线判定**的行为（真库分支见 `tests/test_runtime_events_postgres.py`）：
写入→读取、`after_sequence` 增量读取（游标不回退不重复）、sequence 从 1 起单调递增、
事件查询以 run_id 为准（不新增跨租户路径）、`purge_events_before` 只删超期行且返回正确条数、
以及保留期配置与周期任务接线。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType
from app.runtime.mock import MockRuntime
from app.runtime.state import RuntimeStateStore
from app.settings import Settings

READ_PLAN = [{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]
WRITE_PLAN = [{"step_id": "s1", "kind": "write", "tool": "file.write"}]


def runtime_context(tenant_id: str = "t-1") -> RuntimeContext:
    return RuntimeContext(
        tenant_id=tenant_id, user_id="u-1", role_key="content-operator", mode="product_manager",
        project_id=None, task_id="task-1", device_id="device:u-1", knowledge_scope=(),
        file_scope=(), budget_cents=100, risk_level="low", policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def plan() -> AgentPlan:
    return AgentPlan.from_steps(READ_PLAN)


def _append(store: RuntimeStateStore, state, sequence: int, payload: dict | None = None) -> RuntimeEvent:
    event = RuntimeEvent(state.run_id, sequence, RuntimeEventType.TOOL_RESULT, payload or {})
    store.append(state, event)
    return event


# ------------------------------------------------------------ 写入 → 读取


def test_append_then_list_events_returns_them_in_sequence_order() -> None:
    store = RuntimeStateStore()
    state = store.create(runtime_context(), plan())

    _append(store, state, 1)
    _append(store, state, 2, {"status": "success"})

    events = store.list_events(state.run_id)
    assert [event.sequence for event in events] == [1, 2]
    assert [event.event_type for event in events] == [RuntimeEventType.TOOL_RESULT] * 2
    # 状态行只保留计数（不再承载事件数组）。
    assert state.event_count == 2
    assert not hasattr(state, "events")


def test_list_events_for_unknown_run_is_empty() -> None:
    store = RuntimeStateStore()

    assert store.list_events("run-unknown") == []


def test_list_events_after_sequence_returns_only_newer_events() -> None:
    store = RuntimeStateStore()
    state = store.create(runtime_context(), plan())
    for sequence in (1, 2, 3):
        _append(store, state, sequence)

    assert [event.sequence for event in store.list_events(state.run_id, 1)] == [2, 3]
    assert [event.sequence for event in store.list_events(state.run_id, 3)] == []
    # 游标不回退：`after_sequence=0` 等价于「从头读」，不会漏事件。
    assert [event.sequence for event in store.list_events(state.run_id, 0)] == [1, 2, 3]


# ------------------------------------------------------------ sequence 单调 / 游标不重复


def test_mock_sequences_start_at_one_and_are_monotonic() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)

    run_id = runtime.start_run(runtime_context(), plan())

    events = runtime.stream_events(run_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert store.get(run_id).event_count == len(events)


def test_cursor_read_does_not_repeat_or_skip_events() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(runtime_context(), AgentPlan.from_steps(WRITE_PLAN))

    first = runtime.stream_events(run_id)
    cursor = first[0].to_public_dict()["cursor"]

    tail = runtime.stream_events(run_id, cursor)

    assert [event.sequence for event in tail] == [event.sequence for event in first[1:]]
    assert all(event.sequence > first[0].sequence for event in tail)


def test_sequence_continues_after_new_events_are_appended() -> None:
    store = RuntimeStateStore()
    runtime = MockRuntime(store)
    run_id = runtime.start_run(runtime_context(), AgentPlan.from_steps(WRITE_PLAN))
    before = [event.sequence for event in runtime.stream_events(run_id)]

    runtime.cancel_run(run_id, "测试取消")

    after = [event.sequence for event in runtime.stream_events(run_id)]
    # 追加只增不减：既有序号原样保留，新序号严格大于历史最大值（无回退、无重复）。
    assert after[: len(before)] == before
    assert after[len(before):] == [max(before) + 1]
    assert len(set(after)) == len(after)


# ------------------------------------------------------------ 跨租户不可见


def test_events_are_scoped_strictly_by_run_id() -> None:
    store = RuntimeStateStore()
    mine = store.create(runtime_context("t-1"), plan())
    other = store.create(runtime_context("t-2"), plan())

    _append(store, mine, 1)
    _append(store, other, 1)

    assert [event.run_id for event in store.list_events(mine.run_id)] == [mine.run_id]
    assert [event.run_id for event in store.list_events(other.run_id)] == [other.run_id]


# ------------------------------------------------------------ 保留期清理


def test_purge_events_before_only_removes_expired_events_and_returns_count() -> None:
    store = RuntimeStateStore()
    state = store.create(runtime_context(), plan())
    _append(store, state, 1)
    # 时钟分辨率下两次 append 可能落在同一微秒 ⇒ 明确留出间隔，让「超期」可判定。
    time.sleep(0.01)
    cutoff = datetime.now(UTC)
    _append(store, state, 2)

    kept_nothing_expired = store.purge_events_before(cutoff)

    assert kept_nothing_expired == 1
    assert [event.sequence for event in store.list_events(state.run_id)] == [2]
    # 「事件被清理」不得让序号回退：计数只增不减，否则下一条事件会复用已删掉的序号。
    assert state.event_count == 2

    assert store.purge_events_before(datetime.now(UTC) + timedelta(days=1)) == 1
    assert store.list_events(state.run_id) == []


def test_purge_events_before_with_past_cutoff_removes_nothing() -> None:
    store = RuntimeStateStore()
    state = store.create(runtime_context(), plan())
    _append(store, state, 1)

    assert store.purge_events_before(datetime.now(UTC) - timedelta(days=30)) == 0
    assert [event.sequence for event in store.list_events(state.run_id)] == [1]


def test_remove_drops_the_runs_events_too() -> None:
    """⑥ 失败回滚的零残留语义：状态行被撤销时，其事件不得留在表里。"""
    store = RuntimeStateStore()
    state = store.create(runtime_context(), plan())
    _append(store, state, 1)

    store.remove(state.run_id)

    assert store.list_events(state.run_id) == []
    with pytest.raises(KeyError):
        store.get(state.run_id)


# ------------------------------------------------------------ 保留期配置与周期任务


def test_runtime_events_retention_setting_defaults_and_bounds() -> None:
    field = Settings.model_fields["runtime_events_retention_days"]

    # 判定依据（本改造拍板口径）：默认保留 30 天，范围 1–3650 天。
    assert field.default == 30
    assert Settings(runtime_events_retention_days=1).runtime_events_retention_days == 1
    assert Settings(runtime_events_retention_days=3650).runtime_events_retention_days == 3650
    for invalid in (0, 3651):
        with pytest.raises(Exception):
            Settings(runtime_events_retention_days=invalid)


def test_purge_task_is_scheduled_alongside_existing_periodic_tasks() -> None:
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule["runtime-events-purge"]
    settings = Settings()

    assert entry["task"] == "app.worker.purge_runtime_events"
    assert entry["schedule"] == settings.runtime_events_purge_interval_seconds
    assert entry["schedule"] > 0


def test_purge_task_returns_zero_when_worker_is_not_wired(monkeypatch) -> None:
    from app import worker

    monkeypatch.setattr(worker, "_runtime_event_purger", None)
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)

    assert worker.purge_runtime_events() == 0


def test_purge_task_uses_the_configured_retention_window(monkeypatch) -> None:
    from app import worker

    captured: list[datetime] = []

    class Recorder:
        def purge_events_before(self, cutoff: datetime) -> int:
            captured.append(cutoff)
            return 7

    monkeypatch.setattr(worker, "_runtime_event_purger", Recorder())
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)

    removed = worker.purge_runtime_events()

    assert removed == 7
    settings = Settings()
    expected = datetime.now(UTC) - timedelta(days=settings.runtime_events_retention_days)
    assert abs((captured[0] - expected).total_seconds()) < 60
