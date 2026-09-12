"""对话服务层：会话/消息业务逻辑 + 审计 + 与表单入口共用的权限判定。

🔴 §8 约束 3：对话入口不允许绕开既有 `ensure_can_create` / `ensure_can_approve`。
这里**调用**既有判定函数，不复制一份判定逻辑。自治等级只决定「是否需要人批」，
不决定「是否绕开权限判定」——`full_auto` 的员工仍不能做其操作者无权做的事。
"""

from __future__ import annotations

from ..audit.models import AuditAction
from ..domain import RiskLevel, UserContext, ensure_can_approve, ensure_can_create
from .models import Conversation, ConversationMessage, MessageRole
from .store import ConversationStore

# P1 用桩回复：不接真实模型、不执行任何工具（D7）。响应体显式标注 stub。
STUB_REPLY_TEXT = (
    "（P1 桩回复）已收到你的消息。当前阶段为对话层桩实现，"
    "未接入真实模型，也不会执行任何工具或文件/命令操作；数据模型、权限与审计都是真实的。"
)


def build_stub_reply(content: str) -> str:
    """确定性桩回复：同一输入永远得到同一输出，绝不伪装成真实模型输出。"""
    return f"{STUB_REPLY_TEXT}\n（你说了 {len(content)} 个字符。）"


class ConversationService:
    def __init__(self, store: ConversationStore, *, audit=None) -> None:
        self.store = store
        self.audit = audit

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

    def list_messages(self, context: UserContext, conversation_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ConversationMessage], int]:
        return self.store.list_messages(context, conversation_id, limit=limit, offset=offset)

    # ------------------------------------------------------------ 消息

    def send_message(self, context: UserContext, conversation_id: str, *, content: str) -> tuple[ConversationMessage, ConversationMessage]:
        """落库用户消息 → 生成确定性桩回复 → 落库助手消息；两条消息各自写审计。

        审计只记标识与角色，**不记消息正文**。
        """
        user_message = self.store.append_message(
            context, conversation_id, role=MessageRole.USER, content=content
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

    def _record(self, context: UserContext, action: AuditAction, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="conversation",
            target_id=target_id,
            detail=detail,
        )
