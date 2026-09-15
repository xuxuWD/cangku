"""知识治理层的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md` §2。

核心是「知识文档生命周期 + 检索谓词守卫」：一张注册表 `workbench_knowledge_documents`
（迁移 032），登记 Who 拥有 / 同步到什么状态 / 何时复核 / 过期即从检索谓词下线；
WeKnora 仍是检索唯一事实源（D1），本表只是**文档级元数据守卫**，不复制正文、不重建索引。

状态机（§2.2）：`draft → published → needs_review → published/archived`（`published →
under_review → needs_review → published/archived` 为可选中间态）；`archived` 终态。
发布闸门（§1.2 C / §3.2）在 service 层强制 owner 非空；本模块只做长度 / 字符串归一。
权限判定刻意放在本模块，供仓储 / 服务 / 接口层共用（沿用记忆层 / 技能层手法）：
登记 / 改状态 / 复核 / 读指标均仅 `super_admin` 可执行。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ..domain import PolicyError, UserContext

# 字段上限（§2.1 写入前服务端二次校验）。
MAX_DOCUMENT_ID_LENGTH = 128
MAX_TITLE_LENGTH = 300
MAX_VERSION_LENGTH = 32
MAX_SOURCE_KEY_LENGTH = 32
# source_key 稳定标识格式（沿用记忆层 rule_key / 技能层 skill_key 风格：
# 小写、字母或数字开头、可含 . _ -，最长 32）。候选值 manual / migration / api。
SOURCE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,31}$"
_SOURCE_KEY_RE = re.compile(SOURCE_KEY_PATTERN)

# 可管理 / 可读指标本租户知识文档的岗位（§2.4 / §3.2：登记 / 发布 / 改状态 / 读指标仅超级管理员）。
MANAGE_ROLES = frozenset({"super_admin"})


class KnowledgeDocStatus(StrEnum):
    """知识文档生命周期状态机（§2.2）。"""

    DRAFT = "draft"  # 已登记未发布，owner 待补 / 未发布
    PUBLISHED = "published"  # 进入检索谓词白名单（未过期）
    UNDER_REVIEW = "under_review"  # 复核中间态（人工）
    NEEDS_REVIEW = "needs_review"  # 到期待复核（事件触发，不自动归档）
    ARCHIVED = "archived"  # 终态：判废 / 归档，物理保留、从检索下线


class KnowledgeGovernanceError(ValueError):
    """知识治理操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidKnowledgeDoc(KnowledgeGovernanceError):
    """字段 / 参数校验不通过（document_id 超长、发布无 owner 等）→ 422。"""


class KnowledgeDocStateConflict(KnowledgeGovernanceError):
    """状态机冲突（非法迁移，如 draft→archived 直跳 / published→draft）→ 409。"""


class KnowledgeDocNotFound(LookupError):
    """文档不存在、跨租户，或当前操作者无权可见 → 404。

    刻意**不**继承 `KnowledgeGovernanceError`/`PolicyError`：否则会被 403/422 分支截走，
    把「看不到（避免探测存在性）」误报成「无权限」或「参数错误」（沿用记忆层 / 技能层口径）。
    """


def now() -> datetime:
    """当前 UTC 时间（可复现性：注入方也可传明确时刻）。"""
    return datetime.now(UTC)


@dataclass(frozen=True)
class KnowledgeDoc:
    """知识文档治理元数据（`workbench_knowledge_documents` 一行）。

    指 WeKnora 侧文档 id 的元数据守卫：谁拥有 / 什么状态 / 何时复核；不复制正文。
    owner 是发布闸门（§6.3）：draft 登记时可空，`published` 时服务端强制非空。
    """

    tenant_id: str
    document_id: str
    title: str
    owner_id: str
    status: KnowledgeDocStatus
    version: str
    source_key: str
    registered_by: str
    last_reviewed_at: datetime | None = None
    review_due_at: datetime | None = None
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)


# ------------------------------------------------------------ 状态机（跨层共用）

_TRANSITIONS: dict[KnowledgeDocStatus, frozenset[KnowledgeDocStatus]] = {
    KnowledgeDocStatus.DRAFT: frozenset({KnowledgeDocStatus.PUBLISHED, KnowledgeDocStatus.ARCHIVED}),
    KnowledgeDocStatus.PUBLISHED: frozenset(
        {KnowledgeDocStatus.UNDER_REVIEW, KnowledgeDocStatus.NEEDS_REVIEW, KnowledgeDocStatus.ARCHIVED}
    ),
    KnowledgeDocStatus.UNDER_REVIEW: frozenset(
        {KnowledgeDocStatus.NEEDS_REVIEW, KnowledgeDocStatus.PUBLISHED, KnowledgeDocStatus.ARCHIVED}
    ),
    KnowledgeDocStatus.NEEDS_REVIEW: frozenset(
        {KnowledgeDocStatus.PUBLISHED, KnowledgeDocStatus.ARCHIVED, KnowledgeDocStatus.UNDER_REVIEW}
    ),
    KnowledgeDocStatus.ARCHIVED: frozenset(),  # 终态：不自动回 published
}


def transition_allowed(current: KnowledgeDocStatus, target: KnowledgeDocStatus) -> bool:
    """状态机迁移判定（§2.2）。

    允许边（以「状态机主体表格」为准，规格 §2.2）：
      - draft → published（发布，owner 闸门由 service 强制）/ archived（登记后直接判废）
      - published → under_review / needs_review / archived（进入复核 / 到期扫描 / 人工归档）
      - under_review → needs_review / published / archived（复核进行中 / 复核通过 / 判废）
      - needs_review → published / archived / under_review（复核通过 / 判废 / 进入复核）
      - **any → archived（人工归档，终态，§2.2 末行「any | 归档 → archived」）**

    刻意不允许：published→draft 回退、needs_review→draft、任何 →under_review 从 draft/archived、
    archived 出发（终态）。返回布尔；`KnowledgeDocStateConflict` 的抛出由 service 层完成。

    ⚠️ 规格 §3.2 验收表把「draft→archived 直跳」列为 409，与本表「any→archived」冲突；
    本实现以**状态机主体表格**（§2.2，更核心、更好维护）为准，允许 draft→archived，
    冲突点已在交付说明明示待裁决。
    """
    return target in _TRANSITIONS.get(current, frozenset())


# ------------------------------------------------------------ 访问权限（跨层共用）


def can_manage(context: UserContext) -> bool:
    """是否可管理知识治理（登记 / 发布 / 改状态 / 复核）：仅超级管理员。"""
    return context.role in MANAGE_ROLES


def ensure_can_manage(context: UserContext) -> None:
    """管理前置判定：仅超级管理员可管理与复核；否则 403。"""
    if not can_manage(context):
        raise PolicyError("只有超级管理员可以管理知识文档治理")


def can_read_metrics(context: UserContext) -> bool:
    """是否可读 Freshness 指标（§2.4）：仅超级管理员。"""
    return context.role in MANAGE_ROLES


def ensure_can_read_metrics(context: UserContext) -> None:
    """读指标前置判定：仅超级管理员可读；否则 403。"""
    if not can_read_metrics(context):
        raise PolicyError("只有超级管理员可以阅读知识治理指标")


# ------------------------------------------------------------ 输入归一化


def normalize_document_id(value: str) -> str:
    """归一 document_id（WeKnora 侧文档 id）：非空、≤128、去除两端空白。"""
    if not isinstance(value, str):
        raise InvalidKnowledgeDoc("document_id 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise InvalidKnowledgeDoc("document_id 不能为空")
    if len(normalized) > MAX_DOCUMENT_ID_LENGTH:
        raise InvalidKnowledgeDoc(f"document_id 最长 {MAX_DOCUMENT_ID_LENGTH} 个字符")
    return normalized


def normalize_title(value: str) -> str:
    """归一标题：去除两端空白、≤300；允许为空（draft 登记可暂无标题）。"""
    if not isinstance(value, str):
        raise InvalidKnowledgeDoc("title 必须是字符串")
    normalized = value.strip()
    if len(normalized) > MAX_TITLE_LENGTH:
        raise InvalidKnowledgeDoc(f"title 最长 {MAX_TITLE_LENGTH} 个字符")
    return normalized


def normalize_owner_id(value: str) -> str:
    """归一负责人 id：去除两端空白、≤上限；允许为空（发布闸门在 service 层强制非空）。

    发布前 owner 可空、发布时必填——「发布必须指定负责人」的校验由 service 层发布闸门完成，
    这里只做长度 / 字符串归一（规格 §1.3 / §3.2）。
    """
    if not isinstance(value, str):
        raise InvalidKnowledgeDoc("owner_id 必须是字符串")
    normalized = value.strip()
    if len(normalized) > MAX_DOCUMENT_ID_LENGTH:
        raise InvalidKnowledgeDoc(f"owner_id 过长（最长 {MAX_DOCUMENT_ID_LENGTH} 个字符）")
    return normalized


def normalize_version(value: str) -> str:
    """归一版本：非空、≤32、去除两端空白（WeKnora 侧版本或治理层登记版本）。"""
    if not isinstance(value, str):
        raise InvalidKnowledgeDoc("version 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise InvalidKnowledgeDoc("version 不能为空")
    if len(normalized) > MAX_VERSION_LENGTH:
        raise InvalidKnowledgeDoc(f"version 最长 {MAX_VERSION_LENGTH} 个字符")
    return normalized


def normalize_source_key(value: str) -> str:
    """归一来源 key：非空、≤32、白名单字符（沿用 rule_key 风格，manual / migration / api）。"""
    if not isinstance(value, str):
        raise InvalidKnowledgeDoc("source_key 必须是字符串")
    normalized = value.strip().lower()
    if not normalized:
        raise InvalidKnowledgeDoc("source_key 不能为空")
    if not _SOURCE_KEY_RE.match(normalized):
        raise InvalidKnowledgeDoc(
            "source_key 只能含小写字母、数字、点、下划线与短横线，且以字母或数字开头（最长 32）"
        )
    return normalized