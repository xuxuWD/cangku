from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain import PolicyError, Task, TaskNotFound, UserContext

from .contracts import AgentPlan, RuntimeContext
from .mock import MockRuntime
from .policy import RuntimePolicy
from .registry import RuntimeRegistry
from .state import RuntimeStateStore


class RunAccessDenied(ValueError):
    pass


class RunApprovalDenied(ValueError):
    """决议运行审批的权限不满足（接口层按 403 处理）。"""


_APPROVER_ROLES = frozenset({'ceo', 'super_admin'})
# 只有非终态运行里的审批才可决议；终态运行的待办列出即误导。
_ACTIVE_STATUSES = frozenset({'running', 'paused'})


@dataclass(frozen=True)
class PendingRunApproval:
    """待决议的运行审批；供「待我审批」聚合展示与跳转。"""

    run_id: str
    approval_id: str
    task_id: str
    requested_by: str
    created_at: datetime
    step_id: str | None = None
    tool: str | None = None


class RuntimeService:
    def __init__(self, task_store: Any, *, registry: RuntimeRegistry | None = None, state_store: RuntimeStateStore | None = None, policy: RuntimePolicy | None = None, run_metrics: Any = None) -> None:
        self.task_store = task_store
        self.state_store = state_store or RuntimeStateStore()
        self.registry = registry or RuntimeRegistry()
        self.policy = policy or RuntimePolicy('policy-1')
        self.run_metrics = run_metrics
        if 'mock' not in self.registry.keys():
            self.registry.register('mock', MockRuntime(self.state_store))

    def _task(self, context: UserContext, task_id: str) -> Task:
        try:
            task = self.task_store.get(context, task_id)
        except TaskNotFound as exc:
            raise RunAccessDenied('任务不存在') from exc
        return task

    def _context(self, task: Task, actor: UserContext, *, mode: str) -> RuntimeContext:
        if actor.user_id != task.created_by and actor.role not in {'ceo', 'super_admin'}:
            raise RunAccessDenied('当前员工无权操作此任务')
        return RuntimeContext(
            tenant_id=task.tenant_id, user_id=task.created_by, role_key=task.employee_key,
            mode=mode, project_id=task.project_id, task_id=task.id, device_id=f'device:{actor.user_id}',
            knowledge_scope=(), file_scope=(), budget_cents=max(0, int(task.budget * 100)),
            risk_level=task.risk_level.value, policy_version=self.policy.policy_version,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

    def start(self, actor: UserContext, task_id: str, runtime_key: str, steps: list[dict[str, Any]], mode: str, *, proposal_id: str | None = None) -> tuple[str, str, str]:
        task = self._task(actor, task_id)
        context = self._context(task, actor, mode=mode)
        adapter = self.registry.get(runtime_key)
        plan = AgentPlan.from_steps(steps)
        if not plan.steps:
            plan = AgentPlan.from_steps([{'step_id': 'plan', 'kind': 'read', 'tool': 'plan.create'}])
        bind_state_store = getattr(adapter, "bind_state_store", None)
        if callable(bind_state_store):
            bind_state_store(self.state_store)
        started = time.perf_counter()
        run_id = adapter.start_run(context, plan)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._sync_run_record(actor, run_id, runtime_key, latency_ms=latency_ms, proposal_id=proposal_id)
        return run_id, runtime_key, context.policy_version

    def pause(self, actor: UserContext, run_id: str, reason: str) -> None:
        key, adapter, _state = self.adapter_for_task(actor, run_id)
        started = time.perf_counter()
        adapter.pause_run(run_id, reason)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def resume(self, actor: UserContext, run_id: str) -> None:
        key, adapter, _state = self.adapter_for_task(actor, run_id)
        started = time.perf_counter()
        adapter.resume_run(run_id)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def cancel(self, actor: UserContext, run_id: str, reason: str) -> None:
        key, adapter, _state = self.adapter_for_task(actor, run_id)
        started = time.perf_counter()
        adapter.cancel_run(run_id, reason)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def decide_approval(self, actor: UserContext, run_id: str, approval_id: str, approved: bool) -> None:
        """决议运行内的审批项：仅 CEO/超级管理员，且发起人不能自审。"""
        key, adapter, state = self.adapter_for_task(actor, run_id)
        self._ensure_decider(actor, state)
        started = time.perf_counter()
        adapter.decide_approval(run_id, approval_id, approved)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    @staticmethod
    def _ensure_decider(actor: UserContext, state: Any) -> None:
        if actor.role not in _APPROVER_ROLES:
            raise RunApprovalDenied('只有 CEO 或超级管理员可以决议运行审批')
        if actor.user_id == state.context.user_id:
            raise RunApprovalDenied('发起人不能审批自己发起的运行')

    def list_pending_approvals(self, actor: UserContext, *, limit: int = 50) -> list[PendingRunApproval]:
        """本租户待决议的运行审批（只读）。

        只覆盖**非终态运行**里仍为 `pending` 的审批；运行时状态是进程内状态，因此
        重启或多进程部署下只能看到当前进程创建的运行（已登记为已知限制）。
        """
        pending: list[PendingRunApproval] = []
        for state in self.state_store.list_for_tenant(actor.tenant_id):
            if state.status not in _ACTIVE_STATUSES:
                continue
            tools = {step.step_id: step.tool for step in state.plan.steps}
            for approval_id, status in state.approvals.items():
                if status != 'pending':
                    continue
                is_step = approval_id in tools
                pending.append(
                    PendingRunApproval(
                        run_id=state.run_id,
                        approval_id=approval_id,
                        task_id=state.context.task_id,
                        requested_by=state.context.user_id,
                        created_at=state.created_at,
                        step_id=approval_id if is_step else None,
                        tool=tools.get(approval_id),
                    )
                )
        pending.sort(key=lambda item: item.created_at, reverse=True)
        return pending[:limit]

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _sync_run_record(self, actor: UserContext, run_id: str, runtime_key: str, *, latency_ms: int, proposal_id: str | None = None) -> None:
        """把运行状态回写到运行记录；未注入指标服务时保持旧行为（不记录）。"""
        if self.run_metrics is None:
            return
        state = self.snapshot(actor, run_id)
        self.run_metrics.record_state(
            tenant_id=state.context.tenant_id,
            proposal_id=proposal_id,
            runtime_key=runtime_key,
            state=state,
            latency_ms=latency_ms,
        )

    def adapter_for(self, actor: UserContext, run_id: str):
        for key in self.registry.keys():
            adapter = self.registry.get(key)
            try:
                state = adapter.get_checkpoint(run_id)
            except (KeyError, LookupError):
                continue
            if state is not None:
                return key, adapter
        raise RunAccessDenied('运行不存在')

    def adapter_for_task(self, actor: UserContext, run_id: str):
        key, adapter = self.adapter_for(actor, run_id)
        try:
            state = self.state_store.get(run_id)
        except KeyError as exc:
            raise RunAccessDenied('运行不存在') from exc
        if state.context.tenant_id != actor.tenant_id:
            raise RunAccessDenied('运行不存在')
        if actor.user_id != state.context.user_id and actor.role not in {'ceo', 'super_admin'}:
            raise RunAccessDenied('当前员工无权操作此运行')
        return key, adapter, state

    def snapshot(self, actor: UserContext, run_id: str):
        """只读运行快照；租户与归属校验与适配器选择一致。"""
        _key, _adapter, state = self.adapter_for_task(actor, run_id)
        return state
