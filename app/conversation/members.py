"""会话协作的**成员表**（`workbench_conversation_members`，迁移 `039`）。

口径（真源）：
    契约 `docs/api-contract.md`「会话协作：分享与多端协同（P2c-6 · 2026-09-17）」；
    规格 §2.16（已评审 2026-09-17）。

要点：
    * `read` / `write` **两档受控枚举**（与迁移 `039` 的 CHECK 一字不差）；`owner` 是**展示值**，
      不入库（发起人由会话行 `operator_id` 解析，`GET .../members` 列首位且不可撤销）。
    * 本表只承载「谁被点名分享」；**可见性判定**复用 `models.ensure_can_view` /
      `ensure_can_speak`（读 = 本人 ∪ 成员；写 = 本人 ∪ `write` 成员），不在这里另造一套判定。
    * 表里不做活动时间列（**不做实时在线态**，「最近活动时间」取会话 `updated_at`）。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

from .models import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    PERMISSION_WRITE,
    PERMISSIONS,
    now as _now,
)

__all__ = [
    "PERMISSION_OWNER",
    "PERMISSION_READ",
    "PERMISSION_WRITE",
    "PERMISSIONS",
    "ConversationMember",
    "ConversationMemberStore",
    "InMemoryConversationMemberStore",
    "PostgresConversationMemberStore",
]


@dataclass(frozen=True)
class ConversationMember:
    """`workbench_conversation_members` 一行。"""

    tenant_id: str
    conversation_id: str
    member_id: str
    permission: str
    added_by: str
    created_at: datetime | None = None


class ConversationMemberStore(Protocol):
    def permission_for(self, tenant_id: str, conversation_id: str, member_id: str) -> str | None:
        """该成员对该会话的授权档（`read` / `write`）；不是成员返回 `None`。"""
        ...

    def list_for_conversation(self, tenant_id: str, conversation_id: str) -> list[ConversationMember]:
        """该会话的全部成员（按加入时间升序；**不含**发起人——由服务层补首位）。"""
        ...

    def upsert(self, *, tenant_id: str, conversation_id: str, member_id: str, permission: str,
               added_by: str) -> ConversationMember:
        """添加 / 覆盖权限档（同一 `(租户, 会话, 成员)` 只有一行）。"""
        ...

    def delete(self, tenant_id: str, conversation_id: str, member_id: str) -> bool:
        """撤销成员；**幂等**：本就不是成员返回 `False`（调用方据此不重复写审计）。"""
        ...

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        """**租户整层清场（B1）**：生命周期专用物理删除（整层成员表），语义见实现 docstring。"""
        ...


class InMemoryConversationMemberStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], ConversationMember] = {}
        self._lock = RLock()

    def permission_for(self, tenant_id: str, conversation_id: str, member_id: str) -> str | None:
        with self._lock:
            item = self._items.get((str(tenant_id), str(conversation_id), str(member_id)))
        return item.permission if item is not None else None

    def list_for_conversation(self, tenant_id: str, conversation_id: str) -> list[ConversationMember]:
        with self._lock:
            matched = [
                item
                for (item_tenant, item_conversation, _member), item in self._items.items()
                if item_tenant == str(tenant_id) and item_conversation == str(conversation_id)
            ]
        matched.sort(key=lambda item: (item.created_at or datetime.min, item.member_id))
        return matched

    def upsert(self, *, tenant_id: str, conversation_id: str, member_id: str, permission: str,
               added_by: str) -> ConversationMember:
        key = (str(tenant_id), str(conversation_id), str(member_id))
        with self._lock:
            existing = self._items.get(key)
            item = ConversationMember(
                tenant_id=key[0],
                conversation_id=key[1],
                member_id=key[2],
                permission=str(permission),
                added_by=str(added_by),
                created_at=existing.created_at if existing is not None else _now(),
            )
            self._items[key] = item
            return item

    def delete(self, tenant_id: str, conversation_id: str, member_id: str) -> bool:
        with self._lock:
            return self._items.pop((str(tenant_id), str(conversation_id), str(member_id)), None) is not None

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        """**租户整层清场（B1）**：真删本租户全部成员行，返回删除行数。

        本表对会话行是 `ON DELETE CASCADE`（039），单独显式删是为了与其他子表**同一口径**
        （整层清场逐表可数、不依赖级联），且顺序排在会话行之前。幂等、只动本租户。
        """
        with self._lock:
            keys = [key for key in self._items if key[0] == tenant_id]
            for key in keys:
                self._items.pop(key, None)
            return len(keys)


class PostgresConversationMemberStore:
    """`workbench_conversation_members` 持久化（迁移 `039`）。"""

    _COLUMNS = "tenant_id, conversation_id, member_id, permission, added_by, created_at"

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
    def _hydrate(row: tuple) -> ConversationMember:
        return ConversationMember(
            tenant_id=str(row[0]),
            conversation_id=str(row[1]),
            member_id=str(row[2]),
            permission=str(row[3]),
            added_by=str(row[4]),
            created_at=row[5],
        )

    def permission_for(self, tenant_id: str, conversation_id: str, member_id: str) -> str | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT permission FROM workbench_conversation_members
                    WHERE tenant_id = %s AND conversation_id = %s AND member_id = %s
                    """,
                    (tenant_id, str(conversation_id), str(member_id)),
                )
                row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def list_for_conversation(self, tenant_id: str, conversation_id: str) -> list[ConversationMember]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_conversation_members
                    WHERE tenant_id = %s AND conversation_id = %s
                    ORDER BY created_at, member_id
                    """,
                    (tenant_id, str(conversation_id)),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def upsert(self, *, tenant_id: str, conversation_id: str, member_id: str, permission: str,
               added_by: str) -> ConversationMember:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_conversation_members
                            (tenant_id, conversation_id, member_id, permission, added_by)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, conversation_id, member_id)
                        DO UPDATE SET permission = EXCLUDED.permission, added_by = EXCLUDED.added_by
                        RETURNING {self._COLUMNS}
                        """,
                        (tenant_id, str(conversation_id), str(member_id), str(permission), str(added_by)),
                    )
                    row = cursor.fetchone()
        if row is None:  # pragma: no cover - RETURNING 恒有行；仅为类型收敛
            raise RuntimeError("成员写入失败")
        return self._hydrate(row)

    def delete(self, tenant_id: str, conversation_id: str, member_id: str) -> bool:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM workbench_conversation_members
                        WHERE tenant_id = %s AND conversation_id = %s AND member_id = %s
                        """,
                        (tenant_id, str(conversation_id), str(member_id)),
                    )
                    return int(cursor.rowcount) > 0

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        """**租户整层清场（B1）**：真删本租户全部成员行，返回删除行数（语义同内存实现）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_conversation_members WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    return int(cursor.rowcount)