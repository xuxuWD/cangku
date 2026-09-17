"""对话仓储：租户隔离、归属校验、分页、append-only、已停用员工的历史会话仍可读。

口径见 `docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md` §7 / §8 / §12。
先写测试（此时实现尚不存在，收集即红），再写实现使其转绿。
"""

from __future__ import annotations

import pytest

from app.conversation.models import (
    ConversationNotFound,
    ConversationStateConflict,
    ConversationStatus,
    InvalidConversation,
    MessageRole,
)
from app.conversation.store import (
    InMemoryConversationStore,
    PostgresConversationStore,
)
from app.domain import PolicyError, UserContext

EMPLOYEE = UserContext("t-1", "u-1", "employee")
OTHER_EMPLOYEE = UserContext("t-1", "u-2", "employee")
CEO = UserContext("t-1", "ceo-1", "ceo")
OTHER_TENANT = UserContext("t-2", "u-9", "employee")
# 他租户的 CEO：若租户过滤被去掉，它会「合法地」看到 t-1 的会话，从而暴露缺陷
OTHER_TENANT_CEO = UserContext("t-2", "ceo-9", "ceo")
CUSTOMER_ADMIN = UserContext("t-1", "ca-1", "customer_admin")


# ------------------------------------------------------------ 创建与租户隔离


def test_create_conversation_normalizes_agent_key_and_scopes_tenant() -> None:
    store = InMemoryConversationStore()

    conversation = store.create_conversation(EMPLOYEE, agent_key="  Content-Writer  ", title="  咨询  ")

    assert conversation.agent_key == "content-writer"
    assert conversation.title == "咨询"
    assert conversation.operator_id == "u-1"
    assert conversation.status == ConversationStatus.ACTIVE
    # 他租户看不到
    assert store.list_conversations(OTHER_TENANT) == ([], 0)


@pytest.mark.parametrize("bad_key", ["运营岗", "bad key", "-lead", "a" * 65])
def test_create_conversation_rejects_invalid_agent_key(bad_key: str) -> None:
    store = InMemoryConversationStore()

    with pytest.raises(InvalidConversation):
        store.create_conversation(EMPLOYEE, agent_key=bad_key)


def test_conversation_requires_a_conversing_role() -> None:
    store = InMemoryConversationStore()

    with pytest.raises(PolicyError):
        store.create_conversation(CUSTOMER_ADMIN, agent_key=None)
    with pytest.raises(PolicyError):
        store.list_conversations(CUSTOMER_ADMIN)


# ------------------------------------------------------------ 列表与分页


def test_list_conversations_only_lists_own_but_ceo_sees_tenant() -> None:
    store = InMemoryConversationStore()
    for index in range(3):
        store.create_conversation(EMPLOYEE, agent_key=None, title=f"会话 {index}")
    store.create_conversation(OTHER_EMPLOYEE, agent_key=None, title="别人的会话")

    page, total = store.list_conversations(EMPLOYEE, limit=2, offset=0)
    assert total == 3
    assert len(page) == 2

    rest, rest_total = store.list_conversations(EMPLOYEE, limit=2, offset=2)
    assert rest_total == 3
    assert len(rest) == 1

    _, ceo_total = store.list_conversations(CEO)
    assert ceo_total == 4


def test_list_conversations_filters_by_status() -> None:
    store = InMemoryConversationStore()
    active = store.create_conversation(EMPLOYEE, agent_key=None)
    archived = store.create_conversation(EMPLOYEE, agent_key=None)
    store.archive_conversation(EMPLOYEE, archived.conversation_id)

    items, total = store.list_conversations(EMPLOYEE, status="archived")
    assert total == 1
    assert [item.conversation_id for item in items] == [archived.conversation_id]

    items, total = store.list_conversations(EMPLOYEE, status="active")
    assert total == 1
    assert [item.conversation_id for item in items] == [active.conversation_id]


# ------------------------------------------------------------ 归属与跨租户（一律 404）


def test_cross_tenant_conversation_is_not_found() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    with pytest.raises(ConversationNotFound):
        store.get_conversation(OTHER_TENANT, conversation.conversation_id)
    # 关键在于他租户的 CEO 也看不到（跨租户隔离只由 tenant_id 过滤保证）
    with pytest.raises(ConversationNotFound):
        store.get_conversation(OTHER_TENANT_CEO, conversation.conversation_id)
    assert store.list_conversations(OTHER_TENANT_CEO) == ([], 0)


def test_reading_another_operators_conversation_is_not_found() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    with pytest.raises(ConversationNotFound):
        store.get_conversation(OTHER_EMPLOYEE, conversation.conversation_id)
    # CEO 可以查看本租户内他人会话
    assert store.get_conversation(CEO, conversation.conversation_id).conversation_id == conversation.conversation_id


def test_modifying_another_operators_conversation_is_not_found() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    with pytest.raises(ConversationNotFound):
        store.archive_conversation(OTHER_EMPLOYEE, conversation.conversation_id)
    with pytest.raises(ConversationNotFound):
        store.append_message(
            OTHER_EMPLOYEE, conversation.conversation_id, role=MessageRole.USER, content="越权"
        )
    # 改他人会话对任何人都是 404（不区分权限不足，避免探测存在性）
    with pytest.raises(ConversationNotFound):
        store.archive_conversation(CEO, conversation.conversation_id)


# ------------------------------------------------------------ 消息 append-only


def test_messages_are_append_only_chronological_and_paginated() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    first = store.append_message(EMPLOYEE, conversation.conversation_id, role=MessageRole.USER, content="第一句")
    second = store.append_message(
        EMPLOYEE, conversation.conversation_id, role=MessageRole.ASSISTANT, content="第二句"
    )

    page, total = store.list_messages(EMPLOYEE, conversation.conversation_id, limit=1, offset=0)
    assert total == 2
    assert [item.message_id for item in page] == [first.message_id]

    rest, _ = store.list_messages(EMPLOYEE, conversation.conversation_id, limit=10, offset=1)
    assert [item.message_id for item in rest] == [second.message_id]


def test_archiving_blocks_new_messages() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    archived = store.archive_conversation(EMPLOYEE, conversation.conversation_id)
    assert archived.status == ConversationStatus.ARCHIVED

    with pytest.raises(ConversationStateConflict):
        store.append_message(
            EMPLOYEE, conversation.conversation_id, role=MessageRole.USER, content="归档后"
        )


def test_empty_message_is_rejected_and_not_written() -> None:
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key=None)

    with pytest.raises(InvalidConversation):
        store.append_message(EMPLOYEE, conversation.conversation_id, role=MessageRole.USER, content="   ")

    _, total = store.list_messages(EMPLOYEE, conversation.conversation_id)
    assert total == 0


def test_history_survives_disabled_agent_key() -> None:
    """`agent_key` 刻意不加外键：数字员工停用后历史会话必须永远可解析。"""
    store = InMemoryConversationStore()
    conversation = store.create_conversation(EMPLOYEE, agent_key="retired-agent")
    store.append_message(EMPLOYEE, conversation.conversation_id, role=MessageRole.USER, content="历史")

    again = store.get_conversation(EMPLOYEE, conversation.conversation_id)
    assert again.agent_key == "retired-agent"
    messages, total = store.list_messages(EMPLOYEE, conversation.conversation_id)
    assert total == 1
    assert messages[0].content == "历史"


# ------------------------------------------------------------ PostgreSQL 实现


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple | None]] = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return self.rows.pop(0)

    def fetchone(self):
        return self.rows.pop(0)


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


# 表列口径与迁移 038 一致：`..., updated_at, mode, deleted_at`（软删行为 `None`）。
CONVERSATION_ROW = (
    "t-1", "conv-1", "content-writer", "u-1", "咨询", "active", None, None, None, "craft", None,
)
MESSAGE_ROW = ("t-1", "msg-1", "conv-1", "user", "你好", None, None, None)


def test_postgres_create_conversation_inserts_scoped_row() -> None:
    connection = RecordingConnection([CONVERSATION_ROW])

    conversation = PostgresConversationStore(connection).create_conversation(
        EMPLOYEE, agent_key="Content-Writer", title="咨询"
    )

    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO workbench_conversations" in statement
    assert "RETURNING" in statement
    assert params[0] == "t-1"
    assert params[2] == "content-writer"
    assert params[3] == "u-1"
    assert conversation.conversation_id == "conv-1"


def test_postgres_get_conversation_filters_by_tenant_and_reports_missing() -> None:
    connection = RecordingConnection([CONVERSATION_ROW])

    found = PostgresConversationStore(connection).get_conversation(EMPLOYEE, "conv-1")
    statement, params = connection.cursor_instance.statements[0]
    assert "WHERE tenant_id = %s AND conversation_id = %s" in statement
    assert params == ("t-1", "conv-1")
    assert found.conversation_id == "conv-1"

    with pytest.raises(ConversationNotFound):
        PostgresConversationStore(RecordingConnection([None])).get_conversation(EMPLOYEE, "nobody")


def test_postgres_list_conversations_scopes_operator_for_non_admin() -> None:
    connection = RecordingConnection([[CONVERSATION_ROW], (1,)])

    items, total = PostgresConversationStore(connection).list_conversations(EMPLOYEE, limit=10, offset=0)

    statement, params = connection.cursor_instance.statements[0]
    assert "FROM workbench_conversations" in statement
    assert "operator_id = %s" in statement
    assert params == ("t-1", "u-1", 10, 0)
    assert total == 1
    assert [item.conversation_id for item in items] == ["conv-1"]


def test_postgres_append_message_checks_conversation_then_inserts() -> None:
    connection = RecordingConnection([CONVERSATION_ROW, MESSAGE_ROW, None])

    message = PostgresConversationStore(connection).append_message(
        EMPLOYEE, "conv-1", role=MessageRole.USER, content="你好"
    )

    statements = connection.cursor_instance.statements
    assert "SELECT" in statements[0][0] and "FROM workbench_conversations" in statements[0][0]
    assert "INSERT INTO workbench_conversation_messages" in statements[1][0]
    assert "updated_at = now()" in statements[2][0]
    assert message.message_id == "msg-1"
