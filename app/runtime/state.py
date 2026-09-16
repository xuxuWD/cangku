from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Iterable
from uuid import uuid4

from .contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType

# `usage` 中的知识命中计数键：命中口径与改造前一致（`tool.result` 事件且 payload `knowledge_hit is True`），
# 但由「每次统计全量事件」改为**写入时增量累加**（事件已独立成表，状态对象上不再有全量事件可统计）。
KNOWLEDGE_HITS_KEY = "knowledge_hits"


@dataclass
class RuntimeState:
    run_id: str
    context: RuntimeContext
    plan: AgentPlan
    # 事件计数（2026-09-16 起取代行内 `events: list[RuntimeEvent]` 数组）。
    # 事件已迁到 append-only 表 `workbench_runtime_events`（见 migrations/034），状态行只保留
    # 「已写过多少条」，用途有二：
    #   ① 生成下一条事件序号（`event_count + 1`，从 1 开始、同 run 内单调递增；
    #      保留期清理删掉旧事件后计数也不回退，因此序号不会被复用）；
    #   ② 随状态行落库 ⇒ 重新加载（重启/多进程）后序号仍能接续。
    event_count: int = 0
    completed_steps: list[str] = field(default_factory=list)
    status: str = "running"
    checkpoint: dict[str, object] | None = None
    approvals: dict[str, str] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: {"tool_calls": 0, "successful_tools": 0})
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def track_appended_event(state: RuntimeState, event: RuntimeEvent) -> None:
    """一次事件追加**成功**后的增量维护（就地改状态）：事件计数 +1，知识命中 +1。

    两个计数都随状态行落库，因此必须在写入之后调用（内存实现与 PG 实现同口径）；
    也可以对状态副本调用以先算出「追加后」的取值（PG 实现即用它构造同一次写入的参数）。
    """
    state.event_count += 1
    if event.event_type is RuntimeEventType.TOOL_RESULT and event.payload.get("knowledge_hit") is True:
        state.usage[KNOWLEDGE_HITS_KEY] = state.usage.get(KNOWLEDGE_HITS_KEY, 0) + 1


class RuntimeStateStore:
    def __init__(self) -> None:
        self._states: dict[str, RuntimeState] = {}
        # run_id → [(occurred_at, event)]：内存实现同样记录写入时刻，
        # 使保留期清理（`purge_events_before`）与真库按 `occurred_at` 清理的语义一致。
        self._events: dict[str, list[tuple[datetime, RuntimeEvent]]] = {}
        self._lock = RLock()

    def create(
        self,
        context: RuntimeContext,
        plan: AgentPlan,
        *,
        run_id: str | None = None,
    ) -> RuntimeState:
        state = RuntimeState(run_id=run_id or f"run-{uuid4().hex[:12]}", context=context, plan=plan)
        with self._lock:
            self._states[state.run_id] = state
        return state

    def get(self, run_id: str) -> RuntimeState:
        with self._lock:
            return self._states[run_id]

    def remove(self, run_id: str) -> None:
        """删除一个运行状态（⑥ 失败回滚用，§4.1.3：使该次请求**零残留**）。

        新增方法，不改变 `get` / `list_for_tenant` 等既有读取语义；幂等，删不存在无副作用。
        事件独立成表后，这里**连同该 run 的事件一起删除**——否则回滚会留下孤儿事件，
        与「零残留」相矛盾，且孤儿事件不会被任何读取路径访问到却仍在增长。
        """
        with self._lock:
            self._states.pop(run_id, None)
            self._events.pop(run_id, None)

    def list_for_tenant(self, tenant_id: str, *, statuses: Iterable[str] | None = None) -> list[RuntimeState]:
        """按租户列出运行状态，可选按状态过滤。

        注意：运行时状态本身是**进程内状态**（所有存储模式都一样），因此这里只能看到
        当前进程创建的运行；重启或多进程部署下结果不完整（已登记为已知限制）。
        """
        with self._lock:
            states = [state for state in self._states.values() if state.context.tenant_id == tenant_id]
        if statuses is not None:
            selected = set(statuses)
            states = [state for state in states if state.status in selected]
        states.sort(key=lambda state: state.created_at, reverse=True)
        return states

    def append(self, state: RuntimeState, event: RuntimeEvent) -> None:
        """追加一条事件（append-only），写入后维护计数（见 `track_appended_event`）。"""
        with self._lock:
            self._events.setdefault(state.run_id, []).append((datetime.now(UTC), event))
            track_appended_event(state, event)

    def list_events(self, run_id: str, after_sequence: int | None = None) -> list[RuntimeEvent]:
        """按 `sequence` **升序**读取某个 run 的事件；`after_sequence` 用于断点续读。

        只以 `run_id`（主键的一部分，全局唯一）为界，不提供跨 run / 跨租户的读取路径。
        """
        with self._lock:
            rows = list(self._events.get(run_id, ()))
        events = sorted((event for _occurred_at, event in rows), key=lambda event: event.sequence)
        if after_sequence is None:
            return events
        return [event for event in events if event.sequence > after_sequence]

    def purge_events_before(self, cutoff: datetime) -> int:
        """删除 `occurred_at < cutoff` 的运行事件，返回删除条数（保留期清理入口）。

        只清理运行事件：**审计不可删除**（`delivery-remaining-checklist` 10.1），
        本方法不触碰任何审计数据。被清理的 run 的状态行与 `event_count` 保持不动
        （计数不回退 ⇒ 后续事件的序号继续单调递增）。
        """
        removed = 0
        with self._lock:
            for run_id in list(self._events):
                rows = self._events[run_id]
                kept = [(occurred_at, event) for occurred_at, event in rows if occurred_at >= cutoff]
                removed += len(rows) - len(kept)
                if kept:
                    self._events[run_id] = kept
                else:
                    del self._events[run_id]
        return removed

    def save_checkpoint(self, state: RuntimeState) -> dict[str, object]:
        with self._lock:
            state.checkpoint = {"status": state.status, "completed_steps": list(state.completed_steps), "next_step": len(state.completed_steps)}
            return dict(state.checkpoint)
