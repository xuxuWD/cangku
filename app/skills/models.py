"""P4 技能层的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md` §2。

两张表：技能包注册（`workbench_skills`）+ 数字员工↔技能绑定（`workbench_skill_bindings`）。
权限判定刻意放在本模块，供仓储层、服务层与接口层共用同一份实现（沿用记忆层 / 对话层手法）：
提交人 ≠ 评审人（生成者 ≠ 评审者硬约束）；`rejected` 之外的未审核技能对本人/管理员之外的
其他员工一律映射为「未找到」（404，避免探测存在性）。

状态机（§2.2）：submitted → approved → enabled → disabled（`enabled ⇄ disabled` 可回退；
`approved ⇄ submitted` 允许退回修改；`rejected` 终态）。同 skill_key 多版本并存，只
`enabled` 版本参与会话工具面展开。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ..domain import PolicyError, UserContext

# 描述 / skill_key / version 的上限（§2.1 写入前服务端二次校验）。
MAX_DESCRIPTION_LENGTH = 800
MAX_SKILL_KEY_LENGTH = 64
MAX_VERSION_LENGTH = 32
# 技能包正文体积上限（M5 裁决 2026-09-15：库内落库；默认 64 KiB，服务端校验）。
DEFAULT_CONTENT_MAX_BYTES = 64 * 1024
# 许可白名单（fail-closed，§2.1）：除此之外一律拒。
LICENSE_ALLOWLIST = ("Apache-2.0", "MIT", "BSD-3")
# 语义版本 major.minor.patch（§2.1：正则 + 递增校验）。
SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_SEMVER_RE = re.compile(SEMVER_PATTERN)

# skill_key 稳定标识格式（沿用记忆层 rule_key 风格：小写、字母或数字开头、可含 . _ -，最长 64）。
SKILL_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_SKILL_KEY_RE = re.compile(SKILL_KEY_PATTERN)

# 可审核 / 管理本租户技能包的岗位（§2.3：人工审核仅超级管理员）。
REVIEW_ROLES = frozenset({"super_admin"})
# 可提交技能包的岗位（§2.3：customer_admin 不参与技能申报，参照对话层 CONVERSING_ROLES 思路）。
SUBMIT_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})


class SkillStatus(StrEnum):
    """技能包状态机（§2.2 状态机与控制流）。"""

    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ENABLED = "enabled"
    DISABLED = "disabled"


class BindingStatus(StrEnum):
    """数字员工↔技能 绑定状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class SkillError(ValueError):
    """技能操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidSkillPackage(SkillError):
    """技能包校验不通过（字段 / 许可 / 工具键 / 描述注入等）→ 422。"""


class SkillStateConflict(SkillError):
    """状态机冲突（例如版本不递增 / 从错误状态越迁）→ 409。"""


class SkillSourceDenied(SkillError):
    """来源 key 不在部署注入白名单 → 403（§2.3，来源白名单 fail-closed）。"""


class SkillNotFound(LookupError):
    """技能包不存在、跨租户，或当前操作者无权可见 → 404。

    刻意**不**继承 `SkillError`/`PolicyError`：否则会被 403/422 分支截走，
    把「看不到（避免探测存在性）」误报成「无权限」或「参数错误」（沿用记忆层口径）。
    """


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Skill:
    """技能包声明（`workbench_skills` 一行，版本多行并存）。"""

    tenant_id: str
    skill_key: str
    version: str
    name: str
    description: str
    license: str
    allowed_tools: tuple[str, ...]
    status: SkillStatus
    source_key: str
    content_sha256: str
    owner_id: str
    reviewed_by: str | None = None
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)
    # M5 裁决（2026-09-15）：技能包正文（库内落库，031 迁移 content_body 列）。
    content_body: str = ""


@dataclass(frozen=True)
class SkillBinding:
    """数字员工 ↔ 技能 绑定（`workbench_skill_bindings` 一行）。"""

    tenant_id: str
    agent_key: str
    skill_key: str
    status: BindingStatus
    created_by: str
    created_at: datetime | None = field(default_factory=now)


# ------------------------------------------------------------ 访问权限（跨层共用）


def can_submit(context: UserContext) -> bool:
    """是否可提交技能包（任意已登录员工；customer_admin 除外）。"""
    return context.role in SUBMIT_ROLES


def ensure_can_submit(context: UserContext) -> None:
    """提交技能包前置判定：customer_admin 之外的在职员工可提交；否则 403。"""
    if not can_submit(context):
        raise PolicyError("当前岗位不能提交技能包")


def can_review(context: UserContext) -> bool:
    """是否可审核 / 管理本租户技能包（仅超级管理员）。"""
    return context.role in REVIEW_ROLES


def ensure_can_review(context: UserContext) -> None:
    """审核前置判定：仅超级管理员可审核；否则 403。"""
    if not can_review(context):
        raise PolicyError("只有超级管理员可以审核或启用技能包")


def skill_visible_to(context: UserContext, skill: Skill) -> bool:
    """技能包是否对当前操作者可见（§2.2 / §2.3）。

    本人或超级管理员始终可见；他人的包仅当已审（approved / enabled / disabled）才可见，
    submitted / rejected 一律按「未找到」处理，避免探测存在性。
    """
    if can_review(context) or skill.owner_id == context.user_id:
        return True
    return skill.status in (SkillStatus.APPROVED, SkillStatus.ENABLED, SkillStatus.DISABLED)


# ------------------------------------------------------------ 输入归一化


def parse_version(version: str) -> tuple[int, int, int]:
    """语义版本解析为整数元组，用于递增比较；非法抛 422。"""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise InvalidSkillPackage("version 必须是 major.minor.patch 语义版本号")
    return tuple(int(part) for part in version.split("."))


def normalize_skill_key(value: str) -> str:
    """归一技能键；沿用 rule_key 稳定标识风格（小写、字母或数字开头、可含 . _ -，最长 64）。"""
    if not isinstance(value, str):
        raise InvalidSkillPackage("skill_key 必须是字符串")
    normalized = value.strip().lower()
    if not normalized:
        raise InvalidSkillPackage("skill_key 不能为空")
    if not _SKILL_KEY_RE.match(normalized):
        raise InvalidSkillPackage("skill_key 只能含小写字母、数字、点、下划线与短横线，且以字母或数字开头（最长 64）")
    return normalized


def normalize_version(value: str) -> str:
    """归一版本：SEMVER 正则 + 长度；非法抛 422。"""
    if not isinstance(value, str):
        raise InvalidSkillPackage("version 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise InvalidSkillPackage("version 不能为空")
    if len(normalized) > MAX_VERSION_LENGTH:
        raise InvalidSkillPackage(f"version 最长 {MAX_VERSION_LENGTH} 个字符")
    parse_version(normalized)  # 正则校验（非法抛 422）
    return normalized


def normalize_license(value: str) -> str:
    """归一许可：必须 ∈ 白名单（Apache-2.0 / MIT / BSD-3），否则 422（§2.1 许可 fail-closed）。"""
    if not isinstance(value, str):
        raise InvalidSkillPackage("license 必须是字符串")
    normalized = value.strip()
    if normalized not in LICENSE_ALLOWLIST:
        raise InvalidSkillPackage("license 必须为受支持的许可（Apache-2.0 / MIT / BSD-3）")
    return normalized


def normalize_status(value: str | SkillStatus) -> SkillStatus:
    """归一技能包状态；非法值抛 422。"""
    try:
        return SkillStatus(value)
    except ValueError as exc:
        raise InvalidSkillPackage(f"status 只能是 {' / '.join(s.value for s in SkillStatus)}") from exc


def normalize_content_body(value: str, *, max_bytes: int = DEFAULT_CONTENT_MAX_BYTES) -> str:
    """归一技能包正文（M5 裁决：库内落库，体积上限服务端校验）。

    - 必须是非空字符串（技能包正文不得为空）；
    - UTF-8 字节数 ≤ `max_bytes`（默认 64 KiB），超限抛 422。
    """
    if not isinstance(value, str):
        raise InvalidSkillPackage("content_body 必须是字符串")
    if not value.strip():
        raise InvalidSkillPackage("content_body 不能为空")
    if len(value.encode("utf-8")) > max_bytes:
        raise InvalidSkillPackage(f"技能包正文超过体积上限（{max_bytes} 字节）")
    return value