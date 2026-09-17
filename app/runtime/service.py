from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Sequence

from app.commercial.usage import UsageEntry
from app.domain import PolicyError, Task, TaskNotFound, UserContext
from app.tool_execution.store import ReasonCode, ToolActionStatus

from .authorization import (
    AuthorizationAction,
    ExecutionAuthorization,
    ExecutionNotAuthorized,
    ensure_source_allowed,
    plan_digest,
    validate_authorization_action,
)
from .contracts import AgentPlan, RuntimeContext
from .mock import MockRuntime
from .policy import RuntimePolicy
from .records import RunRecord, RunRecordNotFound
from .registry import RuntimeRegistry
from .state import RuntimeState, RuntimeStateStore


def _yuan_to_cents(amount: float) -> int:
    """元 → 分：十进制精确换算，避免二进制浮点尾差（宪法 §三「金额不用浮点（整数分或 Decimal）」）。

    修复前为 `int(amount * 100)`：`0.29 * 100 = 28.999…` 截断成 `28`，少 1 分。
    先 `Decimal(str(amount))` 走十进制字符串（直接 `Decimal(0.29)` 会把浮点误差原样带入），
    乘 100 后 `ROUND_HALF_UP` 取整。存储 / 契约 / 前端其余环节不在本次加固范围（另立专项）。
    """
    return int((Decimal(str(amount)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


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
    def __init__(self, task_store: Any, *, registry: RuntimeRegistry | None = None, state_store: RuntimeStateStore | None = None, policy: RuntimePolicy | None = None, run_metrics: Any = None, tool_actions: Any = None, usage_ledger: Any = None, member_run_reader: Any = None) -> None:
        self.task_store = task_store
        self.state_store = state_store or RuntimeStateStore()
        self.registry = registry or RuntimeRegistry()
        self.policy = policy or RuntimePolicy('policy-1')
        self.run_metrics = run_metrics
        # 追加式用量账本（商业化 G0）：只记「按运行 1 unit、cost_cents 恒 0」，
        # **不向员工计费**（`docs/superpowers/specs/2026-09-06-commercial-g0-design.md:72`）。
        # 未装配（既有单测 / 段一路径）→ 不记账，保持旧行为。
        self.usage_ledger = usage_ledger
        # 授权位与运行记录同库同表：直接复用运行记录仓储，不另建存储通道。
        self.run_records = getattr(run_metrics, "store", None)
        # 027 待批动作仓储（可选）：仅用于 ⑦ 的「待判动作序列」投影与「是否需审批路径」判定。
        # 未装配（段一路径）→ 保持既有行为（仅比对运行级摘要）。
        self.tool_actions = tool_actions
        # P2c-6（可选）：会话成员对**运行级读路径**的可见性回调 `(actor, run_id) -> bool`。
        # 未注入 ⇒ 不放松（与改造前完全一致）；**只影响读路径**，控制类动作绝不使用它。
        self.member_run_reader = member_run_reader
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
            knowledge_scope=(), file_scope=(), budget_cents=max(0, _yuan_to_cents(task.budget)),
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
        # 推进执行前过授权闸门：**显式传入**从 027 投影的待判动作序列（§4.1.7-5；
        # 未装配 027 的段一路径传 None，退化为仅比对运行级摘要）。
        self.ensure_execution_authorized(
            actor, run_id, state.plan, actions=self._authorization_actions(actor.tenant_id, run_id)
        )
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
        # 段二 §3.2 / §4.1.6-4：决议必须**同时**落 `027`（唯一授权权威）——否则审批通过后
        # `ToolExecutionService.resume` 从 `027` 取不到 `approved` 行，重跑永不可达。未装配 `027`
        # （段一路径）时为 no-op，既有行为不变。写在适配器决议**之后**：适配器拒绝（404/409）时
        # 不留下「027 已 approved 但决议未生效」的错位。
        self._decide_tool_actions(actor, run_id, approval_id, approved, source=source)
        self._sync_run_record(actor, run_id, key, latency_ms=self._elapsed_ms(started))

    def _decide_tool_actions(
        self,
        actor: UserContext,
        run_id: str,
        approval_id: str,
        approved: bool,
        *,
        source: str,
    ) -> None:
        """把 `027` 中与该决议入口键对应的待批动作置为 `approved` / `rejected`（逐项授权的前提）。"""
        if self.tool_actions is None:
            return
        rows = self.tool_actions.list_for_run(actor.tenant_id, run_id)
        row = next(
            (item for item in rows if item.approval_id == approval_id), None
        )
        # 非工具执行审批（段一 / 计划步审批）在 `027` 中没有对应行 → no-op。
        if row is None or row.status is not ToolActionStatus.PENDING:
            return
        decided = replace(
            row,
            status=ToolActionStatus.APPROVED if approved else ToolActionStatus.REJECTED,
            decided_by=actor.user_id,
            decided_at=datetime.now(UTC),
            decision_source=source,
            # 驳回原因用受控枚举码（不得写自由文本）。
            reason_code=None if approved else ReasonCode.APPROVAL_DENIED,
            # **通过时保留正文密文**：审批后的重跑（§4.1.6-4）必须从 `body_ciphertext` 解密还原正文参数，
            # 提前清空会让重跑落到「解密失败」行（502）。驳回时不再执行 → 即时清空两列
            # （`body_check` 要求同有同无）；通过后的密文由与审批同寿的 TTL 清理任务收尾（§4.1.5）。
            body_ciphertext=None if not approved else row.body_ciphertext,
            body_expires_at=None if not approved else row.body_expires_at,
        )
        self.tool_actions.upsert(decided)

    def ensure_execution_authorized(
        self,
        actor: UserContext,
        run_id: str,
        plan: AgentPlan,
        actions: Sequence[AuthorizationAction] | None = None,
    ) -> None:
        """推进执行前的闸门：需审批路径必须逐项持有 027 授权（规格 §4.1.7-5）。

        三种情形（口径见段一规格 §2.3 与段二 §4.1.7-5）：

        * **未装配运行记录仓储** → **拒绝**（fail-closed）：无授权位可查时宁可不执行（段二规格 §3.2
          「两条必须收窄的既有实现」明令**不得**沿用 `run_records is None → return` 的 fail-open 行为）；
        * **有仓储但查不到该运行** → **拒绝**（fail-closed：状态不一致时宁可不执行）。

        `actions`（待判动作只读投影序列）的**缺省语义定死**（§4.1.7-5，不得自行放宽）：

        * `actions` 缺省（`None` / 空序列）**只允许**出现在「⑤ 判定**无需审批**」路径；该路径**只退化
          为运行级摘要比对**（`026` 路径，仅比对粒度退化、**不含** fail-open），并在完成 ②③④ 后进入 ⑧；
        * `actions` 缺省却处于「⑤ 判定**需审批**」路径（本运行在 `027` 中存在 `requires_approval` 的行）
          → **必须拒绝**（接口层 409）；**不得**把缺省当作「跳过 ⑥⑦ 直接执行」的开关；
        * `actions` **显式提供** → ⑦ 逐项校验：每个投影 8 字段非空且 `plan_digest` 与当前计划一致；
          仍叠加运行级摘要比对。

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
        current_digest = plan_digest(plan)

        if not actions:
            # 缺省（None / 空序列）：只允许「⑤ 判定无需审批」路径。
            if self._is_approval_driven(actor.tenant_id, run_id):
                raise ExecutionNotAuthorized(
                    "需审批路径必须显式传入待判动作序列，actions 缺省不被允许（fail-closed，接口层 409）"
                )
            # 该路径只退化为运行级摘要比对（026 路径），不跳过 ②③④。
            if authorization is not None and authorization.plan_digest != current_digest:
                raise ExecutionNotAuthorized("授权已失效：计划在批准之后发生了变更，需重新审批")
            return

        # actions 显式提供 → ⑦ 逐项校验（逐行核 8 字段非空 + 计划摘要一致）。
        for action in actions:
            validate_authorization_action(action)
            if action.plan_digest != current_digest:
                raise ExecutionNotAuthorized(
                    "授权已失效：待判动作的计划摘要与当前计划不一致，需重新审批"
                )
        if authorization is not None and authorization.plan_digest != current_digest:
            raise ExecutionNotAuthorized("授权已失效：计划在批准之后发生了变更，需重新审批")

    def _is_approval_driven(self, tenant_id: str, run_id: str) -> bool:
        """本运行是否处于「⑤ 判定需审批」路径：`027` 中是否存在 `requires_approval` 的行。

        未装配 `027`（段一路径）→ `False`：保持既有行为（仅比对运行级摘要），不误伤段一测试。
        """
        if self.tool_actions is None:
            return False
        rows = self.tool_actions.list_for_run(tenant_id, run_id)
        return any(bool(getattr(row, "requires_approval", False)) for row in rows)

    def _authorization_actions(
        self, tenant_id: str, run_id: str
    ) -> list[AuthorizationAction] | None:
        """从 `027` 投影待判动作序列；未装配 `027` 或无待判动作 → `None`（缺省）。"""
        if self.tool_actions is None:
            return None
        rows = self.tool_actions.list_for_run(tenant_id, run_id)
        projected = [
            AuthorizationAction.from_row(row)
            for row in rows
            if bool(getattr(row, "requires_approval", False))
        ]
        return projected or None

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
        record = self.run_metrics.record_state(
            tenant_id=state.context.tenant_id,
            proposal_id=proposal_id,
            runtime_key=runtime_key,
            state=state,
            latency_ms=latency_ms,
        )
        # 运行终态同步钩子：这里是全仓**唯一**回写运行记录的地方，故也是用量记账的唯一落点。
        self._record_usage_on_terminal(state, record)

    def _record_usage_on_terminal(self, state: RuntimeState, record: RunRecord) -> None:
        """运行到终态时向追加式用量账本记一条「1 run = 1 unit」，`cost_cents` 恒 0。

        依据与本实现的固定口径：

        - **方案 A（用户裁决）**：`docs/superpowers/specs/2026-09-06-commercial-g0-design.md:72`
          「内部版……记录用量，**不向员工计费**」⇒ `units=1`、`cost_cents=0`；
          **不引入单价表、换算公式或任何定价真源**。
        - **幂等维度**：真源 `:171`「用量账本**按任务和运行幂等**记账」⇒ 幂等键同时含
          `task_id` 与 `run_id`：`usage:{task_id}:{run_id}`。真源只约定幂等维度，
          **键的格式由本实现确定**。
        - **`units` 语义**：沿用「未定义、只展示原值」口径
          （`docs/superpowers/specs/2026-09-12-usage-billing-page-design.md:49/:66`），
          **不解释成 token / 次数 / 条数**。`state.usage` 是运行内计数
          （`app/runtime/state.py:22`），**不是**商业账本 ⇒ 不拿 `tool_calls` 当 units。
        - **只在终态写入**：`record.finish_reason is not None`（由运行状态单向推导）时才写，
          避免运行中反复写；账本**只追加、不原地修改**，重复终态同步（如 start 后 cancel）
          由幂等键去重。
        - **冲正未接线（本期不做）**：`UsageLedger.reverse` / `reverse_usage` **不接线、不删除**。
        """
        if self.usage_ledger is None:
            return
        if record.finish_reason is None:
            return
        self.usage_ledger.append(
            UsageEntry(
                idempotency_key=f"usage:{state.context.task_id}:{state.run_id}",
                tenant_id=state.context.tenant_id,
                units=1,
                cost_cents=0,
            )
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

    def adapter_for_task(self, actor: UserContext, run_id: str, *, member_reader: bool = False):
        """按运行号取适配器 + 权威状态；跨租户 / 未知运行 / 非本人一律拒绝。

        `member_reader=True`（**仅运行级读端点显式传入**，P2c-6）：当 actor 不是发起人也不是
        CEO / 超管时，再问一次注入的 `member_run_reader(actor, run_id)`；回调恒 fail-closed
        （异常 / 未注入 ⇒ 不放松）。**控制类动作绝不传该开关**。
        """
        key, adapter = self.adapter_for(actor, run_id)
        try:
            state = self.state_store.get(run_id)
        except KeyError as exc:
            raise RunAccessDenied('运行不存在') from exc
        if state.context.tenant_id != actor.tenant_id:
            raise RunAccessDenied('运行不存在')
        if actor.user_id != state.context.user_id and actor.role not in {'ceo', 'super_admin'}:
            if not (member_reader and self._is_member_reader(actor, run_id)):
                raise RunAccessDenied('当前员工无权操作此运行')
        return key, adapter, state

    def _is_member_reader(self, actor: UserContext, run_id: str) -> bool:
        """会话成员的读可见性回调；未注入 / 任何异常一律 `False`（fail-closed，不猜测）。"""
        reader = self.member_run_reader
        if reader is None:
            return False
        try:
            return bool(reader(actor, run_id))
        except Exception:  # noqa: BLE001 - 判定不可用 ⇒ 不放松
            return False

    def snapshot(self, actor: UserContext, run_id: str):
        """只读运行快照；租户与归属校验与适配器选择一致。"""
        _key, _adapter, state = self.adapter_for_task(actor, run_id)
        return state
