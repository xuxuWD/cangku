"""P4 技能层（技能包注册表 + 数字员工绑定 + 来源白名单）。

口径见 `docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md`。
本阶段先实现领域核心（模型 / 校验器 / 仓储 / 服务），路由、配置接线与审计动作码由主代理负责。
"""

from .models import (
    BindingStatus,
    InvalidSkillPackage,
    LICENSE_ALLOWLIST,
    MAX_DESCRIPTION_LENGTH,
    MAX_SKILL_KEY_LENGTH,
    MAX_VERSION_LENGTH,
    REVIEW_ROLES,
    SEMVER_PATTERN,
    Skill,
    SkillBinding,
    SkillError,
    SkillNotFound,
    SkillSourceDenied,
    SkillStateConflict,
    SkillStatus,
    SUBMIT_ROLES,
    can_review,
    can_submit,
    ensure_can_review,
    ensure_can_submit,
    normalize_license,
    normalize_skill_key,
    normalize_status,
    normalize_version,
    parse_version,
    skill_visible_to,
)
from .service import SkillService
from .store import InMemorySkillStore, PostgresSkillStore, SkillStore
from .validator import SkillPackageSpec, SkillPackageValidator

__all__ = [
    "BindingStatus",
    "InvalidSkillPackage",
    "LICENSE_ALLOWLIST",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_SKILL_KEY_LENGTH",
    "MAX_VERSION_LENGTH",
    "REVIEW_ROLES",
    "SEMVER_PATTERN",
    "Skill",
    "SkillBinding",
    "SkillError",
    "SkillNotFound",
    "SkillSourceDenied",
    "SkillStateConflict",
    "SkillStatus",
    "SUBMIT_ROLES",
    "can_review",
    "can_submit",
    "ensure_can_review",
    "ensure_can_submit",
    "normalize_license",
    "normalize_skill_key",
    "normalize_status",
    "normalize_version",
    "parse_version",
    "skill_visible_to",
    "SkillService",
    "SkillStore",
    "InMemorySkillStore",
    "PostgresSkillStore",
    "SkillPackageSpec",
    "SkillPackageValidator",
]