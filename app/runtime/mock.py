from __future__ import annotations

from typing import Any

from .contracts import AgentPlan, AgentRuntimeAdapter, RuntimeContext, RuntimeEvent, RuntimeEventType
from .state import RuntimeState, RuntimeStateStore


class MockRuntime(AgentRuntimeAdapter):
    def __init__(self, store: RuntimeStateStore) -> None:
        self.store = store

    def _emit(self, state: RuntimeState, event_type: RuntimeEventType, payload: dict[str, Any] | None = None) -> RuntimeEvent:
        event = RuntimeEvent(state.run_id, len(state.events) + 1, event_type, payload or {})
        self.store.append(state, event)
        return event

    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str:
        state = self.store.create(context, plan)
        self._emit(state, RuntimeEventType.PLAN_CREATED, {"step_count": len(plan.steps)})
        for step in plan.steps:
            if step.requires_approval:
                state.approvals[step.step_id] = "pending"
                self._emit(state, RuntimeEventType.APPROVAL_REQUESTED, {"step_id": step.step_id, "tool": step.tool})
            elif step.kind in {"read", "search"}:
                self._emit(state, RuntimeEventType.STEP_STARTED, {"step_id": step.step_id, "tool": step.tool})
                state.usage["tool_calls"] += 1
                state.usage["successful_tools"] += 1
                state.completed_steps.append(step.step_id)
                self._emit(state, RuntimeEventType.TOOL_RESULT, {"step_id": step.step_id, "status": "success"})
        if not state.approvals:
            state.status = "completed"
            self._emit(state, RuntimeEventType.RUN_COMPLETED, {"step_count": len(plan.steps)})
        self.store.save_checkpoint(state)
        return state.run_id

    def stream_events(self, run_id: str, cursor: str | None = None) -> list[RuntimeEvent]:
        state = self.store.get(run_id)
        if not cursor:
            return list(state.events)
        try:
            sequence = int(cursor.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            sequence = 0
        return [event for event in state.events if event.sequence > sequence]

    def pause_run(self, run_id: str, reason: str) -> None:
        state = self.store.get(run_id)
        state.status = "paused"
        self._emit(state, RuntimeEventType.RUN_PAUSED, {"reason": reason})
        self.store.save_checkpoint(state)

    def resume_run(self, run_id: str) -> None:
        state = self.store.get(run_id)
        if state.status == "cancelled":
            return
        state.status = "running"
        self.store.save_checkpoint(state)

    def cancel_run(self, run_id: str, reason: str) -> None:
        state = self.store.get(run_id)
        state.status = "cancelled"
        self._emit(state, RuntimeEventType.RUN_FAILED, {"reason": reason, "cancelled": True})
        self.store.save_checkpoint(state)

    def request_approval(self, run_id: str, action: dict[str, Any]) -> str:
        state = self.store.get(run_id)
        approval_id = f"approval-{len(state.approvals) + 1}"
        state.approvals[approval_id] = "pending"
        self._emit(state, RuntimeEventType.APPROVAL_REQUESTED, {"approval_id": approval_id, "action": action})
        return approval_id

    def get_checkpoint(self, run_id: str) -> dict[str, object] | None:
        return self.store.get(run_id).checkpoint

    def replay_run(self, run_id: str, from_step: str | None = None) -> str:
        state = self.store.get(run_id)
        self._emit(state, RuntimeEventType.CHECKPOINT_SAVED, {"from_step": from_step, "replay": True})
        return run_id

    def get_usage(self, run_id: str) -> dict[str, int]:
        return dict(self.store.get(run_id).usage)

    def health(self) -> dict[str, object]:
        return {"runtime": "mock", "version": "0.1.0", "capabilities": ["pause", "resume", "replay"], "sandbox": "deterministic"}
