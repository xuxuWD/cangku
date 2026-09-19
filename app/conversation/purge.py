"""会话层租户清场（**B1**，2026-09-19）：租户删除时把会话层**整层**物理清空。

依据：`docs/superpowers/specs/2026-09-19-tenant-purge-expansion-design.md` §3/§4.1（B1 会话层）；
对外口径见 `docs/api-contract.md`「删除清场口径」段。

**为什么需要一个组合类**：会话层不是一个 store，而是**四张表 / 四个仓储**（会话与消息、成员、
流帧与流态、执行幂等），且它们之间有**固定的外键顺序**（真库实测，2026-09-19）：

| 顺序 | 表 | 为什么在这个位置 |
| --- | --- | --- |
| 1 | `workbench_execution_idempotency` | 同时以 `(tenant_id, conversation_id)` 与 `(tenant_id, message_id)` 引用会话行与消息行（027，**均无级联**）⇒ 必须最先删，否则后两步被外键拒绝 |
| 2 | `workbench_conversation_stream_frames` / `..._stream_state` | 以 `(tenant_id, conversation_id)` 引用会话行（036，无级联） |
| 3 | `workbench_conversation_members` | 引用会话行（039，**有**级联；仍显式删，保证逐表可数、不依赖级联） |
| 4 | `workbench_conversation_messages` → `workbench_conversations` | 消息引用会话行（023，无级联）⇒ 消息先于会话 |

该顺序与既有「单会话物理删除」的固定顺序**同源**（P2c-4：幂等行 → 帧 → 流状态 → 消息 + 会话行）。

**事务边界**：四步各自在同一连接上按序执行（每步内部一个事务），整体**幂等且可重跑**——
任何中途中断后重跑都能收敛（子表先删 ⇒ 父表随后可删）。刻意不做「一个大事务」：四个仓储各自
持有连接租约（池化），跨仓储的大事务会依赖实现细节；而逐表删除本身可重入，重跑即修复。
"""

from __future__ import annotations

from typing import Protocol

# 删除顺序（先子后父）与取证用的键名；顺序即本元组次序，改序前先看模块 docstring 的外键表。
CONVERSATION_LAYER_ORDER: tuple[tuple[str, str], ...] = (
    ("execution_idempotency", "幂等行"),
    ("stream", "流帧 + 流状态"),
    ("members", "成员行"),
    ("conversations", "消息 + 会话行"),
)


class ConversationLayerPurgeStore(Protocol):
    def delete_all_for_tenant(self, tenant_id: str) -> int: ...


class PostgresConversationLayerPurgeStore:
    """真库组合实现：四个仓储各自删自己的表，**按 `CONVERSATION_LAYER_ORDER` 的固定顺序**调用。"""

    def __init__(
        self,
        connection_or_pool,
        *,
        conversations=None,
        members=None,
        stream=None,
        idempotency=None,
    ) -> None:
        from .idempotency import PostgresExecutionIdempotencyStore
        from .members import PostgresConversationMemberStore
        from .stream import PostgresStreamStore
        from .store import PostgresConversationStore

        # 允许显式传入（worker / API 可复用各自既有实例）；未传则用同一连接自建。
        self.conversations = conversations or PostgresConversationStore(connection_or_pool)
        self.members = members or PostgresConversationMemberStore(connection_or_pool)
        self.stream = stream or PostgresStreamStore(connection_or_pool)
        self.idempotency = idempotency or PostgresExecutionIdempotencyStore(connection_or_pool)

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        deleted = 0
        deleted += int(self.idempotency.delete_all_for_tenant(tenant_id))
        deleted += int(self.stream.delete_all_for_tenant(tenant_id))
        deleted += int(self.members.delete_all_for_tenant(tenant_id))
        deleted += int(self.conversations.delete_all_for_tenant(tenant_id))
        return deleted


class InMemoryConversationLayerPurgeStore:
    """内存组合实现（development / 单测）：四个内存仓储按同一顺序删各自的字典键。

    ⚠️ 内存模式**不装配**本面（`build_commercial_components` 的内存分支不注入它）：内存会话仓储由
    API 进程各自持有，商业化装配拿不到同一实例；生产删除流程在 worker（PG 强制）执行 ⇒ 不受影响。
    本类供单测直接构造（口径：与 PG 同顺序、同幂等）。
    """

    def __init__(self, *, conversations, members, stream, idempotency) -> None:
        self.conversations = conversations
        self.members = members
        self.stream = stream
        self.idempotency = idempotency

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        deleted = 0
        deleted += int(self.idempotency.delete_all_for_tenant(tenant_id))
        deleted += int(self.stream.delete_all_for_tenant(tenant_id))
        deleted += int(self.members.delete_all_for_tenant(tenant_id))
        deleted += int(self.conversations.delete_all_for_tenant(tenant_id))
        return deleted