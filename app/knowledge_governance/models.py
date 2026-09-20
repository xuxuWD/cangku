"""知识治理层的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md` §2。

核心是「知识文档生命周期 + 检索谓词守卫」：一张注册表 `workbench_knowledge_documents`
（迁移 032），登记 Who 拥有 / 同步到什么状态 / 何时复核 / 过期即从检索谓词下线；
WeKnora 仍是检索唯一事实源（D1），本表只是**文档级元数据守卫**，不复制正文、不重建索引。

状态机（§2.2）：`draft → published → needs_review → published/archived`（`published →
under_review → needs_review → published/archived` 为可选中间态）；`archived` 终态。
发布闸门（§1.2 C / §3.2）在 service 层强制 owner 非空；本模块只做长度 / 字符串归一。
权限判定刻意放在本模块，供仓储 / 服务 / 接口层共用（沿用记忆层 / 技能层手法）：
登记 / 检索 / 发布 / 复核 / 治理读分四档，**逐行对齐 `permission-matrix.md` §3**（见下方 `*_ROLES` 常量注释）。
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

# 可检索 / 可登记 / 可管理本租户知识文档的岗位（**逐行对齐 `permission-matrix.md` §3 的「知识」四行**）。
#
# 2026-09-19（P0 缺口修复，用户裁决「全量对齐矩阵」）：本模块原先把检索 / 登记 / 管理 / 治理读**全部**
# 收在 `super_admin` 之下，与矩阵 §3 冲突。矩阵是权限口径的**唯一权威**且自定「实现与本文冲突时以本文为准」
# ⇒ 按矩阵拆成四档。**不改矩阵口径**，只让实现回到矩阵。
#
# | 资源 · 动作 | employee | department_lead | ceo | super_admin | customer_admin |
# | --- | --- | --- | --- | --- | --- |
# | 知识：检索 | ⚠️ 按绑定 | ⚠️ 按绑定 | ⚠️ 按绑定 | ✅ | ❌ |
# | 知识：上传/登记 | ✅ | ✅ | ✅ | ✅ | ❌ |
# | 知识：发布 / 归档 / 复核 | ❌ | ❌ | ✅ | ✅ | ❌ |
# | 知识：授权绑定 | ❌ | ❌ | ✅ | ✅ | ❌ |
#
# **「按绑定」的落地**（见 `ensure_can_search` 与 `app/main.py` 的自限判定）：非管理角色的 `role_key`
# 必须等于**自身角色**，且不开放 `agent_key` 通道 —— 否则员工可在请求体里填任意岗位键读到别人的知识范围
# （矩阵 §8 第 4 条「不静默返回他人文档」+ 宪法「数据归属」红线）。
SEARCH_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})
REGISTER_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})
# 发布 / 归档 / 复核 + 授权绑定 + 治理读（文档列表 / 指标 / 可检索清单）同属管理面。
GOVERNANCE_ROLES = frozenset({"ceo", "super_admin"})
# 兼容既有引用（发布 / 归档 / 复核 / 到期扫描 / 治理读均为管理面）。
MANAGE_ROLES = GOVERNANCE_ROLES


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
    """状态机冲突（非法迁移，如 published→draft 回退 / archived 终态出发）→ 409。"""


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

    允许边（§2.2；口径裁定 2026-09-15：末行「any → 归档」为准）：
      - draft → published（发布，owner 闸门由 service 强制）/ archived（登记后直接判废）
      - published → under_review / needs_review / archived（进入复核 / 到期扫描 / 人工归档）
      - under_review → needs_review / published / archived（复核进行中 / 复核通过 / 判废）
      - needs_review → published / archived / under_review（复核通过 / 判废 / 进入复核）
      - **any → archived（人工归档，终态，§2.2 末行「any | 归档 → archived」）**

    刻意不允许：published→draft 回退、needs_review→draft、任何 →under_review 从 draft/archived、
    archived 出发（终态）。返回布尔；`KnowledgeDocStateConflict` 的抛出由 service 层完成。
    """
    return target in _TRANSITIONS.get(current, frozenset())


# ------------------------------------------------------------ 访问权限（跨层共用）


def can_search(context: UserContext) -> bool:
    """是否可发起知识检索（矩阵 §3 检索行：四个角色 ✅/⚠️，`customer_admin` ❌）。"""
    return context.role in SEARCH_ROLES


def ensure_can_search(context: UserContext) -> None:
    """检索入口前置判定；否则 403。

    ⚠️ 本判定**只管"能不能进检索入口"**；非管理角色的**范围自限**（`role_key` 必须等于自身角色、
    不开放 `agent_key`）在接口层完成 —— 因为那需要读请求体，而本层刻意不依赖请求模型。
    """
    if not can_search(context):
        raise PolicyError("当前角色不能检索知识文档")


def can_register(context: UserContext) -> bool:
    """是否可登记知识文档（矩阵 §3 登记行：四个角色 ✅，`customer_admin` ❌）。"""
    return context.role in REGISTER_ROLES


def ensure_can_register(context: UserContext) -> None:
    """登记前置判定；否则 403。"""
    if not can_register(context):
        raise PolicyError("当前角色不能登记知识文档")


def can_manage(context: UserContext) -> bool:
    """是否可管理知识治理（发布 / 归档 / 复核 / 到期扫描 / 治理读 / 授权绑定）。

    矩阵 §3：仅 `ceo` 与 `super_admin`。
    """
    return context.role in MANAGE_ROLES


def ensure_can_manage(context: UserContext) -> None:
    """管理前置判定：仅企业负责人或超级管理员可管理；否则 403。"""
    if not can_manage(context):
        raise PolicyError("只有企业负责人或超级管理员可以管理知识文档治理")


def can_read_metrics(context: UserContext) -> bool:
    """是否可读 Freshness 指标（§2.4）：治理读，与 `can_manage` 同档（ceo + super_admin）。"""
    return context.role in MANAGE_ROLES


def ensure_can_read_metrics(context: UserContext) -> None:
    """读指标前置判定：仅企业负责人或超级管理员可读；否则 403。"""
    if not can_read_metrics(context):
        raise PolicyError("只有企业负责人或超级管理员可以阅读知识治理指标")


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