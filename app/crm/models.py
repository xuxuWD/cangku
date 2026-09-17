"""CRM（P5a）领域模型、状态机白名单、错误类型与权限判定。

依据：`docs/superpowers/specs/2026-09-17-crm-p5a-design.md`（已评审，2026-09-17）§2.1 / §2.3 / §2.9。

权限判定刻意放在本模块，供仓储层、服务层与接口层共用同一份实现（沿用记忆层 / 对话层手法）：
- 读他人 / 跨租户对象一律映射为「未找到」（404），避免探测存在性；
- 角色级不允许的操作（`scope=all`、目标写入、`customer_admin` 进模块）→ 403（PolicyError）；
- 非法状态迁移 / 已冻结单据修改 → 409。

金额一律整数分（BIGINT）；税率万分比整数；数量 NUMERIC(12,3)（Decimal）。
敏感字段集合（`SENSITIVE_FIELDS`）为**代码级常量 + 单一来源**：新增敏感字段必须显式登记并走评审。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from ..domain import PolicyError, UserContext

# ------------------------------------------------------------ 常量

MAX_LIMIT = 200
MAX_NAME_LENGTH = 200
MAX_TEXT_LENGTH = 2000
MAX_CONTENT_LENGTH = 8000
MAX_LINES_PER_QUOTE = 200

# 健康度四维权重与分档阈值（§2.5；模块级常量，计算函数接受 weights 参数以便单测替换）。
HEALTH_WEIGHTS: dict[str, float] = {
    "engagement": 0.35,
    "pipeline": 0.30,
    "relationship": 0.20,
    "commercial": 0.15,
}
HEALTH_BAND_GREEN = 80
HEALTH_BAND_YELLOW = 60

# 续约窗口（天；§2.11 与 §2.6 共用）。
RENEWAL_WINDOW_DAYS = 90

# 敏感字段集合（§2.2）：键 = 对象键，值 = 字段名集合。**代码级常量 + 单一来源**。
SENSITIVE_FIELDS: dict[str, frozenset[str]] = {
    "contact": frozenset({"phone", "email"}),
    "lead": frozenset({"phone", "email"}),
}

# 可查看 / 管理本租户内全部 CRM 数据的岗位（§2.9：`department_lead` 沿用既有同档先例——
# `app/repository.py` 的 `%s IN ('department_lead','ceo','super_admin')`；平台无部门维度数据）。
VIEW_ALL_ROLES = frozenset({"department_lead", "ceo", "super_admin"})
# 目标写入 / `scope=all` 等管理动作的允许岗位（§2.9）。
MANAGE_ROLES = frozenset({"ceo", "super_admin"})
# 允许进入 CRM 模块的岗位（`customer_admin` 不进本模块，§2.9 待裁决 6 已按推荐定）。
CRM_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})

# 单号格式（服务端生成；租户内唯一）。
_QUOTE_NO_PATTERN = re.compile(r"^Q-\d{6}-\d{4,}$")
_CONTRACT_NO_PATTERN = re.compile(r"^C-\d{6}-\d{4,}$")

# 自定义字段键格式（与迁移 035 的 CHECK 一致）。
_FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FIELD_TYPES = frozenset({"text", "number", "date", "select", "bool"})
FIELD_OBJECTS = frozenset({"account", "contact", "lead", "opportunity", "activity"})


# ------------------------------------------------------------ 枚举


class AccountStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AccountSource(StrEnum):
    MANUAL = "manual"
    LEAD_CONVERTED = "lead_converted"
    API = "api"


class LeadStatus(StrEnum):
    OPEN = "open"
    CONVERTED = "converted"
    DROPPED = "dropped"


class CrmStage(StrEnum):
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CONVERTED = "converted"
    VOIDED = "voided"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    PENDING_SIGN = "pending_sign"
    SIGNED = "signed"
    VOIDED = "voided"
    EXPIRED = "expired"


class ActivityKind(StrEnum):
    CALL = "call"
    MEETING = "meeting"
    EMAIL = "email"
    NOTE = "note"
    TASK = "task"


class ActivityStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    CANCELLED = "cancelled"


class CreatedByKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class HealthBand(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class InsightKind(StrEnum):
    FOLLOWUP_PLAN = "followup_plan"
    ACCOUNT_REVIEW = "account_review"


# ------------------------------------------------------------ 状态机白名单（唯一事实源，§2.3 / §2.4）

OPPORTUNITY_TRANSITIONS: dict[str, frozenset[str]] = {
    CrmStage.QUALIFICATION: frozenset({CrmStage.PROPOSAL, CrmStage.LOST}),
    CrmStage.PROPOSAL: frozenset({CrmStage.NEGOTIATION, CrmStage.LOST}),
    CrmStage.NEGOTIATION: frozenset({CrmStage.WON, CrmStage.LOST}),
    CrmStage.WON: frozenset(),
    CrmStage.LOST: frozenset(),
}

QUOTE_TRANSITIONS: dict[str, frozenset[str]] = {
    QuoteStatus.DRAFT: frozenset({QuoteStatus.CONFIRMED, QuoteStatus.VOIDED}),
    QuoteStatus.CONFIRMED: frozenset({QuoteStatus.CONVERTED, QuoteStatus.VOIDED}),
    QuoteStatus.CONVERTED: frozenset(),
    QuoteStatus.VOIDED: frozenset(),
}

CONTRACT_TRANSITIONS: dict[str, frozenset[str]] = {
    ContractStatus.DRAFT: frozenset({ContractStatus.PENDING_SIGN, ContractStatus.VOIDED}),
    ContractStatus.PENDING_SIGN: frozenset({ContractStatus.SIGNED, ContractStatus.VOIDED}),
    ContractStatus.SIGNED: frozenset({ContractStatus.VOIDED, ContractStatus.EXPIRED}),
    ContractStatus.VOIDED: frozenset(),
    ContractStatus.EXPIRED: frozenset(),
}

# 数字员工写活动允许的 kind（§2.8：禁 `task` 类——不产生人类待办）。
AGENT_ACTIVITY_KINDS = frozenset({ActivityKind.CALL, ActivityKind.MEETING, ActivityKind.EMAIL, ActivityKind.NOTE})


# ------------------------------------------------------------ 错误类型


class CrmError(ValueError):
    """CRM 操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidCrm(CrmError):
    """输入不合法（长度 / 格式 / 类型 / 范围）→ 422。"""


class CrmStateConflict(CrmError):
    """状态冲突（非法迁移 / 冻结单据修改 / 重复转化 / 回款超限）→ 409。"""


class CrmNotFound(LookupError):
    """对象不存在、跨租户，或不属于当前操作者 → 404。

    刻意**不**继承 `CrmError`：否则会被 422 分支截走，把「看不到（避免探测存在性）」
    误报成「参数错误」（沿用记忆层口径）。
    """


# ------------------------------------------------------------ 工具函数


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"crm-{prefix}-{uuid4().hex[:12]}"


def new_account_id() -> str:
    return new_id("acc")


def new_contact_id() -> str:
    return new_id("con")


def new_lead_id() -> str:
    return new_id("lead")


def new_opportunity_id() -> str:
    return new_id("op")


def new_stage_event_id() -> str:
    return new_id("ev")


def new_activity_id() -> str:
    return new_id("act")


def new_quote_id() -> str:
    return new_id("q")


def new_contract_id() -> str:
    return new_id("c")


def new_insight_id() -> str:
    return new_id("ins")


def new_target_id() -> str:
    return new_id("tgt")


def normalize_text(value: str | None, *, max_length: int, required: bool = False, field_name: str = "字段") -> str:
    text = (value or "").strip()
    if required and not text:
        raise InvalidCrm(f"{field_name}不能为空")
    if len(text) > max_length:
        raise InvalidCrm(f"{field_name}长度超过上限 {max_length}")
    return text


def normalize_optional_date(value: date | None, *, field_name: str = "日期") -> date | None:
    if value is None:
        return None
    if not isinstance(value, date):
        raise InvalidCrm(f"{field_name}格式不合法")
    return value


def normalize_amount_cents(value: int | None, *, field_name: str = "金额") -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidCrm(f"{field_name}必须为整数分")
    if value < 0:
        raise InvalidCrm(f"{field_name}不能为负")
    return int(value)


def normalize_positive_amount_cents(value: int | None, *, field_name: str = "金额") -> int:
    amount = normalize_amount_cents(value, field_name=field_name)
    if amount <= 0:
        raise InvalidCrm(f"{field_name}必须大于 0")
    return amount


def normalize_field_key(value: str) -> str:
    key = (value or "").strip()
    if not _FIELD_KEY_PATTERN.match(key):
        raise InvalidCrm("自定义字段键格式不合法")
    return key


def normalize_bool(value: object, *, field_name: str = "布尔值") -> bool:
    if not isinstance(value, bool):
        raise InvalidCrm(f"{field_name}必须为布尔值")
    return value


# ------------------------------------------------------------ 权限判定（单一来源）


def can_view_all(context: UserContext) -> bool:
    """是否可读本租户全部 CRM 数据（§2.9：`department_lead` / `ceo` / `super_admin`）。"""
    return context.role in VIEW_ALL_ROLES


def ensure_crm_role(context: UserContext) -> None:
    """进入 CRM 模块的岗位校验（`customer_admin` → 403，§2.9）。"""
    if context.role not in CRM_ROLES:
        raise PolicyError("当前岗位不可访问 CRM 模块")


def ensure_can_view(context: UserContext, owner_id: str) -> None:
    """读归属校验：非特权岗位只能读本人负责对象；否则 404（不泄露存在性）。"""
    if can_view_all(context) or owner_id == context.user_id:
        return
    raise CrmNotFound(owner_id)


def ensure_can_manage(context: UserContext, owner_id: str) -> None:
    """写归属校验：非特权岗位只能写本人负责对象；否则 404（不泄露存在性）。"""
    if can_view_all(context) or owner_id == context.user_id:
        return
    raise CrmNotFound(owner_id)


def ensure_manage_role(context: UserContext) -> None:
    """管理动作（目标写入 / `scope=all`）角色校验；否则 403。"""
    if context.role not in MANAGE_ROLES:
        raise PolicyError("当前岗位无权执行该管理动作")


# ------------------------------------------------------------ 数据类（与迁移 035 逐列对应）


@dataclass
class Account:
    tenant_id: str
    account_id: str
    name: str
    industry: str = ""
    source: str = "manual"
    owner_id: str = ""
    status: str = "active"
    custom_fields: dict = field(default_factory=dict)
    health_score: int | None = None
    health_band: str | None = None
    health_computed_at: datetime | None = None
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass
class Contact:
    tenant_id: str
    contact_id: str
    name: str
    account_id: str | None = None
    title: str = ""
    phone: str = ""
    email: str = ""
    is_primary: bool = False
    birthday: date | None = None
    owner_id: str = ""
    custom_fields: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass
class Lead:
    tenant_id: str
    lead_id: str
    name: str
    company: str = ""
    phone: str = ""
    email: str = ""
    source: str = "manual"
    owner_id: str = ""
    status: str = "open"
    converted_account_id: str | None = None
    converted_contact_id: str | None = None
    converted_opportunity_id: str | None = None
    custom_fields: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass
class Opportunity:
    tenant_id: str
    opportunity_id: str
    account_id: str
    name: str
    stage: str = "qualification"
    amount_cents: int = 0
    expected_close: date | None = None
    owner_id: str = ""
    stage_entered_at: datetime = field(default_factory=now)
    closed_at: datetime | None = None
    custom_fields: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class StageEvent:
    tenant_id: str
    event_id: str
    opportunity_id: str
    from_stage: str | None
    to_stage: str
    amount_cents: int
    actor_id: str
    occurred_at: datetime = field(default_factory=now)


@dataclass
class Activity:
    tenant_id: str
    activity_id: str
    kind: str
    subject: str = ""
    content: str = ""
    account_id: str | None = None
    contact_id: str | None = None
    opportunity_id: str | None = None
    owner_id: str = ""
    status: str = "done"
    due_at: datetime | None = None
    occurred_at: datetime = field(default_factory=now)
    reminded_on: date | None = None
    created_by_kind: str = "human"
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass
class Quote:
    tenant_id: str
    quote_id: str
    account_id: str
    quote_no: str
    opportunity_id: str | None = None
    status: str = "draft"
    subtotal_cents: int = 0
    tax_cents: int = 0
    total_cents: int = 0
    valid_until: date | None = None
    confirmed_at: datetime | None = None
    converted_contract_id: str | None = None
    owner_id: str = ""
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class QuoteLine:
    tenant_id: str
    quote_id: str
    line_no: int
    description: str
    qty: str  # Decimal 的字符串形式（跨层传输保持精确；落库为 NUMERIC(12,3)）
    unit_price_cents: int
    tax_rate_bp: int
    line_subtotal_cents: int
    line_tax_cents: int


@dataclass
class Contract:
    tenant_id: str
    contract_id: str
    account_id: str
    contract_no: str
    title: str
    quote_id: str | None = None
    opportunity_id: str | None = None
    status: str = "draft"
    amount_cents: int = 0
    paid_cents: int = 0
    starts_on: date | None = None
    ends_on: date | None = None
    document_object_key: str = ""
    signed_at: datetime | None = None
    owner_id: str = ""
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class Insight:
    tenant_id: str
    insight_id: str
    account_id: str
    kind: str
    input_digest: str
    content: dict
    evidence_refs: list
    dropped_refs: list
    model_key: str
    generated_by: str
    created_at: datetime = field(default_factory=now)


@dataclass
class Target:
    tenant_id: str
    target_id: str
    owner_id: str
    period_month: date
    amount_target_cents: int = 0
    count_target: int = 0
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class FieldDef:
    tenant_id: str
    object_key: str
    field_key: str
    label: str
    field_type: str
    required: bool = False
    options: tuple = ()
    active: bool = True
    created_at: datetime = field(default_factory=now)


# ------------------------------------------------------------ 自定义字段校验（白名单，§2.1）


def validate_custom_fields(
    object_key: str, values: dict | None, defs: dict[str, FieldDef]
) -> dict:
    """按 `field_defs` 校验自定义字段（未知键拒绝、类型匹配、select 取值受控）。

    `defs` 为「field_key -> FieldDef」的本租户定义集；未定义键一律拒绝（白名单）。
    """
    payload = dict(values or {})
    if not payload:
        return {}
    result: dict[str, object] = {}
    for key, raw in payload.items():
        field_key = normalize_field_key(str(key))
        definition = defs.get(field_key)
        if definition is None or not definition.active:
            raise InvalidCrm(f"自定义字段未定义或已停用：{field_key}")
        if definition.field_type == "text":
            if not isinstance(raw, str):
                raise InvalidCrm(f"自定义字段 {field_key} 必须为文本")
            result[field_key] = raw[:MAX_TEXT_LENGTH]
        elif definition.field_type == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise InvalidCrm(f"自定义字段 {field_key} 必须为数字")
            result[field_key] = raw
        elif definition.field_type == "bool":
            result[field_key] = normalize_bool(raw, field_name=f"自定义字段 {field_key}")
        elif definition.field_type == "date":
            if not isinstance(raw, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
                raise InvalidCrm(f"自定义字段 {field_key} 必须为 YYYY-MM-DD 日期")
            result[field_key] = raw
        elif definition.field_type == "select":
            if not isinstance(raw, str) or raw not in tuple(definition.options):
                raise InvalidCrm(f"自定义字段 {field_key} 取值不在受控选项内")
            result[field_key] = raw
        else:  # pragma: no cover - 迁移 CHECK 已兜底，防御性分支
            raise InvalidCrm(f"自定义字段 {field_key} 类型不受支持")
    return result