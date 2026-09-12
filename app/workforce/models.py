"""岗位与数字员工目录的领域模型与标识规范。

口径见 `docs/superpowers/specs/2026-09-12-agent-directory-design.md`：
数字员工归属一个岗位；标识创建后不可改；停用不删除（历史任务与知识绑定仍需可解析）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ..domain import RISK_ORDER

# 标识规则：字母或数字开头，允许 . _ -，总长 1–64。
# 取值刻意收紧到小写，避免「大小写不同即两个标识」把同一身份拆成两份。
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_NAME_LENGTH = 60
MAX_DESCRIPTION_LENGTH = 200

# 数字员工配置（§7.2 / D11）
MAX_SYSTEM_PROMPT_LENGTH = 8000
AUTONOMY_LEVELS = ("approval_for_all", "approval_for_risky", "full_auto")
# 风险阈值可取值 = 风险刻度本身。刻度与序的**唯一真源在 `app/domain.py`**，此处只做派生，
# 不再另写一份字面量（两份必然漂移）。
RISK_THRESHOLDS = tuple(RISK_ORDER)

MIN_APPROVAL_TIMEOUT_MINUTES = 5
MAX_APPROVAL_TIMEOUT_MINUTES = 10080
DEFAULT_TEMPERATURE = 0.20
DEFAULT_APPROVAL_TIMEOUT_MINUTES = 60

# 自治等级的三种判定模式（段一规格 §2.2）：
# `approval_for_all` 一律审批；`approval_for_risky` 按该员工的风险阈值；`full_auto` 除 critical 外免批。
APPROVAL_FOR_ALL = "approval_for_all"
APPROVAL_FOR_RISKY = "approval_for_risky"
FULL_AUTO = "full_auto"

# 任何自治等级都不得豁免的风险档（D18）。这是**第二道独立表达**：
# 即使有人把 `full_auto` 的分支改坏，这条仍然拦住 critical。
NEVER_EXEMPT_RISK = "critical"

# 阈值取值非法时的回落档。取**最低档** = 一律审批，宁严不松（fail-closed）。
FALLBACK_RISKY_THRESHOLD = "low"


def needs_approval(autonomy_level: str, risk_level: str, risk_threshold: str) -> bool:
    """判断该自治等级 / 风险档 / 阈值配置下，是否必须人工审批。

    判定口径（段一规格 §2.2）：

    * `approval_for_all` → **一律审批**（阈值不参与）；
    * `approval_for_risky` → `risk >= risk_threshold`（阈值来自该员工配置）；
    * `full_auto` → **除 `critical` 外免批**。

    三则 fail-closed（均有测试守护）：未知自治等级 → 审批；未知风险档 → 审批；
    未知阈值 → 按最低档处理（= 一律审批）。
    """
    if autonomy_level not in AUTONOMY_LEVELS or risk_level not in RISK_ORDER:
        return True
    if autonomy_level == APPROVAL_FOR_ALL:
        return True
    if risk_level == NEVER_EXEMPT_RISK:
        return True
    if autonomy_level == FULL_AUTO:
        return False
    threshold = risk_threshold if risk_threshold in RISK_ORDER else FALLBACK_RISKY_THRESHOLD
    return RISK_ORDER[risk_level] >= RISK_ORDER[threshold]


class DirectoryError(ValueError):
    """目录操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidDirectoryKey(DirectoryError):
    pass


class InvalidDirectoryName(DirectoryError):
    pass


class DirectoryConflict(DirectoryError):
    pass


class DirectoryNotManaged(DirectoryError):
    """知识范围绑定指向了目录里不存在或已停用的标识（阶段 2 写路径闸门 → 409）。

    刻意**不**继承 `PolicyError`：否则会被知识范围接口的 `except PolicyError → 403` 截走，
    把「未纳管」误报成「无权限」。
    """


class RoleNotAvailable(DirectoryError):
    """目标岗位不存在、不属于本租户，或已停用。"""


class DirectoryNotFound(LookupError):
    pass


class InvalidAgentConfig(DirectoryError):
    """数字员工配置校验失败（含 D11 提示词防护）→ 422。

    `fields` 记录被拒的字段名，供审计记录「被拒绝的尝试」，不携带字段正文。
    """

    def __init__(self, message: str, *, fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.fields = tuple(fields)


class DirectoryStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class JobRole:
    tenant_id: str
    role_key: str
    name: str
    status: DirectoryStatus = DirectoryStatus.ACTIVE
    description: str = ""
    created_by: str = ""
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class DigitalEmployee:
    tenant_id: str
    agent_key: str
    name: str
    role_key: str
    status: DirectoryStatus = DirectoryStatus.ACTIVE
    description: str = ""
    created_by: str = ""
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)
    # 配置字段（§7.2 / D11）；默认值即「fail-closed」：用默认模型、无提示词、无工具
    system_prompt: str = ""
    model_key: str = ""
    temperature: float = DEFAULT_TEMPERATURE
    tool_allowlist: tuple[str, ...] = ()
    memory_policy: dict[str, object] = field(default_factory=dict)
    autonomy_level: str = "approval_for_risky"
    risk_threshold: str = "high"
    approval_timeout_minutes: int = DEFAULT_APPROVAL_TIMEOUT_MINUTES
    daily_budget_cents: int = 0


def normalize_key(value: str) -> str:
    """去空白并转小写后校验标识。"""
    if not isinstance(value, str):
        raise InvalidDirectoryKey("岗位或数字员工标识必须是字符串")
    normalized = value.strip().lower()
    if not KEY_PATTERN.match(normalized):
        raise InvalidDirectoryKey(
            "标识只能包含小写字母、数字、点、下划线与短横线，且必须以字母或数字开头（最长 64 个字符）"
        )
    return normalized


def normalize_name(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidDirectoryName("中文名必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise InvalidDirectoryName("中文名不能为空")
    if len(normalized) > MAX_NAME_LENGTH:
        raise InvalidDirectoryName(f"中文名最长 {MAX_NAME_LENGTH} 个字符")
    return normalized


def normalize_description(value: str) -> str:
    if not isinstance(value, str):
        raise DirectoryError("描述必须是字符串")
    normalized = value.strip()
    if len(normalized) > MAX_DESCRIPTION_LENGTH:
        raise DirectoryError(f"描述最长 {MAX_DESCRIPTION_LENGTH} 个字符")
    return normalized


def normalize_status(value: str | DirectoryStatus) -> DirectoryStatus:
    try:
        return DirectoryStatus(value)
    except ValueError as exc:
        raise DirectoryError("状态只能是 active 或 disabled") from exc
