"""知识治理层（知识文档生命周期 + 检索谓词守卫）。

口径见 `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md`。
本阶段先实现领域核心（模型 / 仓储 / 服务），路由、配置接线与审计动作码由主代理负责。
"""

from .models import (
    InvalidKnowledgeDoc,
    KnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeDocStateConflict,
    KnowledgeDocStatus,
    KnowledgeGovernanceError,
    MANAGE_ROLES,
    MAX_DOCUMENT_ID_LENGTH,
    MAX_SOURCE_KEY_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_VERSION_LENGTH,
    SOURCE_KEY_PATTERN,
    can_manage,
    can_read_metrics,
    ensure_can_manage,
    ensure_can_read_metrics,
    normalize_document_id,
    normalize_owner_id,
    normalize_source_key,
    normalize_title,
    normalize_version,
    transition_allowed,
)
from .service import KnowledgeGovernanceService
from .store import InMemoryKnowledgeGovStore, KnowledgeGovStore, PostgresKnowledgeGovStore

__all__ = [
    "InvalidKnowledgeDoc",
    "KnowledgeDoc",
    "KnowledgeDocNotFound",
    "KnowledgeDocStateConflict",
    "KnowledgeDocStatus",
    "KnowledgeGovernanceError",
    "MANAGE_ROLES",
    "MAX_DOCUMENT_ID_LENGTH",
    "MAX_SOURCE_KEY_LENGTH",
    "MAX_TITLE_LENGTH",
    "MAX_VERSION_LENGTH",
    "SOURCE_KEY_PATTERN",
    "can_manage",
    "can_read_metrics",
    "ensure_can_manage",
    "ensure_can_read_metrics",
    "normalize_document_id",
    "normalize_owner_id",
    "normalize_source_key",
    "normalize_title",
    "normalize_version",
    "transition_allowed",
    "KnowledgeGovernanceService",
    "KnowledgeGovStore",
    "InMemoryKnowledgeGovStore",
    "PostgresKnowledgeGovStore",
]