from __future__ import annotations

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


class RuntimeService:
    def __init__(self, task_store: Any, *, registry: RuntimeRegistry | None = None, state_store: RuntimeStateStore | None = None, policy: RuntimePolicy | None = None) -> None:
        self.task_store = task_store
        self.state_store = state_store or RuntimeStateStore()
        self.registry = registry or RuntimeRegistry()
        self.policy = policy or RuntimePolicy('policy-1')
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

    def start(self, actor: UserContext, task_id: str, runtime_key: str, steps: list[dict[str, Any]], mode: str) -> tuple[str, str, str]:
        task = self._task(actor, task_id)
        context = self._context(task, actor, mode=mode)
        adapter = self.registry.get(runtime_key)
        plan = AgentPlan.from_steps(steps)
        if not plan.steps:
            plan = AgentPlan.from_steps([{'step_id': 'plan', 'kind': 'read', 'tool': 'plan.create'}])
        run_id = adapter.start_run(context, plan)
        return run_id, runtime_key, context.policy_version

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
        state = self.state_store.get(run_id)
        if state.context.tenant_id != actor.tenant_id:
            raise RunAccessDenied('运行不存在')
        if actor.user_id != state.context.user_id and actor.role not in {'ceo', 'super_admin'}:
            raise RunAccessDenied('当前员工无权操作此运行')
        return key, adapter, state
