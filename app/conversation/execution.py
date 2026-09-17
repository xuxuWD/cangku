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
from ..runtime.contracts import AgentPlan, RuntimeEventType
from ..tool_execution.args_digest import args_digest as _args_digest
from ..tool_execution.errors import ToolExecutionConfigError, ToolExecutionError
from ..tool_execution.file_ops import CHANGE_KINDS, bounded_changes
from ..tool_execution.params import path_param_names
from ..tool_execution.service import ToolExecutionRequest
from ..workforce.models import APPROVAL_FOR_ALL, needs_approval
from .idempotency import ExecutionIdempotencyRecord
from .models import (
    MODE_ASK_REJECTION_MESSAGE,
    MODE_ASK_REJECTION_REASON,
    ConversationMessage,
    ConversationMode,
    ConversationNotFound,
    InvalidConversation,
    MessageRole,
    normalize_content,
)
from .redaction import redact_message_content
from .stream import MESSAGE_ASSISTANT_KIND, MESSAGE_USER_KIND

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
        stream_writer=None,
        # P2c-3：变更通道上限（`0` = 关闭 ⇒ 帧里不出现 `file_changes`，零破坏）。
        file_changes_max: int = 0,
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
        # P2b §2.2：流写入网关（**可选注入**，缺省 `None` ⇒ 行为与改造前完全一致）；
        # 且只有 `handle_message(..., stream=True)`（`messages:stream` 端点）才真正写帧。
        self.stream_writer = stream_writer
        # P2c-3：变更通道上限（帧 payload 的**契约边界**再次截断；`0` = 关闭）。
        self.file_changes_max = int(file_changes_max)

    # ------------------------------------------------------------------ 公开入口

    def handle_message(
        self,
        context: UserContext,
        conversation_id: str,
        *,
        content: str,
        idempotency_key: str | None = None,
        stream: bool = False,
    ) -> MessageExecutionResult:
        """缺键（或未启用真实执行）⇒ 既有 `stub=true` 通路；带键 ⇒ 真实执行 + 幂等。

        `stream=True`（**仅** `messages:stream` 端点传入）⇒ 执行过程写流帧（P2b §2.4）；
        缺省 `False` ⇒ **旧 `POST /messages` 零帧**（零破坏哨兵），且 `stream_writer` 未注入时同样零帧。
        """
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
        return self._execute(
            context, conversation_id, content=content, idempotency_key=idempotency_key, stream=stream
        )

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
        stream: bool = False,
    ) -> MessageExecutionResult:
        normalize_content(content)
        # 归属 / 跨租户 / 归档：仓储层与模型层统一判定（404 / 409）。
        conversation = self.conversation_store.get_conversation(context, conversation_id)

        existing = self.idempotency.get(
            context.tenant_id, context.user_id, conversation_id, idempotency_key
        )
        if existing is not None:
            return self._rebuild(context, conversation_id, existing)

        # P2c-4 §2.9：`ask` = 只问答 ⇒ **拒绝一切真实执行**（发起处）——fail-closed：
        # 不创建承载任务 / 运行 / 消息；按 §4.1.3 四态口径落 `rejected` 幂等行（重放同码同文案）。
        if conversation.mode is ConversationMode.ASK:
            self._record_mode_rejection(context, conversation)
            self._remember(
                context, conversation_id, idempotency_key,
                outcome="rejected", http_status=409,
                message_id=None, run_id=None, approval_id=None,
            )
            raise ConversationExecutionError(MODE_ASK_REJECTION_MESSAGE, http_status=409)

        # agent_key 校验收紧（执行入口）：存在且启用，否则 422；同时取回治理两字段。
        governance = self._governance(context, conversation)
        autonomy_level, risk_threshold = governance
        # P2c-4 §2.9：`plan` = 先计划后执行 ⇒ **强制待批**（合成取更严）——等价 `approval_for_all`
        # 并经**唯一判定入口** `needs_approval` 生效（不另造判定；`critical` 仍仅 CEO / 超管可发起）。
        if conversation.mode is ConversationMode.PLAN:
            autonomy_level = APPROVAL_FOR_ALL

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
        # P2b §2.5：过程事件帧（payload 只含摘要；参数只落 args_digest，**不落参数值**）。
        params_digest = _params_digest(spec, invocation.params)
        self._write_frame(
            stream, context, conversation_id, run_id,
            kind=RuntimeEventType.PLAN_CREATED.value,
            payload={
                "step_id": step_id,
                "step_kind": kind,
                "tool_key": spec.key,
                "requires_approval": requires_approval,
                "plan_digest": plan_digest(plan),
            },
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
        self._write_frame(
            stream, context, conversation_id, run_id,
            kind=RuntimeEventType.TOOL_CALL.value,
            payload={"step_id": step_id, "tool_key": spec.key, "args_digest": params_digest},
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
                stream=stream,
            )

        if result is None:  # 允许打桩返回 None（无执行结局）——不产生结果码，交由调用方兜底
            self._write_frame(
                stream, context, conversation_id, run_id,
                kind=RuntimeEventType.RUN_FAILED.value,
                payload={"status": "failed", "reason": "no_result"},
                is_terminal=True,
            )
            raise ConversationExecutionError("执行未返回结果", http_status=502)

        if result.outcome == "pending_approval":
            # §3.7 Y2：⑥ 落库成功（该动作进入等待审批）后，把承载任务由 `queued` 置 `pending_approval`。
            self._mark_task_pending_approval(context, task.id)
            # P2b §2.4：`202` 分支**不写终态帧**（流保持 `streaming`，待批展示由既有审批聚合承担）。
            self._write_frame(
                stream, context, conversation_id, run_id,
                kind=RuntimeEventType.APPROVAL_REQUESTED.value,
                payload={
                    "step_id": step_id,
                    "tool_key": spec.key,
                    "approval_id": result.approval_id or step_id,
                },
            )
            try:
                user_message = self._append_message(
                    context,
                    conversation_id,
                    MessageRole.USER,
                    redact_message_content(content),
                    tool_name=invocation.tool_key,
                )
                self._write_message_frame(stream, context, conversation_id, run_id, user_message)
                reply = self._append_message(
                    context,
                    conversation_id,
                    MessageRole.ASSISTANT,
                    "该操作需要人工审批后方可执行。",
                )
                self._write_message_frame(stream, context, conversation_id, run_id, reply)
            except Exception:  # noqa: BLE001 - 追加被拒（如归档会话）：流以终态收口，异常语义不变
                self._write_rejected_frame(stream, context, conversation_id, run_id)
                raise
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
        self._write_frame(
            stream, context, conversation_id, run_id,
            kind=RuntimeEventType.TOOL_RESULT.value,
            payload=_tool_result_summary(
                spec,
                result,
                step_id=step_id,
                params_digest=params_digest,
                file_changes_max=self.file_changes_max,
            ),
        )
        try:
            user_message = self._append_message(
                context,
                conversation_id,
                MessageRole.USER,
                redact_message_content(content),
                tool_name=invocation.tool_key,
            )
            self._write_message_frame(stream, context, conversation_id, run_id, user_message)
            reply = self._append_message(
                context, conversation_id, MessageRole.ASSISTANT, "工具已执行完成。"
            )
            self._write_message_frame(stream, context, conversation_id, run_id, reply)
            # 水位：助手消息已落消息表（客户端据此判断「结果已可经消息表读取」）。
            self._watermark(stream, context, conversation_id, run_id, reply.message_id)
        except Exception:  # noqa: BLE001 - 追加被拒（如归档会话）：流以终态收口，异常语义不变
            self._write_rejected_frame(stream, context, conversation_id, run_id)
            raise
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
        self._write_frame(
            stream, context, conversation_id, run_id,
            kind=RuntimeEventType.RUN_COMPLETED.value,
            payload={"status": "completed", "http_status": 201},
            is_terminal=True,
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
        stream: bool = False,
    ) -> MessageExecutionResult:
        """按受控异常携带的 HTTP 语义落幂等行并抛出；**`503` 不写本表且回滚本次已创建对象**（§4.1.3）。

        §4.1.3 / §4.1.6-5：`⑥` 落库失败（`503`）与幂等行、承载任务、运行属**同一次请求的产物**——
        `⑥` 失败即整体回滚，故**不存在"首次 `503`"的行**，重放该键会**重新走一遍闸门**（此时未产生
        任何消息 / 任务 / 运行 / 副作用，不违反幂等）。

        P2b §2.2-6：失败同样写**终态帧**（`run.failed`，`is_terminal=True`）——流是视图，
        写入时机与既有判定 / 错误语义**无关**（含 `503` 的同请求回滚：帧不参与回滚，仅关闭流）。
        """
        # 终态帧先落（若已写过程帧则关闭流；不写帧的场景只有「run 尚未创建」这一种，此处 run 恒已创建）。
        self._write_frame(
            stream, context, conversation_id, run_id,
            kind=RuntimeEventType.RUN_FAILED.value,
            payload={"status": "failed", "http_status": exc.http_status},
            is_terminal=True,
        )
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

    # ------------------------------------------------------------------ P2c-4 模式判定（推进处）

    def ensure_resume_allowed(self, context: UserContext, run_id: str) -> None:
        """**推进处**（审批决议后重跑）的模式判定：会话为 `ask` 时一律拒绝（fail-closed）。

        运行经**幂等行**反查会话（`find_by_run`，与 P2c-2 的推进帧同源）：
          * 无幂等行 / 未知会话（非对话触发的运行、或会话内容已物理删除）⇒ **不拦截**（已知边界，见契约）；
          * 查得会话且模式为 `ask` ⇒ 写审计 `conversation.execution.rejected` 并抛 `409`
            （**决议整体拒绝**：调用方须在落决议前调用本方法，宁可拒绝决议也不产生悬挂授权位）；
          * **校验本身失败**（读幂等 / 读会话异常）⇒ `503` fail-closed（不猜测、不放行）。
        """
        if self.idempotency is None:
            return
        try:
            record = self.idempotency.find_by_run(context.tenant_id, run_id)
        except Exception as exc:  # noqa: BLE001 - 校验不可用一律 fail-closed（不放行）
            raise ConversationExecutionError("审批前校验暂时不可用，请稍后重试", http_status=503) from exc
        conversation_id = getattr(record, "conversation_id", None)
        if not conversation_id:
            return
        try:
            conversation = self.conversation_store.get_conversation(context, conversation_id)
        except ConversationNotFound:
            return
        except Exception as exc:  # noqa: BLE001 - 同上：校验失败不放行
            raise ConversationExecutionError("审批前校验暂时不可用，请稍后重试", http_status=503) from exc
        if conversation.mode is not ConversationMode.ASK:
            return
        self._record_mode_rejection(context, conversation)
        raise ConversationExecutionError(MODE_ASK_REJECTION_MESSAGE, http_status=409)

    def _record_mode_rejection(self, context: UserContext, conversation) -> None:
        """`ask` 模式拒绝执行的审计（受控键：会话号 / 模式 / 受控原因，**不落正文**）。"""
        if self.audit is None:
            return
        self.audit.record(
            AuditAction.CONVERSATION_EXECUTION_REJECTED,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="conversation",
            target_id=conversation.conversation_id,
            detail={
                "conversation_id": conversation.conversation_id,
                "mode": ConversationMode.ASK.value,
                "reason": MODE_ASK_REJECTION_REASON,
            },
        )

    # ------------------------------------------------------------------ P2b 流帧写入（视图，失败只降级）

    def _write_frame(
        self,
        enabled: bool,
        context: UserContext,
        conversation_id: str,
        run_id: str | None,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        is_terminal: bool = False,
    ) -> None:
        """写一帧（仅 `messages:stream` 路径 + 已注入写入网关时）。

        **先落库、不推送**由写入网关与 SSE 读端点分别承担（读端只从库里读增量）。
        `enabled=False`（旧 `POST /messages`）或未注入网关 ⇒ **零写入**（零破坏哨兵）。
        """
        if not enabled or self.stream_writer is None or not run_id:
            return
        try:
            self.stream_writer.write(
                context.tenant_id,
                conversation_id,
                run_id,
                kind=kind,
                payload=payload or {},
                is_terminal=is_terminal,
            )
        except Exception:  # noqa: BLE001 - 流写入失败**绝不**阻断或改变执行结果
            _logger.error("流帧写入失败（已降级，不影响执行）run_id=%s kind=%s", run_id, kind)

    def _write_message_frame(
        self,
        enabled: bool,
        context: UserContext,
        conversation_id: str,
        run_id: str,
        message: ConversationMessage,
    ) -> None:
        """消息落定帧：**只落 `message_id` 与状态标记，不落正文**（正文在消息表，§2.5）。"""
        kind = MESSAGE_USER_KIND if message.role is MessageRole.USER else MESSAGE_ASSISTANT_KIND
        self._write_frame(
            enabled, context, conversation_id, run_id,
            kind=kind,
            payload={"message_id": message.message_id, "stub": False},
        )

    def _watermark(
        self,
        enabled: bool,
        context: UserContext,
        conversation_id: str,
        run_id: str,
        message_id: str,
    ) -> None:
        if not enabled or self.stream_writer is None:
            return
        try:
            self.stream_writer.watermark(context.tenant_id, conversation_id, run_id, message_id)
        except Exception:  # noqa: BLE001 - 水位失败不影响结果
            _logger.error("流水位回填失败（已降级）run_id=%s", run_id)

    def _write_rejected_frame(
        self,
        enabled: bool,
        context: UserContext,
        conversation_id: str,
        run_id: str,
    ) -> None:
        """消息追加被拒（如向归档会话发消息 `409`）⇒ **终态帧收口**，避免留下悬挂流。

        流是视图：本帧只影响读端何时关流，**不改变**既有异常语义（异常原样向上抛）。
        """
        self._write_frame(
            enabled, context, conversation_id, run_id,
            kind=RuntimeEventType.RUN_FAILED.value,
            payload={"status": "failed", "reason": "message_rejected"},
            is_terminal=True,
        )

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
        self,
        context: UserContext,
        conversation_id: str,
        role: MessageRole,
        content: str,
        *,
        tool_name: str | None = None,
    ) -> ConversationMessage:
        message = self.conversation_store.append_message(
            context, conversation_id, role=role, content=content, tool_name=tool_name
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


def _params_digest(spec, params: Mapping[str, Any]) -> str:
    """工具参数的 `args_digest`（§4.1.4，**与 `027` 落库口径一致**：含 `path_params` 归一）。

    **只落摘要值**（`"sha256:" + hex`），不落任何参数值。
    """
    return _args_digest(params, path_params=path_param_names(spec))


def summary_digest(summary: Mapping[str, Any]) -> str:
    """工具结果摘要的 sha256（可追溯指纹；**只对摘要定型**，不含 stdout / 文件正文）。"""
    encoded = json.dumps(dict(summary), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tool_result_summary(
    spec, result, *, step_id: str, params_digest: str, file_changes_max: int = 0
) -> dict[str, Any]:
    """`tool.result` 帧的 payload：摘要 + `args_digest` + `sha256` **＋ 有界摘录**（P2c-2 §2.6）。

    **仍不落**：stdout 全文、文件正文、宿主真实路径、凭据 / 认证头 / Cookie；
    有界摘录**只增** `output_excerpt` / `output_truncated` / `output_bytes` / `output_sha256`
    与 `file_changes` / `file_changes_truncated`（P2c-3；统一在写帧网关过 `redact_payload`；
    **不进审计、不进消息表**）。
    """
    summary = dict(result.summary or {})
    payload: dict[str, Any] = {
        "step_id": step_id,
        "tool_key": spec.key,
        "status": str(summary.get("status") or "ok"),
        "summary": summary,
        "args_digest": params_digest,
        "sha256": summary_digest(summary),
    }
    payload.update(
        bounded_output_fields(
            getattr(result, "output", None), file_changes_max=file_changes_max
        )
    )
    return payload


def bounded_output_fields(output: object, *, file_changes_max: int = 0) -> dict[str, Any]:
    """把执行结果的**有界输出**并入 payload（**白名单键**；缺省不出现 ⇒ 既有帧逐字节不变）。

    P2c-3 增：`file_changes`（逐条白名单只读五键）与 `file_changes_truncated`（截断告知）。
    **契约边界**：这里再次按 `WORKBENCH_FILE_CHANGES_MAX` 截断——即使上游（执行器 / 打桩）给出更多，
    帧里也**绝不会**超过上限；`0` = 关闭变更通道（不产出、不出现截断标记）。
    """
    if not isinstance(output, Mapping):
        return {}
    fields: dict[str, Any] = {}
    excerpt = output.get("output_excerpt")
    if isinstance(excerpt, str) and excerpt:
        fields["output_excerpt"] = excerpt
    if "output_truncated" in output:
        fields["output_truncated"] = bool(output.get("output_truncated"))
    bytes_read = output.get("output_bytes")
    if isinstance(bytes_read, int) and not isinstance(bytes_read, bool):
        fields["output_bytes"] = int(bytes_read)
    sha = output.get("output_sha256")
    if isinstance(sha, str) and sha:
        fields["output_sha256"] = sha
    raw_changes = output.get("file_changes")
    if isinstance(raw_changes, (list, tuple)) and raw_changes and int(file_changes_max) > 0:
        changes = [item for item in (_change_view(item) for item in raw_changes) if item]
        kept, truncated = bounded_changes(changes, file_changes_max)
        if kept:
            fields["file_changes"] = list(kept)
        if truncated or output.get("file_changes_truncated") is True:
            fields["file_changes_truncated"] = True
    return fields


def _change_view(item: object) -> dict[str, Any] | None:
    """单条变更的**白名单投影**（`virtual_path` / `change_kind` / `bytes` / `sha256` / `diff_excerpt`）。

    形态不符（缺虚拟路径 / 类型非法 / 字节数非法 / 摘要非法）⇒ 丢弃该条（不猜测、不补默认值）。
    """
    if not isinstance(item, Mapping):
        return None
    virtual_path = item.get("virtual_path")
    change_kind = item.get("change_kind")
    size = item.get("bytes")
    sha256 = item.get("sha256")
    if not isinstance(virtual_path, str) or not virtual_path:
        return None
    if change_kind not in CHANGE_KINDS:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    if not isinstance(sha256, str) or not sha256.startswith("sha256:"):
        return None
    view: dict[str, Any] = {
        "virtual_path": virtual_path,
        "change_kind": change_kind,
        "bytes": int(size),
        "sha256": sha256,
    }
    excerpt = item.get("diff_excerpt")
    if isinstance(excerpt, str) and excerpt:
        view["diff_excerpt"] = excerpt
    return view


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
