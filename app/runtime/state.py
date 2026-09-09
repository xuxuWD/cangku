from __future__ import annotations

from dataclasses import dataclass, field
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

    def append(self, state: RuntimeState, event: RuntimeEvent) -> None:
        with self._lock:
            state.events.append(event)

    def save_checkpoint(self, state: RuntimeState) -> dict[str, object]:
        with self._lock:
            state.checkpoint = {"status": state.status, "completed_steps": list(state.completed_steps), "next_step": len(state.completed_steps)}
            return dict(state.checkpoint)
