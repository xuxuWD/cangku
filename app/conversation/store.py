"""对话仓储：内存实现 + PostgreSQL 实现。

权限在**仓储层**同样强制（复用 `models` 的访问判定），避免调用方绕过接口层直接读写。
所有查询严格带 `tenant_id`，不依赖任何调用方传入的租户条件。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from typing import Protocol

from ..domain import UserContext
from .models import (
    Conversation,
    ConversationMessage,
    ConversationMode,
    ConversationNotFound,
    ConversationStateConflict,
    ConversationStatus,
    MessageRole,
    can_view_any,
    ensure_can_converse,
    ensure_can_modify,
    ensure_can_view,
    new_conversation_id,
    new_message_id,
    normalize_agent_key,
    normalize_content,
    normalize_mode,
    normalize_role,
    normalize_title,
    now,
)

MAX_LIMIT = 200
# P2c-4 §2.11：导出分页（页单位 = 会话）与**条目上限**（会话数 + 消息数，超出**如实告知**）。
MAX_EXPORT_LIMIT = 500


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _clamp_export(limit: int) -> int:
    return max(1, min(int(limit), MAX_EXPORT_LIMIT))


def _sort_key(created_at: datetime | None, identity: str) -> tuple[datetime, str]:
    return (created_at or datetime.min, identity)


@dataclass(frozen=True)
class ConversationDeletion:
    """一次物理删除的计数（复删时全为 0；`already_deleted` 标记是否已是删除后状态）。"""

    conversation_id: str
    deleted: bool
    message_count: int
    frame_count: int
    stream_state_count: int
    idempotency_count: int
    already_deleted: bool = False


@dataclass(frozen=True)
class ConversationExportPage:
    """导出一页（页单位 = 会话，按 `created_at` 降序；每项含其全部消息与消息总数）。"""

    conversations: list[tuple[Conversation, list[ConversationMessage]]]
    total_conversations: int
    total_messages: int


class ConversationStore(Protocol):
    """会话与消息读写；所有方法都严格限定本租户并做归属校验。"""

    def create_conversation(self, context: UserContext, *, agent_key: str | None = None, title: str = "") -> Conversation: ...

    def get_conversation(self, context: UserContext, conversation_id: str) -> Conversation: ...

    def get_conversation_including_deleted(self, context: UserContext, conversation_id: str) -> Conversation: ...

    def list_conversations(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Conversation], int]: ...

    def archive_conversation(self, context: UserContext, conversation_id: str) -> Conversation: ...

    def set_mode(self, context: UserContext, conversation_id: str, mode: str | ConversationMode) -> tuple[Conversation, ConversationMode | None]: ...

    def delete_conversation_content(self, context: UserContext, conversation_id: str) -> int: ...

    def export_mine(self, context: UserContext, *, limit: int = 500, offset: int = 0) -> ConversationExportPage: ...

    def append_message(self, context: UserContext, conversation_id: str, *, role: str | MessageRole, content: str, tool_name: str | None = None, tool_call_id: str | None = None) -> ConversationMessage: ...

    def list_messages(self, context: UserContext, conversation_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ConversationMessage], int]: ...

    def get_message(self, context: UserContext, conversation_id: str, message_id: str) -> ConversationMessage: ...


class InMemoryConversationStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._conversations: dict[tuple[str, str], Conversation] = {}
        self._messages: dict[tuple[str, str], list[ConversationMessage]] = {}
        self._lock = RLock()

    # ------------------------------------------------------------ 会话

    def create_conversation(self, context: UserContext, *, agent_key: str | None = None, title: str = "") -> Conversation:
        ensure_can_converse(context)
        conversation = Conversation(
            tenant_id=context.tenant_id,
            conversation_id=new_conversation_id(),
            operator_id=context.user_id,
            agent_key=normalize_agent_key(agent_key),
            title=normalize_title(title),
        )
        with self._lock:
            self._conversations[(context.tenant_id, conversation.conversation_id)] = conversation
        return conversation

    def get_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        ensure_can_converse(context)
        with self._lock:
            conversation = self._conversations.get((context.tenant_id, str(conversation_id)))
        # 软删行按「不存在」处理（与不存在不可区分）。
        if conversation is None or conversation.deleted_at is not None:
            raise ConversationNotFound(conversation_id)
        ensure_can_view(context, conversation)
        return conversation

    def get_conversation_including_deleted(self, context: UserContext, conversation_id: str) -> Conversation:
        """（删除路径专用）含软删行的读取：仍做本人校验（他人 / 跨租户一律「未找到」）。"""
        ensure_can_converse(context)
        with self._lock:
            conversation = self._conversations.get((context.tenant_id, str(conversation_id)))
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        ensure_can_modify(context, conversation)
        return conversation

    def list_conversations(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Conversation], int]:
        ensure_can_converse(context)
        wanted = ConversationStatus(status) if status is not None else None
        with self._lock:
            matched = [
                conversation
                for (tenant_id, _key), conversation in self._conversations.items()
                if tenant_id == context.tenant_id
                and conversation.deleted_at is None
                and (can_view_any(context) or conversation.operator_id == context.user_id)
                and (wanted is None or conversation.status == wanted)
            ]
        matched.sort(key=lambda item: _sort_key(item.created_at, item.conversation_id), reverse=True)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def archive_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        ensure_can_converse(context)
        with self._lock:
            existing = self._conversations.get((context.tenant_id, str(conversation_id)))
            if existing is None or existing.deleted_at is not None:
                raise ConversationNotFound(conversation_id)
            ensure_can_modify(context, existing)
            updated = replace(existing, status=ConversationStatus.ARCHIVED, updated_at=now())
            self._conversations[(context.tenant_id, existing.conversation_id)] = updated
            return updated

    def set_mode(self, context: UserContext, conversation_id: str, mode: str | ConversationMode) -> tuple[Conversation, ConversationMode | None]:
        """改模式：**仅本人**（他人 / 跨租户 `404`）；归档会话 `409`（沿用「归档不可再写」口径）。

        返回 `(更新后会话, 变更前模式)`；**同值无副作用**时第二项为 `None`（服务层据此不写审计）。
        """
        clean_mode = normalize_mode(mode)
        with self._lock:
            existing = self._conversations.get((context.tenant_id, str(conversation_id)))
            if existing is None or existing.deleted_at is not None:
                raise ConversationNotFound(conversation_id)
            ensure_can_modify(context, existing)
            if existing.status != ConversationStatus.ACTIVE:
                raise ConversationStateConflict("会话已归档，不能再修改模式")
            if existing.mode == clean_mode:
                return existing, None
            updated = replace(existing, mode=clean_mode, updated_at=now())
            self._conversations[(context.tenant_id, existing.conversation_id)] = updated
            return updated, existing.mode

    def delete_conversation_content(self, context: UserContext, conversation_id: str) -> int:
        """真删消息行 + 会话行软删（`deleted_at` + `title=''`）——**同一临界区（等价单事务）**。

        幂等行 / 帧 / 流状态由服务层按固定顺序先行删除（见契约「物理删除」）；
        本方法只负责「消息 + 会话行」这一对（外键要求幂等行已先删）。
        """
        with self._lock:
            existing = self._conversations.get((context.tenant_id, str(conversation_id)))
            if existing is None:
                raise ConversationNotFound(conversation_id)
            ensure_can_modify(context, existing)
            messages = self._messages.pop((context.tenant_id, existing.conversation_id), [])
            self._conversations[(context.tenant_id, existing.conversation_id)] = replace(
                existing, title="", deleted_at=now(), updated_at=now()
            )
            return len(messages)

    def export_mine(self, context: UserContext, *, limit: int = MAX_EXPORT_LIMIT, offset: int = 0) -> ConversationExportPage:
        """本人（`operator_id` = 当前用户）全部**未软删**会话（含归档）+ 各自全部消息。"""
        ensure_can_converse(context)
        with self._lock:
            mine = [
                conversation
                for (tenant_id, _key), conversation in self._conversations.items()
                if tenant_id == context.tenant_id
                and conversation.operator_id == context.user_id
                and conversation.deleted_at is None
            ]
            mine.sort(key=lambda item: _sort_key(item.created_at, item.conversation_id), reverse=True)
            page = mine[offset : offset + _clamp_export(limit)]
            conversations = [
                (
                    conversation,
                    sorted(
                        self._messages.get((context.tenant_id, conversation.conversation_id), []),
                        key=lambda item: _sort_key(item.created_at, item.message_id),
                    ),
                )
                for conversation in page
            ]
            total_messages = sum(
                len(self._messages.get((context.tenant_id, conversation.conversation_id), []))
                for conversation in mine
            )
        return ConversationExportPage(
            conversations=conversations,
            total_conversations=len(mine),
            total_messages=total_messages,
        )

    # ------------------------------------------------------------ 消息（append-only）

    def append_message(self, context: UserContext, conversation_id: str, *, role: str | MessageRole, content: str, tool_name: str | None = None, tool_call_id: str | None = None) -> ConversationMessage:
        ensure_can_converse(context)
        clean_role = normalize_role(role)
        clean_content = normalize_content(content)
        with self._lock:
            conversation = self._conversations.get((context.tenant_id, str(conversation_id)))
            if conversation is None or conversation.deleted_at is not None:
                raise ConversationNotFound(conversation_id)
            ensure_can_modify(context, conversation)
            if conversation.status != ConversationStatus.ACTIVE:
                raise ConversationStateConflict("会话已归档，不能再追加消息")
            message = ConversationMessage(
                tenant_id=context.tenant_id,
                message_id=new_message_id(),
                conversation_id=conversation.conversation_id,
                role=clean_role,
                content=clean_content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
            self._messages.setdefault((context.tenant_id, conversation.conversation_id), []).append(message)
            self._conversations[(context.tenant_id, conversation.conversation_id)] = replace(
                conversation, updated_at=now()
            )
            return message

    def list_messages(self, context: UserContext, conversation_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ConversationMessage], int]:
        conversation = self.get_conversation(context, conversation_id)
        with self._lock:
            matched = list(self._messages.get((context.tenant_id, conversation.conversation_id), []))
        matched.sort(key=lambda item: _sort_key(item.created_at, item.message_id))
        return matched[offset : offset + _clamp(limit)], len(matched)

    def get_message(self, context: UserContext, conversation_id: str, message_id: str) -> ConversationMessage:
        """按标识反查单条消息（幂等重放重建首次响应所需）；不属于该会话一律「未找到」。"""
        conversation = self.get_conversation(context, conversation_id)
        with self._lock:
            for message in self._messages.get((context.tenant_id, conversation.conversation_id), []):
                if message.message_id == message_id:
                    return message
        raise ConversationNotFound(message_id)


class PostgresConversationStore:
    """对话持久化（表 `workbench_conversations` / `workbench_conversation_messages`，迁移 023）。"""

    _CONVERSATION_COLUMNS = "tenant_id, conversation_id, agent_key, operator_id, title, status, dsh_session_id, created_at, updated_at, mode, deleted_at"
    _MESSAGE_COLUMNS = "tenant_id, message_id, conversation_id, role, content, tool_name, tool_call_id, created_at"

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate_conversation(row: tuple) -> Conversation:
        return Conversation(
            tenant_id=str(row[0]),
            conversation_id=str(row[1]),
            agent_key=None if row[2] is None else str(row[2]),
            operator_id=str(row[3]),
            title=str(row[4]),
            status=ConversationStatus(str(row[5])),
            dsh_session_id=None if row[6] is None else str(row[6]),
            created_at=row[7],
            updated_at=row[8],
            mode=ConversationMode(str(row[9])),
            deleted_at=row[10],
        )

    @staticmethod
    def _hydrate_message(row: tuple) -> ConversationMessage:
        return ConversationMessage(
            tenant_id=str(row[0]),
            message_id=str(row[1]),
            conversation_id=str(row[2]),
            role=MessageRole(str(row[3])),
            content=str(row[4]),
            tool_name=None if row[5] is None else str(row[5]),
            tool_call_id=None if row[6] is None else str(row[6]),
            created_at=row[7],
        )

    # ------------------------------------------------------------ 会话

    def create_conversation(self, context: UserContext, *, agent_key: str | None = None, title: str = "") -> Conversation:
        ensure_can_converse(context)
        conversation = Conversation(
            tenant_id=context.tenant_id,
            conversation_id=new_conversation_id(),
            operator_id=context.user_id,
            agent_key=normalize_agent_key(agent_key),
            title=normalize_title(title),
        )
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_conversations
                            (tenant_id, conversation_id, agent_key, operator_id, title, status, dsh_session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._CONVERSATION_COLUMNS}
                        """,
                        (
                            conversation.tenant_id,
                            conversation.conversation_id,
                            conversation.agent_key,
                            conversation.operator_id,
                            conversation.title,
                            conversation.status.value,
                            conversation.dsh_session_id,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise ConversationStateConflict("会话创建失败")
        return self._hydrate_conversation(row)

    def get_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        ensure_can_converse(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                    WHERE tenant_id = %s AND conversation_id = %s
                    """,
                    (context.tenant_id, str(conversation_id)),
                )
                row = cursor.fetchone()
        # 软删行按「不存在」处理（与不存在不可区分）；未软删行才做可见性判定（ceo / 超管可读本租户他人会话）。
        if row is None or row[10] is not None:
            raise ConversationNotFound(conversation_id)
        conversation = self._hydrate_conversation(row)
        ensure_can_view(context, conversation)
        return conversation

    def get_conversation_including_deleted(self, context: UserContext, conversation_id: str) -> Conversation:
        """（删除路径专用）含软删行的读取：仍做**本人**校验（他人 / 跨租户一律「未找到」）。"""
        ensure_can_converse(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                    WHERE tenant_id = %s AND conversation_id = %s
                    """,
                    (context.tenant_id, str(conversation_id)),
                )
                row = cursor.fetchone()
        if row is None:
            raise ConversationNotFound(conversation_id)
        conversation = self._hydrate_conversation(row)
        ensure_can_modify(context, conversation)
        return conversation

    def list_conversations(self, context: UserContext, *, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Conversation], int]:
        ensure_can_converse(context)
        clauses = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [context.tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(ConversationStatus(status).value)
        if not can_view_any(context):
            clauses.append("operator_id = %s")
            params.append(context.user_id)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                    WHERE {where} ORDER BY created_at DESC, conversation_id DESC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_conversations WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_conversation(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def archive_conversation(self, context: UserContext, conversation_id: str) -> Conversation:
        ensure_can_converse(context)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
                    row = cursor.fetchone()
                    if row is None or row[10] is not None:
                        raise ConversationNotFound(conversation_id)
                    ensure_can_modify(context, self._hydrate_conversation(row))
                    cursor.execute(
                        f"""
                        UPDATE workbench_conversations
                        SET status = %s, updated_at = now()
                        WHERE tenant_id = %s AND conversation_id = %s
                        RETURNING {self._CONVERSATION_COLUMNS}
                        """,
                        (ConversationStatus.ARCHIVED.value, context.tenant_id, str(conversation_id)),
                    )
                    updated = cursor.fetchone()
        if updated is None:
            raise ConversationNotFound(conversation_id)
        return self._hydrate_conversation(updated)

    def set_mode(self, context: UserContext, conversation_id: str, mode: str | ConversationMode) -> tuple[Conversation, ConversationMode | None]:
        """改模式：**仅本人**；软删行「未找到」；归档 `409`；同值无副作用（不写 `updated_at` / 不写审计）。"""
        clean_mode = normalize_mode(mode)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
                    row = cursor.fetchone()
                    if row is None or row[10] is not None:
                        raise ConversationNotFound(conversation_id)
                    existing = self._hydrate_conversation(row)
                    ensure_can_modify(context, existing)
                    if existing.status != ConversationStatus.ACTIVE:
                        raise ConversationStateConflict("会话已归档，不能再修改模式")
                    if existing.mode == clean_mode:
                        return existing, None
                    cursor.execute(
                        f"""
                        UPDATE workbench_conversations
                        SET mode = %s, updated_at = now()
                        WHERE tenant_id = %s AND conversation_id = %s
                        RETURNING {self._CONVERSATION_COLUMNS}
                        """,
                        (clean_mode.value, context.tenant_id, str(conversation_id)),
                    )
                    updated = cursor.fetchone()
        if updated is None:
            raise ConversationNotFound(conversation_id)
        return self._hydrate_conversation(updated), existing.mode

    def delete_conversation_content(self, context: UserContext, conversation_id: str) -> int:
        """真删消息行 + 会话行软删（`title=''`）——**同一事务**（外键要求幂等行已先删）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ConversationNotFound(conversation_id)
                    existing = self._hydrate_conversation(row)
                    ensure_can_modify(context, existing)
                    cursor.execute(
                        """
                        DELETE FROM workbench_conversation_messages
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
                    deleted = int(cursor.rowcount)
                    cursor.execute(
                        """
                        UPDATE workbench_conversations
                        SET title = '', deleted_at = now(), updated_at = now()
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
        return deleted

    def export_mine(self, context: UserContext, *, limit: int = MAX_EXPORT_LIMIT, offset: int = 0) -> ConversationExportPage:
        """本人（`operator_id` = 当前用户）全部**未软删**会话（含归档）+ 本页会话的全部消息。"""
        ensure_can_converse(context)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                    WHERE tenant_id = %s AND operator_id = %s AND deleted_at IS NULL
                    ORDER BY created_at DESC, conversation_id DESC LIMIT %s OFFSET %s
                    """,
                    (context.tenant_id, context.user_id, _clamp_export(limit), offset),
                )
                rows = cursor.fetchall()
                page = [self._hydrate_conversation(row) for row in rows]
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM workbench_conversations
                    WHERE tenant_id = %s AND operator_id = %s AND deleted_at IS NULL
                    """,
                    (context.tenant_id, context.user_id),
                )
                total_conversations = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM workbench_conversation_messages m
                    JOIN workbench_conversations c
                      ON c.tenant_id = m.tenant_id AND c.conversation_id = m.conversation_id
                    WHERE c.tenant_id = %s AND c.operator_id = %s AND c.deleted_at IS NULL
                    """,
                    (context.tenant_id, context.user_id),
                )
                total_messages = int(cursor.fetchone()[0])
                messages: dict[str, list[ConversationMessage]] = {item.conversation_id: [] for item in page}
                if page:
                    cursor.execute(
                        f"""
                        SELECT {self._MESSAGE_COLUMNS} FROM workbench_conversation_messages
                        WHERE tenant_id = %s AND conversation_id = ANY(%s)
                        ORDER BY conversation_id, created_at, message_id
                        """,
                        (context.tenant_id, list(messages)),
                    )
                    for row in cursor.fetchall():
                        messages[str(row[2])].append(self._hydrate_message(row))
        return ConversationExportPage(
            conversations=[(item, messages[item.conversation_id]) for item in page],
            total_conversations=total_conversations,
            total_messages=total_messages,
        )

    # ------------------------------------------------------------ 消息（append-only）

    def append_message(self, context: UserContext, conversation_id: str, *, role: str | MessageRole, content: str, tool_name: str | None = None, tool_call_id: str | None = None) -> ConversationMessage:
        ensure_can_converse(context)
        clean_role = normalize_role(role)
        clean_content = normalize_content(content)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._CONVERSATION_COLUMNS} FROM workbench_conversations
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, str(conversation_id)),
                    )
                    row = cursor.fetchone()
                    if row is None or row[10] is not None:
                        raise ConversationNotFound(conversation_id)
                    conversation = self._hydrate_conversation(row)
                    ensure_can_modify(context, conversation)
                    if conversation.status != ConversationStatus.ACTIVE:
                        raise ConversationStateConflict("会话已归档，不能再追加消息")
                    message_id = new_message_id()
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_conversation_messages
                            (tenant_id, message_id, conversation_id, role, content, tool_name, tool_call_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._MESSAGE_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            message_id,
                            conversation.conversation_id,
                            clean_role.value,
                            clean_content,
                            tool_name,
                            tool_call_id,
                        ),
                    )
                    message_row = cursor.fetchone()
                    cursor.execute(
                        """
                        UPDATE workbench_conversations
                        SET updated_at = now()
                        WHERE tenant_id = %s AND conversation_id = %s
                        """,
                        (context.tenant_id, conversation.conversation_id),
                    )
        if message_row is None:
            raise ConversationStateConflict("消息写入失败")
        return self._hydrate_message(message_row)

    def list_messages(self, context: UserContext, conversation_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ConversationMessage], int]:
        conversation = self.get_conversation(context, conversation_id)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._MESSAGE_COLUMNS} FROM workbench_conversation_messages
                    WHERE tenant_id = %s AND conversation_id = %s
                    ORDER BY created_at, message_id LIMIT %s OFFSET %s
                    """,
                    (context.tenant_id, conversation.conversation_id, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM workbench_conversation_messages WHERE tenant_id = %s AND conversation_id = %s",
                    (context.tenant_id, conversation.conversation_id),
                )
                count_row = cursor.fetchone()
        return [self._hydrate_message(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def get_message(self, context: UserContext, conversation_id: str, message_id: str) -> ConversationMessage:
        """按标识反查单条消息（幂等重放重建首次响应所需）；归属校验走 `get_conversation`。"""
        conversation = self.get_conversation(context, conversation_id)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._MESSAGE_COLUMNS} FROM workbench_conversation_messages
                    WHERE tenant_id = %s AND conversation_id = %s AND message_id = %s
                    """,
                    (context.tenant_id, conversation.conversation_id, str(message_id)),
                )
                row = cursor.fetchone()
        if row is None:
            raise ConversationNotFound(message_id)
        return self._hydrate_message(row)
