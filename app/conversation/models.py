"""对话层（会话 / 消息）的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md` §7 / §8。

权限判定刻意放在本模块，供仓储层、服务层与接口层共用同一份实现（§8 约束 3）：
跨租户与「改他人会话」一律映射为「未找到」（404），不区分「权限不足」，避免探测存在性。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from ..domain import PolicyError, UserContext

MAX_TITLE_LENGTH = 120
MAX_MESSAGE_LENGTH = 8000
MAX_AGENT_KEY_LENGTH = 64

_AGENT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 可使用对话入口的岗位（§8：customer_admin 不参与对话）
CONVERSING_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})
# 可查看本租户内他人会话的岗位（§8：仅 CEO / 超级管理员）
VIEW_ANY_ROLES = frozenset({"ceo", "super_admin"})


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationMode(StrEnum):
    """每会话模式（P2c-4 §2.9）：只**收紧**、不放松。

    * `ask` = 只问答：拒绝一切真实执行（提问与缺键桩路径不受影响）；
    * `plan` = 先计划后执行：一律先落待批（等价 `approval_for_all`）；
    * `goal` / `craft` = 执行照常（按自治三档，不放松）。

    取值与迁移 `038` 的 CHECK 一字不差；**默认 `craft` = 改造前行为**。
    """

    ASK = "ask"
    PLAN = "plan"
    GOAL = "goal"
    CRAFT = "craft"


DEFAULT_MODE = ConversationMode.CRAFT
# 受控拒绝码 / 原因（`ask` 模式）：拒绝「真实执行」，不拒绝问答。
MODE_ASK_REJECTION_MESSAGE = "该会话为只问答模式，已拒绝执行"
MODE_ASK_REJECTION_REASON = "mode_ask"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ConversationError(ValueError):
    """对话操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidConversation(ConversationError):
    """输入不合法（标识、标题、消息内容）→ 422。"""


class ConversationStateConflict(ConversationError):
    """状态冲突（例如向已归档会话发消息）→ 409。"""


class ConversationNotFound(LookupError):
    """会话不存在、跨租户，或不属于当前操作者 → 404。

    刻意**不**继承 `ConversationError`/`PolicyError`：否则会被 403/422 分支截走，
    把「看不到（避免探测存在性）」误报成「无权限」或「参数错误」。
    """


def now() -> datetime:
    return datetime.now(UTC)


def new_conversation_id() -> str:
    return f"conv-{uuid4().hex[:12]}"


def new_message_id() -> str:
    return f"msg-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class Conversation:
    tenant_id: str
    conversation_id: str
    operator_id: str
    agent_key: str | None = None
    title: str = ""
    status: ConversationStatus = ConversationStatus.ACTIVE
    dsh_session_id: str | None = None
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)
    # P2c-4：每会话模式（默认 `craft` = 改造前行为）与软删标记（置位后一律按「不存在」处理）。
    mode: ConversationMode = DEFAULT_MODE
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class ConversationMessage:
    tenant_id: str
    message_id: str
    conversation_id: str
    role: MessageRole
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    created_at: datetime | None = field(default_factory=now)


# ------------------------------------------------------------ 访问权限（跨层共用）


def ensure_can_converse(context: UserContext) -> None:
    """是否允许使用对话入口；不满足抛 `PolicyError`（接口层 → 403）。"""
    if context.role not in CONVERSING_ROLES:
        raise PolicyError("当前岗位不能使用对话入口")


def can_view_any(context: UserContext) -> bool:
    """是否可查看本租户内他人会话（列表范围也据此收窄）。"""
    return context.role in VIEW_ANY_ROLES


def ensure_can_view(context: UserContext, conversation: Conversation) -> None:
    """读取会话：本人可读；CEO / 超级管理员可读本租户内他人会话；其余按「未找到」处理。"""
    if conversation.operator_id == context.user_id:
        return
    if can_view_any(context):
        return
    raise ConversationNotFound(conversation.conversation_id)


def ensure_can_modify(context: UserContext, conversation: Conversation) -> None:
    """写入会话（发消息 / 归档）：只允许本人；改他人会话一律「未找到」。"""
    if conversation.operator_id != context.user_id:
        raise ConversationNotFound(conversation.conversation_id)


# ------------------------------------------------------------ 输入归一化


def normalize_agent_key(value: str | None) -> str | None:
    """归一数字员工标识；空串 / None 表示「用默认员工」。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidConversation("数字员工标识必须是字符串")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _AGENT_KEY_PATTERN.match(normalized):
        raise InvalidConversation(
            "数字员工标识只能包含小写字母、数字、点、下划线与短横线，且必须以字母或数字开头（最长 64 个字符）"
        )
    return normalized


def normalize_title(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidConversation("会话标题必须是字符串")
    normalized = value.strip()
    if len(normalized) > MAX_TITLE_LENGTH:
        raise InvalidConversation(f"会话标题最长 {MAX_TITLE_LENGTH} 个字符")
    return normalized


def normalize_mode(value: str | ConversationMode) -> ConversationMode:
    """归一模式取值（受控枚举）；非法值 `422`（不猜测、不回落默认值）。"""
    if isinstance(value, ConversationMode):
        return value
    if not isinstance(value, str):
        raise InvalidConversation("会话模式必须是字符串")
    try:
        return ConversationMode(value.strip())
    except ValueError as exc:
        raise InvalidConversation("会话模式只能是 ask / plan / goal / craft 之一") from exc


def normalize_content(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidConversation("消息内容必须是字符串")
    if not value.strip():
        raise InvalidConversation("消息内容不能为空")
    if len(value) > MAX_MESSAGE_LENGTH:
        raise InvalidConversation(f"消息内容最长 {MAX_MESSAGE_LENGTH} 个字符")
    return value


def normalize_role(value: str | MessageRole) -> MessageRole:
    try:
        return MessageRole(value)
    except ValueError as exc:
        raise InvalidConversation("消息角色只能是 user / assistant / tool / system") from exc
