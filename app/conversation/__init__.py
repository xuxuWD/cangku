"""对话层（会话 / 消息）。

口径见 `docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md`。
P1 使用确定性桩回复，不接真实模型、不执行任何工具（D7）。
"""

from .models import (
    CONVERSING_ROLES,
    VIEW_ANY_ROLES,
    Conversation,
    ConversationError,
    ConversationMessage,
    ConversationNotFound,
    ConversationStateConflict,
    ConversationStatus,
    InvalidConversation,
    MessageRole,
    can_view_any,
    ensure_can_converse,
    ensure_can_modify,
    ensure_can_view,
)
from .service import STUB_REPLY_TEXT, ConversationService, build_stub_reply
from .store import (
    ConversationStore,
    InMemoryConversationStore,
    PostgresConversationStore,
)

__all__ = [
    "CONVERSING_ROLES",
    "VIEW_ANY_ROLES",
    "Conversation",
    "ConversationError",
    "ConversationMessage",
    "ConversationNotFound",
    "ConversationService",
    "ConversationStateConflict",
    "ConversationStatus",
    "ConversationStore",
    "InMemoryConversationStore",
    "InvalidConversation",
    "MessageRole",
    "PostgresConversationStore",
    "STUB_REPLY_TEXT",
    "build_stub_reply",
    "can_view_any",
    "ensure_can_converse",
    "ensure_can_modify",
    "ensure_can_view",
]
