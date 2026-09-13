from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain import PolicyError, Task, TaskNotFound, UserContext

from .authorization import (
    ExecutionAuthorization,
    ExecutionNotAuthorized,
    ensure_source_allowed,
    plan_digest,
)
from .contracts import AgentPlan, RuntimeContext
from .mock import MockRuntime
from .policy import RuntimePolicy
from .records import RunRecordNotFound
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
        # 授权位与运行记录同库同表：直接复用运行记录仓储，不另建存储通道。
        self.run_records = getattr(run_metrics, "store", None)
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
        key, adapter, state = self.adapter_for_task(actor, run_id)
        # 推进执行前过授权闸门：已登记授权位的运行，若计划与批准时不一致即拒绝恢复。
        self.ensure_execution_authorized(actor, run_id, state.plan)
        started = time.perf_counter()
        adapter.resume_run(run_id)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def cancel(self, actor: UserContext, run_id: str, reason: str) -> None:
        key, adapter, _state = self.adapter_for_task(actor, run_id)
        started = time.perf_counter()
        adapter.cancel_run(run_id, reason)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def decide_approval(
        self, actor: UserContext, run_id: str, approval_id: str, approved: bool, *, source: str = "user"
    ) -> None:
        """决议运行内的审批项：仅 CEO/超级管理员，且发起人不能自审。

        这里也是**授权位的写入口**：通过即登记「谁在何时批准了哪个计划」，驳回即撤销
        既有授权。`source` 由服务端判定（**不来自请求体**）并在白名单内校验，
        `agent` 被显式拒绝——数字员工不能批准自己要执行的动作。
        """
        key, adapter, state = self.adapter_for_task(actor, run_id)
        self._ensure_decider(actor, state)
        ensure_source_allowed(source)
        started = time.perf_counter()
        if approved:
            self._write_execution_authorization(actor, run_id, state.plan)
        else:
            self._clear_execution_authorization(actor, run_id)
        adapter.decide_approval(run_id, approval_id, approved)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def ensure_execution_authorized(self, actor: UserContext, run_id: str, plan: AgentPlan) -> None:
        """推进执行前的闸门：已登记授权位的运行，其当前计划必须与授权的计划一致。

        三种情形（口径见段一规格 §2.3）：

        * **未装配运行记录仓储** → **拒绝**（fail-closed）：无授权位可查时宁可不执行（段二规格 §3.2
          「两条必须收窄的既有实现」明令**不得**沿用 `run_records is None → return` 的 fail-open 行为）；
        * **有仓储但查不到该运行** → **拒绝**（fail-closed：状态不一致时宁可不执行）；
        * **有授权位但摘要不一致** → **拒绝**（授权已失效，需重新审批）；
        * 无授权位的运行（计划里没有需要审批的步骤）→ 放行，它不是「审批驱动」的运行。

        ⚠️ 段一没有真实工具，因此这里**拦不到真实副作用**。段二接入真实工具后，
        **工具执行器必须在每次执行副作用工具前调用本方法**；届时配合「有副作用 ⇒
        `requires_approval=True`」的工具闸门，这道校验才真正拦得住东西。
        """
        if self.run_records is None:
            raise ExecutionNotAuthorized(
                "未装配运行记录仓储，无法校验执行授权，已拒绝推进执行（fail-closed）"
            )
        try:
            record = self.run_records.get(actor.tenant_id, run_id)
        except RunRecordNotFound as exc:
            raise ExecutionNotAuthorized("运行记录不存在，已拒绝推进执行") from exc
        authorization = record.execution_authorization
        if authorization is None:
            return
        if authorization.plan_digest != plan_digest(plan):
            raise ExecutionNotAuthorized("授权已失效：计划在批准之后发生了变更，需重新审批")

    def _write_execution_authorization(self, actor: UserContext, run_id: str, plan: AgentPlan) -> None:
        self._store_execution_authorization(
            actor,
            run_id,
            ExecutionAuthorization(
                authorized_by=actor.user_id,
                plan_digest=plan_digest(plan),
                authorized_at=datetime.now(UTC),
            ),
        )

    def _clear_execution_authorization(self, actor: UserContext, run_id: str) -> None:
        self._store_execution_authorization(actor, run_id, None)

    def _store_execution_authorization(
        self, actor: UserContext, run_id: str, authorization: ExecutionAuthorization | None
    ) -> None:
        if self.run_records is None:
            return
        try:
            self.run_records.set_execution_authorization(actor.tenant_id, run_id, authorization)
        except RunRecordNotFound as exc:
            # 授权位必须落库；落不下就不许推进执行（fail-closed）。
            raise ExecutionNotAuthorized("运行记录不存在，无法登记执行授权") from exc

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
        for state in self.state_store.list_for_tenant(actor.tenant_id, statuses=_ACTIVE_STATUSES):
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
