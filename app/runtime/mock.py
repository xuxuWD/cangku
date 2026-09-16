from __future__ import annotations

from typing import Any

from .contracts import (
    AgentPlan,
    AgentRuntimeAdapter,
    ApprovalAlreadyDecided,
    ApprovalNotFound,
    RunNotDecidable,
    RuntimeContext,
    RuntimeEvent,
    RuntimeEventType,
)
from .state import RuntimeState, RuntimeStateStore

# 仅 Mock 运行时的失败注入约定；真实适配器不识别该前缀。
FAIL_TOOL_PREFIX = "fail."

# 终态：任何审批都不应再改变这些状态。
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class MockRuntime(AgentRuntimeAdapter):
    def __init__(self, store: RuntimeStateStore) -> None:
        self.store = store

    def _emit(self, state: RuntimeState, event_type: RuntimeEventType, payload: dict[str, Any] | None = None) -> RuntimeEvent:
        # 序号从 1 开始、同一 run 内单调递增：用状态上的**事件计数**生成
        # （事件已迁到 append-only 表，不再有 `state.events` 可以取长度；计数随状态行落库，
        # 因此重新加载后仍能接续，清理旧事件后也不会回退）。
        event = RuntimeEvent(state.run_id, state.event_count + 1, event_type, payload or {})
        self.store.append(state, event)
        return event

    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str:
        state = self.store.create(context, plan)
        self._emit(state, RuntimeEventType.PLAN_CREATED, {"step_count": len(plan.steps)})
        for step in plan.steps:
            # 确定性失败注入：工具名以 "fail." 前缀开头即失败，便于复现终态与失败通知。
            if step.tool.startswith(FAIL_TOOL_PREFIX):
                self._emit(state, RuntimeEventType.STEP_STARTED, {"step_id": step.step_id, "tool": step.tool})
                state.usage["tool_calls"] += 1
                self._emit(
                    state,
                    RuntimeEventType.TOOL_RESULT,
                    {"step_id": step.step_id, "status": "error", "reason": "tool_error"},
                )
                state.status = "failed"
                self._emit(
                    state,
                    RuntimeEventType.RUN_FAILED,
                    {"step_id": step.step_id, "tool": step.tool, "reason": "tool_error"},
                )
                self.store.save_checkpoint(state)
                return state.run_id
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
        # 运行不存在时与改造前一致：`get` 抛 KeyError（调用方的 404 语义依赖它）。
        self.store.get(run_id)
        if not cursor:
            return self.store.list_events(run_id)
        try:
            sequence = int(cursor.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            sequence = 0
        return self.store.list_events(run_id, sequence)

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

    def decide_approval(self, run_id: str, approval_id: str, approved: bool) -> None:
        """决议一个待审批项：通过则执行对应步骤，驳回则立即失败且不再执行。"""
        state = self.store.get(run_id)
        if state.status in _TERMINAL_STATUSES:
            # 终态即终态：不允许用剩余审批把已结束的运行复活。
            raise RunNotDecidable(run_id)
        if approval_id not in state.approvals:
            raise ApprovalNotFound(approval_id)
        if state.approvals[approval_id] != "pending":
            raise ApprovalAlreadyDecided(approval_id)
        state.approvals[approval_id] = "approved" if approved else "rejected"
        self._emit(
            state,
            RuntimeEventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "approved": approved},
        )
        if not approved:
            state.status = "failed"
            self._emit(
                state,
                RuntimeEventType.RUN_FAILED,
                {"approval_id": approval_id, "reason": "approval_rejected"},
            )
            self.store.save_checkpoint(state)
            return
        step = next((item for item in state.plan.steps if item.step_id == approval_id), None)
        if step is not None and step.step_id not in state.completed_steps:
            state.usage["tool_calls"] += 1
            state.usage["successful_tools"] += 1
            state.completed_steps.append(step.step_id)
            self._emit(state, RuntimeEventType.TOOL_RESULT, {"step_id": step.step_id, "status": "success"})
        if all(item != "pending" for item in state.approvals.values()):
            state.status = "completed"
            self._emit(state, RuntimeEventType.RUN_COMPLETED, {"step_count": len(state.plan.steps)})
        self.store.save_checkpoint(state)

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
