from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from .contracts import AgentPlan, RuntimeContext, RuntimeEvent


@dataclass
class RuntimeState:
    run_id: str
    context: RuntimeContext
    plan: AgentPlan
    events: list[RuntimeEvent] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    status: str = "running"
    checkpoint: dict[str, object] | None = None
    approvals: dict[str, str] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: {"tool_calls": 0, "successful_tools": 0})
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class RuntimeStateStore:
    def __init__(self) -> None:
        self._states: dict[str, RuntimeState] = {}
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

    def list_for_tenant(self, tenant_id: str) -> list[RuntimeState]:
        """按租户列出运行状态。

        注意：运行时状态本身是**进程内状态**（所有存储模式都一样），因此这里只能看到
        当前进程创建的运行；重启或多进程部署下结果不完整（已登记为已知限制）。
        """
        with self._lock:
            return [state for state in self._states.values() if state.context.tenant_id == tenant_id]

    def append(self, state: RuntimeState, event: RuntimeEvent) -> None:
        with self._lock:
            state.events.append(event)

    def save_checkpoint(self, state: RuntimeState) -> dict[str, object]:
        with self._lock:
            state.checkpoint = {"status": state.status, "completed_steps": list(state.completed_steps), "next_step": len(state.completed_steps)}
            return dict(state.checkpoint)
