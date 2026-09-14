"""对话入口路由：对话消息触发**真实工具执行**时自动创建「承载任务 + Run」（规格 §3.7 Y2）。

口径来源（真源）：
    - §3.7 Y2：复用既有 `/tasks/{task_id}/runs` 与 `/runs/{run_id}/approvals/*` 的**服务层**
      （`TaskStore.create` / `RuntimeService.start`），**不另造一套**；`workbench_run_records.task_id`
      保持 `NOT NULL`；承载任务字段口径按 Y2 表（`created_by` = 触发者、`budget=0`、
      `idempotency_key = conv-{conversation_id}-{key}`、`risk_level` = 该次工具风险档、
      建时 `status=queued`）。
    - §3.2 第四条：**幂等键 = 请求头 `Idempotency-Key`**；带键 ⇒ 真实执行 + 幂等；
      **不带键 ⇒ 不触发真实执行**，沿用既有 `stub=true` 通路（不创建承载任务 / 运行 / 任何副作用）。
    - §4.1.3：四态（`201`/`202`/拒绝码/首次失败）都写 `workbench_execution_idempotency`，
      重放**必须返回既有结果**；`⑥` 落库失败（`503`）**不写本表**。
    - §1.4 / §15 #11：`agent_key` 校验收紧 —— **执行入口**必须校验「存在且启用」。

⚠️ 关于「工具调用从哪来」：真源只规定「对话消息触发执行」，**未定义**自由文本如何映射到
具体工具（P2a 不做模型规划）。本实现取**最小可判定口径**：当消息触发执行时，`content`
必须是一段**结构化工具调用** JSON（`{"tool_key": str, "params": {...}}`），
非结构化内容一律 `422`（不静默执行）。`tool_invocation_resolver` 可注入，便于后续接真实模型。
该口径属**实现决策，待评审确认**。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from ..audit.models import AuditAction
from ..domain import (
    AuditEvent,
    IdempotencyConflict,
    PolicyError,
    RiskLevel,
    Task,
    TaskStatus,
    UserContext,
    ensure_can_create,
)
from ..runtime.authorization import plan_digest
from ..runtime.contracts import AgentPlan
from ..tool_execution.errors import ToolExecutionConfigError, ToolExecutionError
from ..tool_execution.service import ToolExecutionRequest
from ..workforce.models import needs_approval
from .idempotency import ExecutionIdempotencyRecord
from .models import (
    ConversationMessage,
    InvalidConversation,
    MessageRole,
    normalize_content,
)
from .redaction import redact_message_content

# 带键触发执行时，`content` 必须是结构化工具调用 JSON。
INVOCATION_TOOL_KEY_FIELD = "tool_key"
INVOCATION_PARAMS_FIELD = "params"

# 承载任务口径（§3.7 Y2 表）。
CONVERSATION_TASK_BUDGET = 0.0

_logger = logging.getLogger(__name__)


class ConversationExecutionError(ValueError):
    """执行期受控失败：携带 HTTP 语义，由接口层原样映射（`403`/`409`/`422`/`502`/`503`/`504`）。"""

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True)
class ToolInvocation:
    """一次结构化工具调用（`§3.1.1` 的 `executable + args[]` 口径的结构化载体）。"""

    tool_key: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class MessageExecutionResult:
    """对话消息的处理结果；`http_status` 由接口层写入响应状态码。"""

    http_status: int
    body: dict[str, object]


def parse_tool_invocation(content: str) -> ToolInvocation | None:
    """把对话消息解析为结构化工具调用；非结构化内容返回 `None`（调用方拒绝，不静默执行）。"""
    text = content.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    tool_key = payload.get(INVOCATION_TOOL_KEY_FIELD)
    params = payload.get(INVOCATION_PARAMS_FIELD, {})
    if not isinstance(tool_key, str) or not tool_key.strip():
        return None
    if not isinstance(params, dict):
        return None
    return ToolInvocation(tool_key=tool_key.strip(), params=params)


class ConversationExecutionService:
    """对话入口路由：把「带 `Idempotency-Key` 的消息」路由到承载任务 + Run + 工具执行。"""

    def __init__(
        self,
        *,
        conversations,
        conversation_store,
        task_store,
        runtime_service,
        tool_execution=None,
        idempotency=None,
        catalog=None,
        audit=None,
        directory_store=None,
        tool_invocation_resolver: Callable[[str], ToolInvocation | None] | None = None,
        runtime_key: str = "mock",
        mode: str = "product_manager",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.conversations = conversations
        self.conversation_store = conversation_store
        self.task_store = task_store
        self.runtime_service = runtime_service
        self.tool_execution = tool_execution
        self.idempotency = idempotency
        self.catalog = catalog
        self.audit = audit
        self.directory_store = directory_store
        self._resolve = tool_invocation_resolver or parse_tool_invocation
        self.runtime_key = runtime_key
        self.mode = mode
        self._now = now or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------ 公开入口

    def handle_message(
        self,
        context: UserContext,
        conversation_id: str,
        *,
        content: str,
        idempotency_key: str | None = None,
    ) -> MessageExecutionResult:
        """缺键（或未启用真实执行）⇒ 既有 `stub=true` 通路；带键 ⇒ 真实执行 + 幂等。"""
        if idempotency_key is None or self.tool_execution is None:
            user_message, reply = self.conversations.send_message(
                context, conversation_id, content=content
            )
            return MessageExecutionResult(
                http_status=201,
                body={
                    "message_id": user_message.message_id,
                    "conversation_id": user_message.conversation_id,
                    "stub": True,
                    "reply": _message_view(reply, stub=True),
                    "run_id": None,
                },
            )
        return self._execute(context, conversation_id, content=content, idempotency_key=idempotency_key)

    # ------------------------------------------------------------------ 幂等重放

    def _rebuild(self, context: UserContext, conversation_id: str, record: ExecutionIdempotencyRecord) -> MessageExecutionResult:
        """重放：直接复用首次结果——`http_status` 为唯一结果码来源（§4.1.3 R5-2）。"""
        if record.outcome == "executed":
            message = self._load_message(context, conversation_id, record.message_id)
            return MessageExecutionResult(
                http_status=record.http_status,
                body={
                    "message_id": message.message_id,
                    "conversation_id": message.conversation_id,
                    "stub": False,
                    "reply": _message_view(message, stub=False),
                    "run_id": record.run_id,
                },
            )
        if record.outcome == "pending_approval":
            message = self._load_message(context, conversation_id, record.message_id)
            return MessageExecutionResult(
                http_status=record.http_status,
                body={
                    "conversation_id": conversation_id,
                    "message_id": message.message_id,
                    "stub": False,
                    "status": "pending_approval",
                    "run_id": record.run_id,
                    "approval_id": record.approval_id,
                },
            )
        # `rejected` / `failed`：`message_id` 为空 → 仅由 `outcome` + `http_status` 重建确定响应。
        raise ConversationExecutionError(
            "该请求此前已被拒绝或失败", http_status=record.http_status
        )

    # ------------------------------------------------------------------ 首次执行

    def _execute(
        self,
        context: UserContext,
        conversation_id: str,
        *,
        content: str,
        idempotency_key: str,
    ) -> MessageExecutionResult:
        normalize_content(content)
        # 归属 / 跨租户 / 归档：仓储层与模型层统一判定（404 / 409）。
        conversation = self.conversation_store.get_conversation(context, conversation_id)

        existing = self.idempotency.get(
            context.tenant_id, context.user_id, conversation_id, idempotency_key
        )
        if existing is not None:
            return self._rebuild(context, conversation_id, existing)

        # agent_key 校验收紧（执行入口）：存在且启用，否则 422；同时取回治理两字段。
        governance = self._governance(context, conversation)
        autonomy_level, risk_threshold = governance

        invocation = self._resolve(content)
        if invocation is None:
            raise InvalidConversation("消息内容不是合法的工具调用（需为 {\"tool_key\": ..., \"params\": {...}}）")
        try:
            spec = self.catalog.get(invocation.tool_key)
        except ToolExecutionConfigError as exc:
            raise InvalidConversation("未知工具") from exc

        # `critical` 承载任务：非 CEO / 超管必须在 ① 之前以 403 拒绝（§3.7 Y2 末行）。
        try:
            ensure_can_create(context, spec.risk_level, CONVERSATION_TASK_BUDGET)
        except PolicyError as exc:
            raise ConversationExecutionError(str(exc), http_status=403) from exc

        requires_approval = bool(spec.requires_approval) or bool(
            needs_approval(autonomy_level, spec.risk_level.value, risk_threshold)
        )
        kind = "write" if spec.has_side_effect else "read"
        step_id = _new_step_id()

        task, task_created = self._create_task(context, conversation, spec, invocation, idempotency_key)
        plan = AgentPlan.from_steps(
            [
                {
                    "step_id": step_id,
                    "kind": kind,
                    "tool": spec.key,
                    "requires_approval": requires_approval,
                }
            ]
        )
        run_id, _runtime_key, _policy_version = self.runtime_service.start(
            context, task.id, self.runtime_key, _plan_steps(plan), self.mode
        )

        request = ToolExecutionRequest(
            tenant_id=context.tenant_id,
            run_id=run_id,
            task_id=task.id,
            step_id=step_id,
            tool_key=spec.key,
            params=invocation.params,
            requested_by=context.user_id,
            plan_digest=plan_digest(plan),
            autonomy_level=autonomy_level,
            risk_threshold=risk_threshold,
            # 审批入口键 = 承载计划步 id：使「决议端点 → 适配器决议 → 工具重跑」三者指向同一 id。
            approval_id=step_id if requires_approval else None,
        )

        try:
            result = self.tool_execution.execute(request, actor=context, plan=plan)
        except ToolExecutionError as exc:
            return self._handle_failure(
                context,
                conversation_id,
                idempotency_key,
                run_id,
                exc,
                created_task_id=task.id if task_created else None,
            )

        if result is None:  # 允许打桩返回 None（无执行结局）——不产生结果码，交由调用方兜底
            raise ConversationExecutionError("执行未返回结果", http_status=502)

        if result.outcome == "pending_approval":
            # §3.7 Y2：⑥ 落库成功（该动作进入等待审批）后，把承载任务由 `queued` 置 `pending_approval`。
            self._mark_task_pending_approval(context, task.id)
            self._append_message(
                context, conversation_id, MessageRole.USER, redact_message_content(content)
            )
            reply = self._append_message(
                context,
                conversation_id,
                MessageRole.ASSISTANT,
                "该操作需要人工审批后方可执行。",
            )
            body = {
                "conversation_id": conversation_id,
                "message_id": reply.message_id,
                "stub": False,
                "status": "pending_approval",
                "run_id": run_id,
                "approval_id": result.approval_id or step_id,
            }
            self._remember(
                context, conversation_id, idempotency_key,
                outcome="pending_approval", http_status=202,
                message_id=reply.message_id, run_id=run_id,
                approval_id=body["approval_id"],
            )
            return MessageExecutionResult(http_status=202, body=body)

        # executed
        self._append_message(
            context, conversation_id, MessageRole.USER, redact_message_content(content)
        )
        reply = self._append_message(
            context, conversation_id, MessageRole.ASSISTANT, "工具已执行完成。"
        )
        body = {
            "message_id": reply.message_id,
            "conversation_id": conversation_id,
            "stub": False,
            "reply": _message_view(reply, stub=False),
            "run_id": run_id,
        }
        self._remember(
            context, conversation_id, idempotency_key,
            outcome="executed", http_status=201,
            message_id=reply.message_id, run_id=run_id, approval_id=None,
        )
        return MessageExecutionResult(http_status=201, body=body)

    def _handle_failure(
        self,
        context: UserContext,
        conversation_id: str,
        idempotency_key: str,
        run_id: str,
        exc: ToolExecutionError,
        *,
        created_task_id: str | None = None,
    ) -> MessageExecutionResult:
        """按受控异常携带的 HTTP 语义落幂等行并抛出；**`503` 不写本表且回滚本次已创建对象**（§4.1.3）。

        §4.1.3 / §4.1.6-5：`⑥` 落库失败（`503`）与幂等行、承载任务、运行属**同一次请求的产物**——
        `⑥` 失败即整体回滚，故**不存在"首次 `503`"的行**，重放该键会**重新走一遍闸门**（此时未产生
        任何消息 / 任务 / 运行 / 副作用，不违反幂等）。
        """
        if exc.http_status == 503:
            # 撤销本次请求已创建的运行与承载任务（幂等行本就不写、消息在 ⑥ 成功后才追加 ⇒ 天然为 0）。
            self._compensate(context, run_id=run_id, task_id=created_task_id)
            raise ConversationExecutionError(str(exc) or "审批请求暂时无法登记，请稍后重试", http_status=503) from exc
        outcome = "failed" if exc.http_status in (502, 504) else "rejected"
        self._remember(
            context, conversation_id, idempotency_key,
            outcome=outcome, http_status=exc.http_status,
            message_id=None, run_id=run_id, approval_id=None,
        )
        raise ConversationExecutionError(str(exc) or "执行被拒绝", http_status=exc.http_status) from exc

    # ------------------------------------------------------------------ ⑥ 失败回滚（零残留）

    def _compensate(
        self, context: UserContext, *, run_id: str | None, task_id: str | None
    ) -> None:
        """⑥ 失败的回滚：撤销本次请求已创建的对象，使请求结束后**零残留**（§4.1.3）。

        顺序与创建相反（先运行、后承载任务）。两分支口径一致：Postgres 与 InMemory 均为**显式补偿**
        （本服务跨 4 个独立仓储，无共享事务可挂靠）——各仓储新增 `delete` / `remove` 方法承担撤销。
        任一步失败只记 `error` 日志，**不得掩盖对外的 `503`**，也不得删他人数据。
        """
        if run_id:
            run_records = getattr(self.runtime_service, "run_records", None)
            delete_run = getattr(run_records, "delete", None)
            if delete_run is not None:
                try:
                    delete_run(context.tenant_id, run_id)
                except Exception:  # noqa: BLE001 - 回滚失败只告警，不改变对外 503 语义
                    _logger.error("⑥ 失败回滚：运行记录撤销失败 run_id=%s", run_id)
            state_store = getattr(self.runtime_service, "state_store", None)
            remove_state = getattr(state_store, "remove", None)
            if remove_state is not None:
                try:
                    remove_state(run_id)
                except Exception:  # noqa: BLE001
                    _logger.error("⑥ 失败回滚：运行状态撤销失败 run_id=%s", run_id)
        if task_id:
            delete_task = getattr(self.task_store, "delete", None)
            if delete_task is not None:
                try:
                    delete_task(context.tenant_id, task_id)
                except Exception:  # noqa: BLE001
                    _logger.error("⑥ 失败回滚：承载任务撤销失败 task_id=%s", task_id)

    def _mark_task_pending_approval(self, context: UserContext, task_id: str) -> None:
        """⑥ 落库成功后把承载任务置 `pending_approval`（§3.7 Y2；走既有受控枚举，不新造字符串）。"""
        setter = getattr(self.task_store, "set_pending_approval", None)
        if setter is None:
            return
        setter(context, task_id)

    # ------------------------------------------------------------------ 承载任务

    def _governance(self, context: UserContext, conversation) -> tuple[str, str]:
        """`agent_key` 校验收紧：会话绑定的员工必须**存在且启用**，否则 `422`；返回治理两字段。

        `read_agent_governance` 是既有**非管理**只读入口（不暴露提示词 / 模型 / 工具面），
        对「不存在 / 已停用」一律返回 `None` —— 正好等于「存在且启用」的判据（§1.4 / §15 #11）。
        """
        agent_key = conversation.agent_key
        if not agent_key:
            raise InvalidConversation("会话未绑定数字员工，无法触发执行")
        governance = (
            self.directory_store.read_agent_governance(context, agent_key)
            if self.directory_store is not None
            else None
        )
        if governance is None:
            raise InvalidConversation("数字员工不存在或已停用，已拒绝路由到执行")
        return governance

    def _create_task(
        self,
        context: UserContext,
        conversation,
        spec,
        invocation: ToolInvocation,
        idempotency_key: str,
    ) -> tuple[Task, bool]:
        title = f"对话触发：{conversation.title or ''}".strip() or "对话触发执行"
        fingerprint = hashlib.sha256(
            json.dumps(
                {"tool_key": spec.key, "params": invocation.params},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        task = Task(
            tenant_id=context.tenant_id,
            project_id=None,
            created_by=context.user_id,
            employee_key=conversation.agent_key,
            title=title[:200],
            risk_level=spec.risk_level,
            budget=CONVERSATION_TASK_BUDGET,
            idempotency_key=f"conv-{conversation.conversation_id}-{idempotency_key}",
            request_fingerprint=fingerprint,
            status=TaskStatus.QUEUED,
        )
        task.audits.append(
            AuditEvent(action="task.created", actor_id=context.user_id, actor_role=context.role)
        )
        try:
            stored, created = self.task_store.create(context, task)
        except IdempotencyConflict as exc:
            raise ConversationExecutionError(str(exc), http_status=409) from exc
        return stored, created

    # ------------------------------------------------------------------ 消息与幂等写入

    def _append_message(
        self, context: UserContext, conversation_id: str, role: MessageRole, content: str
    ) -> ConversationMessage:
        message = self.conversation_store.append_message(
            context, conversation_id, role=role, content=content
        )
        if self.audit is not None:
            self.audit.record(
                AuditAction.CONVERSATION_MESSAGE_SENT,
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                target_type="conversation",
                target_id=message.conversation_id,
                detail={
                    "conversation_id": message.conversation_id,
                    "message_id": message.message_id,
                    "role": message.role.value,
                    "stub": False,
                },
            )
        return message

    def _load_message(
        self, context: UserContext, conversation_id: str, message_id: str | None
    ) -> ConversationMessage:
        if not message_id:
            raise ConversationExecutionError("幂等行缺少消息指针，无法重建响应", http_status=409)
        try:
            return self.conversation_store.get_message(context, conversation_id, message_id)
        except Exception as exc:  # noqa: BLE001 - 反查失败一律按确定结果码返回，不泄露细节
            raise ConversationExecutionError("无法重建首次响应", http_status=409) from exc

    def _remember(
        self,
        context: UserContext,
        conversation_id: str,
        idempotency_key: str,
        *,
        outcome: str,
        http_status: int,
        message_id: str | None,
        run_id: str | None,
        approval_id: str | None,
    ) -> None:
        if self.idempotency is None:
            return
        record = ExecutionIdempotencyRecord(
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            outcome=outcome,
            http_status=http_status,
            message_id=message_id,
            run_id=run_id,
            approval_id=approval_id,
            created_at=self._now(),
        )
        # 并发重放由 `ON CONFLICT DO NOTHING` 收敛为首次行；此处不覆盖既有结果。
        self.idempotency.insert(record)


def _plan_steps(plan: AgentPlan) -> list[dict[str, Any]]:
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "tool": step.tool,
            "requires_approval": step.requires_approval,
        }
        for step in plan.steps
    ]


def _message_view(message: ConversationMessage, *, stub: bool) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "role": message.role.value,
        "content": message.content,
        "stub": stub,
        "tool_name": message.tool_name,
        "tool_call_id": message.tool_call_id,
        "created_at": message.created_at,
    }


def _new_step_id() -> str:
    from uuid import uuid4

    return f"step-{uuid4().hex[:12]}"
