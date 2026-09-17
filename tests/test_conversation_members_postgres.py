"""P2c-6 **真库**回归：会话成员表（迁移 `039`）与消息 `sender_id` 列。

口径：沿用 `tests/test_conversation_lifecycle_postgres.py` 先例——
DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip；目标库须已完成全部迁移（含 `039`）；
本文件**不建表、不迁移**；只操作本文件声明的租户，用例前后自清。

覆盖规格 §4「P2c-6（协作）真库用例」的库级部分：
  ① 成员表：受控权限档（表级 CHECK 拦非法值）、复合外键引用会话表（悬空引用被拒、删会话行级联）；
  ② 消息 `sender_id`：user 消息落发言者、助手 / 工具 / 系统落 `NULL`；存量 `NULL` 可读回（零破坏）；
  ③ 读路径「本人 ∪ 成员」真库生效：共享会话进成员列表、非成员不可见、成员可读详情；
  ④ 撤销后新读「未找到」；复删幂等；
  ⑤ 发言写权限：`read` 成员被拒（读得到、写不了）；`write` 成员发言成功且 `sender_id` 正确；
  ⑥ 审计：`conversation.member.added` / `.removed` 落真库审计表，明细受控键、不含正文 / 姓名 / 手机号。

局限（如实）：账号仓储用内存实现——本文件聚焦**成员表与消息列**的真库行为；
账号合法性校验（跨租户 / 未审批 / `customer_admin`）属接口层用例，见 `tests/test_conversation_members_api.py`。
"""

from __future__ import annotations

import os

import pytest

from app.accounts.models import Account, AccountStatus
from app.accounts.repository import InMemoryAccountRepository
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import PostgresAuditStore
from app.conversation.members import PostgresConversationMemberStore
from app.conversation.models import ConversationNotFound, ConversationStateConflict
from app.conversation.service import ConversationService
from app.conversation.store import PostgresConversationStore
from app.domain import PolicyError, UserContext

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-members-pg"
TENANT_OTHER = "test-members-pg-other"
OWNER = "u-m-owner"
MEMBER = "u-m-member"
STRANGER = "u-m-stranger"


def _purge(connection) -> None:
    tenants = (TENANT, TENANT_OTHER)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_conversation_members WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute(
            "DELETE FROM workbench_conversation_messages WHERE tenant_id IN (%s, %s)", tenants
        )
        cursor.execute("DELETE FROM workbench_conversations WHERE tenant_id IN (%s, %s)", tenants)
        cursor.execute("DELETE FROM workbench_audit_log WHERE tenant_id IN (%s, %s)", tenants)


def _account(index: int, account_id: str, *, tenant: str = TENANT) -> Account:
    return Account(
        phone=f"1391000{index:04d}",
        password_hash="hash",
        position="岗位",
        full_name=f"姓名-{account_id}",
        account_id=account_id,
        role="employee",
        tenant_id=tenant,
        status=AccountStatus.APPROVED,
    )


@pytest.fixture()
def env():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    members = PostgresConversationMemberStore(connection)
    store = PostgresConversationStore(connection, members=members)
    audit_store = PostgresAuditStore(connection)
    accounts = InMemoryAccountRepository()
    accounts.add(_account(0, OWNER))
    accounts.add(_account(1, MEMBER))
    accounts.add(_account(2, STRANGER))
    service = ConversationService(
        store,
        audit=AuditService(audit_store),
        members=members,
        accounts=accounts,
    )
    yield {
        "psycopg": psycopg,
        "connection": connection,
        "members": members,
        "store": store,
        "service": service,
        "audit": audit_store,
    }
    _purge(connection)
    connection.close()


def _owner(tenant: str = TENANT, user_id: str = OWNER) -> UserContext:
    return UserContext(tenant, user_id, "employee")


def _seed(env, *, tenant: str = TENANT, user_id: str = OWNER, agent_key: str | None = "content-writer") -> str:
    conversation = env["service"].create_conversation(_owner(tenant, user_id), agent_key=agent_key)
    return conversation.conversation_id


# ------------------------------------------------------------ ① 成员表约束


def test_permission_check_and_composite_foreign_key(env) -> None:
    conversation_id = _seed(env)
    with env["connection"].cursor() as cursor:
        # 表级 CHECK：绕过接口直接 SQL 也写不进非法权限档。
        with pytest.raises(env["psycopg"].errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO workbench_conversation_members
                    (tenant_id, conversation_id, member_id, permission, added_by)
                VALUES (%s, %s, %s, 'admin', %s)
                """,
                (TENANT, conversation_id, MEMBER, OWNER),
            )
        # 复合外键：悬空会话引用被拒（不存在 / 跨租户同号都不可能蒙混）。
        with pytest.raises(env["psycopg"].errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO workbench_conversation_members
                    (tenant_id, conversation_id, member_id, permission, added_by)
                VALUES (%s, %s, %s, 'read', %s)
                """,
                (TENANT, "conv-not-exist", MEMBER, OWNER),
            )
        # 主键去重：同一 (租户, 会话, 成员) 只有一行。
        cursor.execute(
            """
            INSERT INTO workbench_conversation_members
                (tenant_id, conversation_id, member_id, permission, added_by)
            VALUES (%s, %s, %s, 'read', %s)
            """,
            (TENANT, conversation_id, MEMBER, OWNER),
        )
        with pytest.raises(env["psycopg"].errors.UniqueViolation):
            cursor.execute(
                """
                INSERT INTO workbench_conversation_members
                    (tenant_id, conversation_id, member_id, permission, added_by)
                VALUES (%s, %s, %s, 'write', %s)
                """,
                (TENANT, conversation_id, MEMBER, OWNER),
            )
        # 删会话行 ⇒ 成员行级联清理（快照 / 测试清场语义；生产会话行只软删）。
        cursor.execute("DELETE FROM workbench_conversations WHERE tenant_id = %s AND conversation_id = %s",
                       (TENANT, conversation_id))
    assert env["members"].list_for_conversation(TENANT, conversation_id) == []


# ------------------------------------------------------------ ② sender_id


def test_sender_id_is_persisted_and_legacy_null_reads_back(env) -> None:
    conversation_id = _seed(env)
    context = _owner()

    user_message = env["store"].append_message(context, conversation_id, role="user", content="本人发言")
    reply = env["store"].append_message(context, conversation_id, role="assistant", content="（P1 桩回复）")
    assert user_message.sender_id == OWNER
    assert reply.sender_id is None

    # 存量行（迁移前写入）`sender_id` 为 NULL ⇒ 读回 None（展示回退为「发起人」，零破坏）。
    with env["connection"].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_conversation_messages
                (tenant_id, message_id, conversation_id, role, content, sender_id)
            VALUES (%s, %s, %s, 'user', '存量消息', NULL)
            """,
            (TENANT, "msg-legacy-1", conversation_id),
        )
    messages, total = env["store"].list_messages(context, conversation_id)
    assert total == 3
    legacy = next(item for item in messages if item.message_id == "msg-legacy-1")
    assert legacy.sender_id is None
    # 幂等重放靠 `get_message` 反查单条：同样带回发送者（不改既有语义，只增字段）。
    assert env["store"].get_message(context, conversation_id, user_message.message_id).sender_id == OWNER


# ------------------------------------------------------------ ③④ 读路径与撤销


def test_member_visibility_and_revocation(env) -> None:
    conversation_id = _seed(env)
    assert env["service"].add_member(_owner(), conversation_id, member_id=MEMBER).permission == "read"

    member = _owner(user_id=MEMBER)
    assert env["store"].get_conversation(member, conversation_id).conversation_id == conversation_id
    listed_ids = [item.conversation_id for item in env["store"].list_conversations(member, limit=50)[0]]
    assert listed_ids == [conversation_id]

    # 非成员：列表不含、详情「未找到」。
    stranger = _owner(user_id=STRANGER)
    assert env["store"].list_conversations(stranger, limit=50)[0] == []
    with pytest.raises(ConversationNotFound):
        env["store"].get_conversation(stranger, conversation_id)
    # 跨租户同样不可见。
    with pytest.raises(ConversationNotFound):
        env["store"].get_conversation(_owner(TENANT_OTHER), conversation_id)

    # 撤销 ⇒ 新读请求「未找到」（已读内容不可撤回）；复删幂等（不再写审计）。
    assert env["service"].remove_member(_owner(), conversation_id, MEMBER) is True
    with pytest.raises(ConversationNotFound):
        env["store"].get_conversation(member, conversation_id)
    assert env["service"].remove_member(_owner(), conversation_id, MEMBER) is False
    rows, total = env["audit"].query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_REMOVED])
    assert total == 1
    assert set(rows[0].detail) == {"conversation_id", "member_id", "permission"}
    assert all("姓名" not in str(value) for value in rows[0].detail.values())


def test_read_member_cannot_speak_but_write_member_can(env) -> None:
    conversation_id = _seed(env)
    env["service"].add_member(_owner(), conversation_id, member_id=MEMBER)
    member = _owner(user_id=MEMBER)

    # `read` 档：读得到、写不了（403 语义；仓储层同样强制，绕过服务层不行）。
    with pytest.raises(PolicyError):
        env["store"].append_message(member, conversation_id, role="user", content="我能发言吗")

    env["service"].add_member(_owner(), conversation_id, member_id=MEMBER, permission="write")
    message = env["store"].append_message(member, conversation_id, role="user", content="我来协作")
    assert message.sender_id == MEMBER
    # 管理动作仍仅本人：成员改模式 / 归档 / 增删成员一律「未找到」。
    with pytest.raises(ConversationNotFound):
        env["store"].set_mode(member, conversation_id, "ask")
    with pytest.raises(ConversationNotFound):
        env["store"].archive_conversation(member, conversation_id)
    with pytest.raises(ConversationNotFound):
        env["service"].add_member(member, conversation_id, member_id=STRANGER)
    with pytest.raises(ConversationNotFound):
        env["service"].remove_member(member, conversation_id, MEMBER)


def test_archived_conversation_rejects_member_changes(env) -> None:
    conversation_id = _seed(env)
    env["service"].archive_conversation(_owner(), conversation_id)

    with pytest.raises(ConversationStateConflict):
        env["service"].add_member(_owner(), conversation_id, member_id=MEMBER)
    with pytest.raises(ConversationStateConflict):
        env["service"].remove_member(_owner(), conversation_id, MEMBER)


# ------------------------------------------------------------ ⑥ 审计（真库表）


def test_member_audit_rows_are_controlled(env) -> None:
    conversation_id = _seed(env)
    env["service"].add_member(_owner(), conversation_id, member_id=MEMBER, permission="write")

    added, total = env["audit"].query(TENANT, actions=[AuditAction.CONVERSATION_MEMBER_ADDED])
    assert total == 1
    assert added[0].target_type == "conversation"
    assert added[0].target_id == conversation_id
    assert added[0].detail == {"conversation_id": conversation_id, "member_id": MEMBER, "permission": "write"}
    assert added[0].actor_id == OWNER