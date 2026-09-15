"""P3 记忆层（记忆 / 画像）。

口径见 `docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md`。
本阶段先实现领域核心（模型 / 嵌入适配器 / 仓储 / 服务），路由与配置接线由主代理负责。
"""

from .models import (
    EMBEDDING_DIMENSIONS,
    MAX_MEMORY_CONTENT_LENGTH,
    MAX_PROFILE_KEYS_PER_OWNER,
    MAX_PROFILE_VALUE_LENGTH,
    VIEW_ANY_ROLES,
    InvalidMemory,
    MemoryBudgetExceeded,
    MemoryError,
    MemoryFact,
    MemoryNotFound,
    MemoryOwnerKind,
    MemoryProfileKey,
    MemoryRule,
    MemoryScope,
    MemoryStateConflict,
    MemoryStatus,
    ensure_can_manage,
    ensure_can_view,
    normalize_content,
    normalize_owner_kind,
    normalize_profile_key,
    normalize_profile_value,
    normalize_rule_key,
    normalize_scope,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "MAX_MEMORY_CONTENT_LENGTH",
    "MAX_PROFILE_KEYS_PER_OWNER",
    "MAX_PROFILE_VALUE_LENGTH",
    "VIEW_ANY_ROLES",
    "InvalidMemory",
    "MemoryBudgetExceeded",
    "MemoryError",
    "MemoryFact",
    "MemoryNotFound",
    "MemoryOwnerKind",
    "MemoryProfileKey",
    "MemoryRule",
    "MemoryScope",
    "MemoryStateConflict",
    "MemoryStatus",
    "ensure_can_manage",
    "ensure_can_view",
    "normalize_content",
    "normalize_owner_kind",
    "normalize_profile_key",
    "normalize_profile_value",
    "normalize_rule_key",
    "normalize_scope",
]