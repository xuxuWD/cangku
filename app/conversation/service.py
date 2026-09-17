"""对话服务层：会话/消息业务逻辑 + 审计 + 与表单入口共用的权限判定。

🔴 §8 约束 3：对话入口不允许绕开既有 `ensure_can_create` / `ensure_can_approve`。
这里**调用**既有判定函数，不复制一份判定逻辑。自治等级只决定「是否需要人批」，
不决定「是否绕开权限判定」——`full_auto` 的员工仍不能做其操作者无权做的事。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..audit.models import AuditAction
from ..domain import RiskLevel, UserContext, ensure_can_approve, ensure_can_create
from .models import (
    Conversation,
    ConversationMessage,
    ConversationMode,
    ConversationStateConflict,
    MessageRole,
    normalize_content,
    normalize_mode,
)
from .redaction import redact_message_content
from .store import (
    MAX_EXPORT_LIMIT,
    ConversationDeletion,
    ConversationExportPage,
    ConversationStore,
)

# P2c-4 §2.11：导出**条目上限**（会话数 + 消息数合计）与超限的受控原因（**不静默截断**）。
MAX_EXPORT_ITEMS = 50_000
EXPORT_LIMIT_REASON = "total_items_exceeded"

# P1 用桩回复：不接真实模型、不执行任何工具（D7）。响应体显式标注 stub。
STUB_REPLY_TEXT = (
    "（P1 桩回复）已收到你的消息。当前阶段为对话层桩实现，"
    "未接入真实模型，也不会执行任何工具或文件/命令操作；数据模型、权限与审计都是真实的。"
)


def build_stub_reply(content: str) -> str:
    """确定性桩回复：同一输入永远得到同一输出，绝不伪装成真实模型输出。"""
    return f"{STUB_REPLY_TEXT}\n（你说了 {len(content)} 个字符。）"


@dataclass(frozen=True)
class ExportResult:
    """一次导出的结果（页单位 = 会话；`truncated` 时 `limit_reason` 给出受控原因）。"""

    exported_at: datetime
    limit: int
    offset: int
    conversations: list[tuple[Conversation, list[ConversationMessage]]]
    total_conversations: int
    total_messages: int
    truncated: bool
    limit_reason: str | None


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        *,
        audit=None,
        # P2c-4 §2.11：物理删除需要跨仓储（幂等行 / 帧 / 流状态）按序清理；缺任一即 fail-closed。
        stream_store=None,
        idempotency_store=None,
        max_export_items: int = MAX_EXPORT_ITEMS,
    ) -> None:
        self.store = store
        self.audit = audit
        self.stream_store = stream_store
        self.idempotency_store = idempotency_store
        self.max_export_items = max(1, int(max_export_items))

    # ------------------------------------------------------------ 权限收敛（与表单入口共用同一函数）

    def ensure_can_create_task(self, context: UserContext, *, risk_level: RiskLevel, budget: float, autonomy_level: str | None = None) -> None:
        """对话入口创建任务类动作的前置判定：与表单入口共用 `domain.ensure_can_create`。

        `autonomy_level` 只用于说明「是否需要人批」，**刻意不参与**这里的权限判定。
        """
        ensure_can_create(context, risk_level, budget)

    def ensure_can_approve_request(self, context: UserContext) -> None:
        """对话入口审批类动作的前置判定：与表单入口共用 `domain.ensure_can_approve`。"""
        ensure_can_approve(context)

    # ------------------------------------------------------------ 会话

    def create_conversation(self, context: UserContext, *, agent_key: str | None = None, title: str = "") -> Conversation:
        conversation = self.store.create_conversation(context, agent_key=agent_key, title=title)
        self._record(
            context,
            AuditAction.CONVERSATION_CREATED,
            conversation.conversation_id,
            {
                "conversation_id": conversation.conversation_id,
                "agent_key": conversation.agent_key or "",
                "status": conversation.status.value,
            },
        )
        return conversation

    def get_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        return self.store.get_conversation(context, conversation_id)

    def list_conversations(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Conversation], int]:
        return self.store.list_conversations(context, status=status, limit=limit, offset=offset)

    def archive_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        conversation = self.store.archive_conversation(context, conversation_id)
        self._record(
            context,
            AuditAction.CONVERSATION_ARCHIVED,
            conversation.conversation_id,
            {"conversation_id": conversation.conversation_id, "status": conversation.status.value},
        )
        return conversation

    def set_conversation_mode(
        self, context: UserContext, conversation_id: str, mode: str | ConversationMode
    ) -> Conversation:
        """改模式（P2c-4 §2.9）：仅本人；他人 / 跨租户 `404`；归档 `409`；非法值 `422`。

        **设为同一值 = 无副作用**（不写审计、不写 `updated_at`）；变更写审计
        `conversation.mode.changed`（`from_mode` / `to_mode` 均为受控枚举，**不落自由文本**）。
        """
        clean_mode = normalize_mode(mode)
        conversation, previous = self.store.set_mode(context, conversation_id, clean_mode)
        if previous is not None:
            self._record(
                context,
                AuditAction.CONVERSATION_MODE_CHANGED,
                conversation.conversation_id,
                {
                    "conversation_id": conversation.conversation_id,
                    "from_mode": previous.value,
                    "to_mode": conversation.mode.value,
                },
            )
        return conversation

    def delete_conversation(self, context: UserContext, conversation_id: str) -> ConversationDeletion:
        """**物理删除**本人会话的内容行（P2c-4 §2.11）：同步、幂等、审计（受控计数）。

        固定顺序（见契约「物理删除」）：**幂等行 → 帧 → 流状态 → 消息 + 会话行软删**；
        幂等行同时引用消息行与会话行，必须最先删（否则外键拒绝删消息）。
        复删**幂等**：已软删的会话不再删任何东西、**不重复写审计**，各计数返回 0。
        未装配流 / 幂等仓储时 **fail-closed 拒绝**（不得只删一半）。
        """
        conversation = self.store.get_conversation_including_deleted(context, conversation_id)
        if conversation.deleted_at is not None:
            return ConversationDeletion(
                conversation_id=conversation.conversation_id,
                deleted=True,
                message_count=0,
                frame_count=0,
                stream_state_count=0,
                idempotency_count=0,
                already_deleted=True,
            )
        if self.stream_store is None or self.idempotency_store is None:
            raise ConversationStateConflict("删除链路未装配完整（缺少流 / 幂等仓储），已拒绝执行")
        idempotency_count = int(
            self.idempotency_store.delete_for_conversation(context.tenant_id, conversation.conversation_id)
        )
        frame_count, stream_state_count = self.stream_store.delete_for_conversation(
            context.tenant_id, conversation.conversation_id
        )
        message_count = int(self.store.delete_conversation_content(context, conversation_id))
        self._record(
            context,
            AuditAction.CONVERSATION_DELETED,
            conversation.conversation_id,
            {
                "conversation_id": conversation.conversation_id,
                "message_count": message_count,
                "frame_count": int(frame_count),
                "stream_state_count": int(stream_state_count),
                "idempotency_count": idempotency_count,
            },
        )
        return ConversationDeletion(
            conversation_id=conversation.conversation_id,
            deleted=True,
            message_count=message_count,
            frame_count=int(frame_count),
            stream_state_count=int(stream_state_count),
            idempotency_count=idempotency_count,
        )

    def export_mine(self, context: UserContext, *, limit: int = MAX_EXPORT_LIMIT, offset: int = 0) -> ExportResult:
        """导出**本人**全部未软删会话（含归档）与消息（P2c-4 §2.11）：分页 + **条目上限如实告知**。

        页单位 = 会话（`limit` ≤ 500，`created_at` 降序）；条目 = 会话数 + 消息数。
        超上限**不静默截断**：`truncated=true` + `limit_reason="total_items_exceeded"`
        （本页只装入上限内的**整会话**；剩余由下一页 `offset` 继续）。导出动作写审计（受控计数）。
        """
        page: ConversationExportPage = self.store.export_mine(context, limit=limit, offset=offset)
        cap = self.max_export_items
        packed: list[tuple[Conversation, list[ConversationMessage]]] = []
        used = 0
        page_truncated = False
        for conversation, messages in page.conversations:
            if used + 1 + len(messages) > cap:
                page_truncated = True
                break
            packed.append((conversation, messages))
            used += 1 + len(messages)
        truncated = page_truncated or (page.total_conversations + page.total_messages) > cap
        result = ExportResult(
            exported_at=datetime.now(UTC),
            limit=int(limit),
            offset=int(offset),
            conversations=packed,
            total_conversations=page.total_conversations,
            total_messages=page.total_messages,
            truncated=truncated,
            limit_reason=EXPORT_LIMIT_REASON if truncated else None,
        )
        self._record(
            context,
            AuditAction.CONVERSATION_EXPORTED,
            context.user_id,
            {
                "conversation_count": len(packed),
                "message_count": sum(len(messages) for _item, messages in packed),
                "truncated": truncated,
            },
            target_type="conversation_export",
        )
        return result

    def list_messages(self, context: UserContext, conversation_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ConversationMessage], int]:
        return self.store.list_messages(context, conversation_id, limit=limit, offset=offset)

    # ------------------------------------------------------------ 消息

    def send_message(self, context: UserContext, conversation_id: str, *, content: str) -> tuple[ConversationMessage, ConversationMessage]:
        """落库用户消息 → 生成确定性桩回复 → 落库助手消息；两条消息各自写审计。

        审计只记标识与角色，**不记消息正文**。
        §8 U23：用户消息 `content` 落库前经 `redact_message_content` 收敛为**脱敏摘要**，
        自由文本原文**不落库**（助手桩回复不受影响）。
        ⚠️ 空 / 纯空白 / 超长的校验必须落在**原文**上（脱敏摘要恒非空，若只校验摘要会放过空消息）。
        """
        normalize_content(content)
        user_message = self.store.append_message(
            context,
            conversation_id,
            role=MessageRole.USER,
            content=redact_message_content(content),
        )
        self._record(
            context,
            AuditAction.CONVERSATION_MESSAGE_SENT,
            user_message.conversation_id,
            {
                "conversation_id": user_message.conversation_id,
                "message_id": user_message.message_id,
                "role": user_message.role.value,
                "stub": False,
            },
        )
        reply = self.store.append_message(
            context,
            conversation_id,
            role=MessageRole.ASSISTANT,
            content=build_stub_reply(content),
        )
        self._record(
            context,
            AuditAction.CONVERSATION_MESSAGE_SENT,
            reply.conversation_id,
            {
                "conversation_id": reply.conversation_id,
                "message_id": reply.message_id,
                "role": reply.role.value,
                "stub": True,
            },
        )
        return user_message, reply

    # ------------------------------------------------------------ 内部

    def _record(
        self,
        context: UserContext,
        action: AuditAction,
        target_id: str,
        detail: dict[str, object],
        *,
        target_type: str = "conversation",
    ) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
