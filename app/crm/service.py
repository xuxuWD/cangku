"""CRM 服务层（P5a）：主数据 / 线索转化 / 商机阶段机 / 活动 / 报价 / 合同 / 回款 / 目标 / 字段定义。

依据：`docs/superpowers/specs/2026-09-17-crm-p5a-design.md`（已评审）§2.3 / §2.4 / §2.8 / §2.9 / §2.10。

- 权限与归属判定**统一走 `models.py`**（读他人 ⇒ 404；角色级不允许 ⇒ 403 由 PolicyError 承担）。
- 状态迁移走 `store` 的条件更新（首写获胜）；非法迁移 ⇒ `CrmStateConflict`（409）。
- 审计只记标识与受控枚举（`AuditAction.CRM_*` + `ALLOWED_DETAIL_KEYS`），**不落正文 / PII / 敏感字段值**。
- 金额一律整数分；报价行由服务端重算（`pricing` 纯函数）。
- 本模块**不含**任何 provider 代码（发票 / 签署为二期，§1.3）。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime

from ..audit.models import AuditAction
from ..domain import PolicyError, UserContext
from . import pricing
from .followup import INSUFFICIENT_SUMMARY, MockFollowupGenerator, sanitize_output
from .metrics import compute_metrics
from .scoring import compute_health
from .models import (
    AGENT_ACTIVITY_KINDS,
    CONTRACT_TRANSITIONS,
    CRM_ROLES,
    MAX_CONTENT_LENGTH,
    MAX_LINES_PER_QUOTE,
    MAX_NAME_LENGTH,
    MAX_TEXT_LENGTH,
    OPPORTUNITY_TRANSITIONS,
    QUOTE_TRANSITIONS,
    SENSITIVE_FIELDS,
    Account,
    AccountSource,
    Activity,
    ActivityKind,
    ActivityStatus,
    Contact,
    Contract,
    ContractStatus,
    CreatedByKind,
    CrmNotFound,
    CrmStateConflict,
    FieldDef,
    Insight,
    InvalidCrm,
    Lead,
    LeadStatus,
    Opportunity,
    Quote,
    QuoteStatus,
    StageEvent,
    Target,
    ensure_can_manage,
    ensure_can_view,
    ensure_crm_role,
    ensure_manage_role,
    can_view_all,
    new_account_id,
    new_activity_id,
    new_contact_id,
    new_contract_id,
    new_insight_id,
    new_lead_id,
    new_opportunity_id,
    new_quote_id,
    new_stage_event_id,
    new_target_id,
    normalize_amount_cents,
    normalize_optional_date,
    normalize_positive_amount_cents,
    normalize_text,
    now,
    validate_custom_fields,
)


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_no(prefix: str, count: int) -> str:
    return f"{prefix}{count + 1:04d}"


class CrmService:
    """CRM 业务服务（store 为 `InMemoryCrmStore` 或 `PostgresCrmStore`）。"""

    def __init__(self, store, *, audit=None, followup_generator=None) -> None:
        self.store = store
        self.audit = audit
        self.followup_generator = followup_generator or MockFollowupGenerator()
        self._followup_model_key = getattr(self.followup_generator, "model_key", None) or "mock"

    # ------------------------------------------------------------ 内部工具

    def _record(
        self, action: AuditAction, context: UserContext, entity: str, entity_id: str, detail: dict
    ) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type=f"crm_{entity}",
            target_id=entity_id,
            detail=detail,
        )

    def _field_defs(self, tenant_id: str, object_key: str) -> dict[str, FieldDef]:
        return {d.field_key: d for d in self.store.list_field_defs(tenant_id, object_key)}

    def _validate_fields(self, tenant_id: str, object_key: str, values: dict | None) -> dict:
        return validate_custom_fields(object_key, values, self._field_defs(tenant_id, object_key))

    def _require_account(self, context: UserContext, account_id: str) -> Account:
        account = self.store.get_account(context.tenant_id, account_id)
        if account is None:
            raise CrmNotFound(account_id)
        ensure_can_view(context, account.owner_id)
        return account

    def _require_opportunity(self, context: UserContext, opportunity_id: str) -> Opportunity:
        opportunity = self.store.get_opportunity(context.tenant_id, opportunity_id)
        if opportunity is None:
            raise CrmNotFound(opportunity_id)
        ensure_can_view(context, opportunity.owner_id)
        return opportunity

    # ------------------------------------------------------------ 客户

    def create_account(
        self,
        context: UserContext,
        *,
        name: str,
        industry: str = "",
        owner_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> Account:
        ensure_crm_role(context)
        target_owner = owner_id or context.user_id
        if target_owner != context.user_id:
            ensure_can_manage(context, target_owner)
        account = Account(
            tenant_id=context.tenant_id,
            account_id=new_account_id(),
            name=normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="客户名称"),
            industry=normalize_text(industry, max_length=MAX_NAME_LENGTH, field_name="行业"),
            source="manual",
            owner_id=target_owner,
            custom_fields=self._validate_fields(context.tenant_id, "account", custom_fields),
        )
        self.store.add_account(account)
        self._record(
            AuditAction.CRM_ACCOUNT_CREATED, context, "account", account.account_id,
            {"account_id": account.account_id},
        )
        return account

    def get_account(self, context: UserContext, account_id: str) -> Account:
        ensure_crm_role(context)
        return self._require_account(context, account_id)

    def update_account(
        self,
        context: UserContext,
        account_id: str,
        *,
        name: str | None = None,
        industry: str | None = None,
        status: str | None = None,
        custom_fields: dict | None = None,
    ) -> Account:
        account = self._require_account(context, account_id)
        ensure_can_manage(context, account.owner_id)
        if name is not None:
            account.name = normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="客户名称")
        if industry is not None:
            account.industry = normalize_text(industry, max_length=MAX_NAME_LENGTH, field_name="行业")
        if status is not None:
            if status not in ("active", "inactive"):
                raise InvalidCrm("客户状态取值不合法")
            account.status = status
        if custom_fields is not None:
            account.custom_fields = self._validate_fields(context.tenant_id, "account", custom_fields)
        account.updated_at = now()
        self.store.update_account(account)
        return account

    def list_accounts(
        self,
        context: UserContext,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Account], int]:
        ensure_crm_role(context)
        owner_filter = owner_id
        if not can_view_all(context):
            if owner_id is not None and owner_id != context.user_id:
                raise CrmNotFound(owner_id)
            owner_filter = context.user_id
        return self.store.list_accounts(
            context.tenant_id, owner_id=owner_filter, status=status, limit=limit, offset=offset
        )

    # ------------------------------------------------------------ 联系人（敏感字段：默认掩码由接口层出口控制）

    def create_contact(
        self,
        context: UserContext,
        *,
        name: str,
        account_id: str | None = None,
        title: str = "",
        phone: str = "",
        email: str = "",
        is_primary: bool = False,
        birthday: date | None = None,
        custom_fields: dict | None = None,
    ) -> Contact:
        ensure_crm_role(context)
        if account_id is not None:
            account = self._require_account(context, account_id)
            ensure_can_manage(context, account.owner_id)
        if not isinstance(is_primary, bool):
            raise InvalidCrm("is_primary 必须为布尔值")
        contact = Contact(
            tenant_id=context.tenant_id,
            contact_id=new_contact_id(),
            account_id=account_id,
            name=normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="联系人姓名"),
            title=normalize_text(title, max_length=MAX_NAME_LENGTH, field_name="称谓"),
            phone=normalize_text(phone, max_length=64, field_name="电话"),
            email=normalize_text(email, max_length=254, field_name="邮箱"),
            is_primary=is_primary,
            birthday=normalize_optional_date(birthday, field_name="生日"),
            owner_id=context.user_id,
            custom_fields=self._validate_fields(context.tenant_id, "contact", custom_fields),
        )
        self.store.add_contact(contact)
        self._record(
            AuditAction.CRM_CONTACT_CREATED, context, "contact", contact.contact_id,
            {"contact_id": contact.contact_id, "account_id": account_id or ""},
        )
        return contact

    def get_contact(self, context: UserContext, contact_id: str) -> Contact:
        ensure_crm_role(context)
        contact = self.store.get_contact(context.tenant_id, contact_id)
        if contact is None:
            raise CrmNotFound(contact_id)
        ensure_can_view(context, contact.owner_id)
        return contact

    def update_contact(
        self,
        context: UserContext,
        contact_id: str,
        *,
        name: str | None = None,
        title: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        is_primary: bool | None = None,
        birthday: date | None = None,
        custom_fields: dict | None = None,
    ) -> Contact:
        contact = self.get_contact(context, contact_id)
        ensure_can_manage(context, contact.owner_id)
        if name is not None:
            contact.name = normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="联系人姓名")
        if title is not None:
            contact.title = normalize_text(title, max_length=MAX_NAME_LENGTH, field_name="称谓")
        if phone is not None:
            contact.phone = normalize_text(phone, max_length=64, field_name="电话")
        if email is not None:
            contact.email = normalize_text(email, max_length=254, field_name="邮箱")
        if is_primary is not None:
            if not isinstance(is_primary, bool):
                raise InvalidCrm("is_primary 必须为布尔值")
            contact.is_primary = is_primary
        if birthday is not None:
            contact.birthday = normalize_optional_date(birthday, field_name="生日")
        if custom_fields is not None:
            contact.custom_fields = self._validate_fields(context.tenant_id, "contact", custom_fields)
        contact.updated_at = now()
        self.store.update_contact(contact)
        return contact

    def list_contacts(
        self, context: UserContext, *, account_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[Contact], int]:
        ensure_crm_role(context)
        if account_id is not None:
            self._require_account(context, account_id)
        items, total = self.store.list_contacts(
            context.tenant_id, account_id=account_id, limit=limit, offset=offset
        )
        if not can_view_all(context):
            items = [item for item in items if item.owner_id == context.user_id]
            total = len(items)
        return items, total

    # ------------------------------------------------------------ 线索

    def create_lead(
        self,
        context: UserContext,
        *,
        name: str,
        company: str = "",
        phone: str = "",
        email: str = "",
        source: str = "manual",
        custom_fields: dict | None = None,
    ) -> Lead:
        ensure_crm_role(context)
        lead = Lead(
            tenant_id=context.tenant_id,
            lead_id=new_lead_id(),
            name=normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="线索名称"),
            company=normalize_text(company, max_length=MAX_NAME_LENGTH, field_name="公司"),
            phone=normalize_text(phone, max_length=64, field_name="电话"),
            email=normalize_text(email, max_length=254, field_name="邮箱"),
            source=normalize_text(source, max_length=64, field_name="来源") or "manual",
            owner_id=context.user_id,
            custom_fields=self._validate_fields(context.tenant_id, "lead", custom_fields),
        )
        self.store.add_lead(lead)
        return lead

    def get_lead(self, context: UserContext, lead_id: str) -> Lead:
        ensure_crm_role(context)
        lead = self.store.get_lead(context.tenant_id, lead_id)
        if lead is None:
            raise CrmNotFound(lead_id)
        ensure_can_view(context, lead.owner_id)
        return lead

    def list_leads(
        self,
        context: UserContext,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        ensure_crm_role(context)
        owner_filter = owner_id
        if not can_view_all(context):
            if owner_id is not None and owner_id != context.user_id:
                raise CrmNotFound(owner_id)
            owner_filter = context.user_id
        return self.store.list_leads(
            context.tenant_id, owner_id=owner_filter, status=status, limit=limit, offset=offset
        )

    def convert_lead(
        self,
        context: UserContext,
        lead_id: str,
        *,
        create_opportunity: bool = False,
        opportunity_name: str | None = None,
        account_name: str | None = None,
    ) -> tuple[Account, Contact, Opportunity | None]:
        """线索转化（单事务）：`Lead → Account + Contact（+ 可选 Opportunity）`。"""
        lead = self.get_lead(context, lead_id)
        ensure_can_manage(context, lead.owner_id)
        if lead.status != LeadStatus.OPEN:
            raise CrmStateConflict("线索已转化或已丢弃，不能重复转化")
        if not isinstance(create_opportunity, bool):
            raise InvalidCrm("create_opportunity 必须为布尔值")

        account = Account(
            tenant_id=context.tenant_id,
            account_id=new_account_id(),
            name=normalize_text(
                account_name or lead.company or lead.name,
                max_length=MAX_NAME_LENGTH,
                required=True,
                field_name="客户名称",
            ),
            source="lead_converted",
            owner_id=lead.owner_id,
        )
        contact = Contact(
            tenant_id=context.tenant_id,
            contact_id=new_contact_id(),
            account_id=account.account_id,
            name=lead.name,
            phone=lead.phone,
            email=lead.email,
            is_primary=True,
            owner_id=lead.owner_id,
        )
        opportunity: Opportunity | None = None
        if create_opportunity:
            opportunity = Opportunity(
                tenant_id=context.tenant_id,
                opportunity_id=new_opportunity_id(),
                account_id=account.account_id,
                name=normalize_text(
                    opportunity_name or f"{account.name} 商机",
                    max_length=MAX_NAME_LENGTH,
                    required=True,
                    field_name="商机名称",
                ),
                owner_id=lead.owner_id,
            )
        lead.status = "converted"
        lead.converted_account_id = account.account_id
        lead.converted_contact_id = contact.contact_id
        lead.converted_opportunity_id = opportunity.opportunity_id if opportunity else None
        lead.updated_at = now()

        self.store.convert_lead_atomic(lead, account, contact, opportunity)
        if opportunity is not None:
            self.store.append_stage_event(
                StageEvent(
                    tenant_id=context.tenant_id,
                    event_id=new_stage_event_id(),
                    opportunity_id=opportunity.opportunity_id,
                    from_stage=None,
                    to_stage=opportunity.stage,
                    amount_cents=opportunity.amount_cents,
                    actor_id=context.user_id,
                )
            )
        self._record(
            AuditAction.CRM_LEAD_CONVERTED, context, "lead", lead.lead_id,
            {
                "lead_id": lead.lead_id,
                "account_id": account.account_id,
                "create_opportunity": create_opportunity,
            },
        )
        return account, contact, opportunity

    # ------------------------------------------------------------ 商机

    def create_opportunity(
        self,
        context: UserContext,
        *,
        account_id: str,
        name: str,
        amount_cents: int = 0,
        expected_close: date | None = None,
        custom_fields: dict | None = None,
    ) -> Opportunity:
        ensure_crm_role(context)
        account = self._require_account(context, account_id)
        ensure_can_manage(context, account.owner_id)
        opportunity = Opportunity(
            tenant_id=context.tenant_id,
            opportunity_id=new_opportunity_id(),
            account_id=account_id,
            name=normalize_text(name, max_length=MAX_NAME_LENGTH, required=True, field_name="商机名称"),
            amount_cents=normalize_amount_cents(amount_cents),
            expected_close=normalize_optional_date(expected_close, field_name="预计成交日"),
            owner_id=account.owner_id,
            custom_fields=self._validate_fields(context.tenant_id, "opportunity", custom_fields),
        )
        self.store.add_opportunity(opportunity)
        self.store.append_stage_event(
            StageEvent(
                tenant_id=context.tenant_id,
                event_id=new_stage_event_id(),
                opportunity_id=opportunity.opportunity_id,
                from_stage=None,
                to_stage=opportunity.stage,
                amount_cents=opportunity.amount_cents,
                actor_id=context.user_id,
            )
        )
        self._record(
            AuditAction.CRM_OPPORTUNITY_CREATED, context, "opportunity", opportunity.opportunity_id,
            {"opportunity_id": opportunity.opportunity_id, "account_id": account_id},
        )
        return opportunity

    def get_opportunity(self, context: UserContext, opportunity_id: str) -> Opportunity:
        ensure_crm_role(context)
        return self._require_opportunity(context, opportunity_id)

    def list_opportunities(
        self,
        context: UserContext,
        *,
        owner_id: str | None = None,
        account_id: str | None = None,
        stage: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Opportunity], int]:
        ensure_crm_role(context)
        owner_filter = owner_id
        if not can_view_all(context):
            if owner_id is not None and owner_id != context.user_id:
                raise CrmNotFound(owner_id)
            owner_filter = context.user_id
        return self.store.list_opportunities(
            context.tenant_id, owner_id=owner_filter, account_id=account_id, stage=stage,
            limit=limit, offset=offset,
        )

    def change_opportunity_stage(
        self, context: UserContext, opportunity_id: str, *, to_stage: str
    ) -> Opportunity:
        """商机阶段迁移（白名单 + 首写获胜 + 阶段事件 append）。"""
        opportunity = self._require_opportunity(context, opportunity_id)
        ensure_can_manage(context, opportunity.owner_id)
        previous_stage = str(opportunity.stage)
        allowed = OPPORTUNITY_TRANSITIONS.get(previous_stage, frozenset())
        if to_stage not in allowed:
            raise CrmStateConflict(f"不允许的阶段迁移：{previous_stage} → {to_stage}")
        at = now()
        amount_cents = opportunity.amount_cents
        ok = self.store.transition_opportunity_stage(
            context.tenant_id, opportunity_id, from_stage=previous_stage, to_stage=to_stage, at=at
        )
        if not ok:
            # 并发：另一方已先迁移（不静默覆盖）。
            raise CrmStateConflict("商机阶段已被其他操作变更，请刷新后重试")
        self.store.append_stage_event(
            StageEvent(
                tenant_id=context.tenant_id,
                event_id=new_stage_event_id(),
                opportunity_id=opportunity_id,
                from_stage=previous_stage,
                to_stage=to_stage,
                amount_cents=amount_cents,
                actor_id=context.user_id,
                occurred_at=at,
            )
        )
        self._record(
            AuditAction.CRM_OPPORTUNITY_STAGE_CHANGED, context, "opportunity", opportunity_id,
            {"opportunity_id": opportunity_id, "from_stage": previous_stage, "to_stage": to_stage},
        )
        updated = self.store.get_opportunity(context.tenant_id, opportunity_id)
        return updated if updated is not None else opportunity

    def list_stage_events(self, context: UserContext, opportunity_id: str) -> list[StageEvent]:
        self._require_opportunity(context, opportunity_id)
        return self.store.list_stage_events(context.tenant_id, opportunity_id)

    # ------------------------------------------------------------ 活动

    def log_activity(
        self,
        context: UserContext,
        *,
        kind: str,
        subject: str = "",
        content: str = "",
        account_id: str | None = None,
        contact_id: str | None = None,
        opportunity_id: str | None = None,
        status: str | None = None,
        due_at: datetime | None = None,
        created_by_kind: str = CreatedByKind.HUMAN,
    ) -> Activity:
        ensure_crm_role(context)
        if kind not in {item.value for item in ActivityKind}:
            raise InvalidCrm("活动类型不合法")
        if created_by_kind == CreatedByKind.AGENT and kind not in AGENT_ACTIVITY_KINDS:
            raise InvalidCrm("数字员工只能登记 call / meeting / email / note 类活动")
        if created_by_kind not in (CreatedByKind.HUMAN, CreatedByKind.AGENT):
            raise InvalidCrm("created_by_kind 取值不合法")
        if account_id is not None:
            account = self._require_account(context, account_id)
            ensure_can_manage(context, account.owner_id)
        if contact_id is not None:
            contact = self.get_contact(context, contact_id)
            ensure_can_manage(context, contact.owner_id)
        if opportunity_id is not None:
            opportunity = self._require_opportunity(context, opportunity_id)
            ensure_can_manage(context, opportunity.owner_id)

        resolved_status = status or ("planned" if kind == "task" else "done")
        if resolved_status not in {item.value for item in ActivityStatus}:
            raise InvalidCrm("活动状态不合法")
        if kind == "task":
            if resolved_status == "planned" and due_at is None:
                raise InvalidCrm("task 类活动必须提供到期时间")
        elif due_at is not None and not isinstance(due_at, datetime):
            raise InvalidCrm("到期时间格式不合法")

        activity = Activity(
            tenant_id=context.tenant_id,
            activity_id=new_activity_id(),
            kind=kind,
            subject=normalize_text(subject, max_length=MAX_NAME_LENGTH, field_name="主题"),
            content=normalize_text(content, max_length=MAX_CONTENT_LENGTH, field_name="正文"),
            account_id=account_id,
            contact_id=contact_id,
            opportunity_id=opportunity_id,
            owner_id=context.user_id,
            status=str(resolved_status),
            due_at=due_at,
            created_by_kind=str(created_by_kind),
        )
        self.store.add_activity(activity)
        self._record(
            AuditAction.CRM_ACTIVITY_LOGGED, context, "activity", activity.activity_id,
            {"activity_id": activity.activity_id, "kind": kind, "account_id": account_id or ""},
        )
        return activity

    def list_activities(
        self,
        context: UserContext,
        *,
        account_id: str | None = None,
        contact_id: str | None = None,
        opportunity_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Activity], int]:
        ensure_crm_role(context)
        if account_id is not None:
            self._require_account(context, account_id)
        if contact_id is not None:
            self.get_contact(context, contact_id)
        if opportunity_id is not None:
            self._require_opportunity(context, opportunity_id)
        items, total = self.store.list_activities(
            context.tenant_id, account_id=account_id, contact_id=contact_id,
            opportunity_id=opportunity_id, limit=limit, offset=offset,
        )
        if not can_view_all(context):
            items = [item for item in items if item.owner_id == context.user_id]
            total = len(items)
        return items, total

    # ------------------------------------------------------------ 报价

    def create_quote(
        self,
        context: UserContext,
        *,
        account_id: str,
        lines: list[dict],
        opportunity_id: str | None = None,
        valid_until: date | None = None,
    ) -> Quote:
        ensure_crm_role(context)
        account = self._require_account(context, account_id)
        ensure_can_manage(context, account.owner_id)
        if opportunity_id is not None:
            opportunity = self._require_opportunity(context, opportunity_id)
            if opportunity.account_id != account_id:
                raise InvalidCrm("商机不属于该客户")
        quote_id = new_quote_id()
        built = pricing.build_lines(context.tenant_id, quote_id, lines)
        subtotal, tax, total = pricing.compute_totals(built)
        prefix = f"Q-{now().strftime('%Y%m')}-"
        quote = Quote(
            tenant_id=context.tenant_id,
            quote_id=quote_id,
            account_id=account_id,
            opportunity_id=opportunity_id,
            quote_no=_next_no(prefix, self.store.count_quotes_with_prefix(context.tenant_id, prefix)),
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=total,
            valid_until=normalize_optional_date(valid_until, field_name="有效期"),
            owner_id=account.owner_id,
        )
        self.store.add_quote(quote, built)
        self._record(
            AuditAction.CRM_QUOTE_CREATED, context, "quote", quote.quote_id,
            {"quote_id": quote.quote_id, "account_id": account_id},
        )
        return quote

    def get_quote(self, context: UserContext, quote_id: str) -> Quote:
        ensure_crm_role(context)
        quote = self.store.get_quote(context.tenant_id, quote_id)
        if quote is None:
            raise CrmNotFound(quote_id)
        ensure_can_view(context, quote.owner_id)
        return quote

    def list_quotes(
        self,
        context: UserContext,
        *,
        account_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Quote], int]:
        ensure_crm_role(context)
        owner_filter: str | None = None
        if not can_view_all(context):
            owner_filter = context.user_id
        return self.store.list_quotes(
            context.tenant_id, owner_id=owner_filter, account_id=account_id, status=status,
            limit=limit, offset=offset,
        )

    def replace_quote_lines(self, context: UserContext, quote_id: str, *, lines: list[dict]) -> Quote:
        """draft 态整单全量替换（事务内删旧插新 + 重算金额）；非 draft ⇒ 409（confirmed 冻结）。"""
        quote = self.get_quote(context, quote_id)
        ensure_can_manage(context, quote.owner_id)
        if quote.status != QuoteStatus.DRAFT:
            raise CrmStateConflict("已确认（或已终止）的报价不能修改行")
        built = pricing.build_lines(context.tenant_id, quote_id, lines)
        subtotal, tax, total = pricing.compute_totals(built)
        quote.subtotal_cents = subtotal
        quote.tax_cents = tax
        quote.total_cents = total
        quote.updated_at = now()
        self.store.update_quote(quote, built)
        return quote

    def confirm_quote(self, context: UserContext, quote_id: str) -> Quote:
        quote = self.get_quote(context, quote_id)
        ensure_can_manage(context, quote.owner_id)
        if quote.status != QuoteStatus.DRAFT:
            raise CrmStateConflict("仅草稿报价可确认")
        lines = self.store.list_quote_lines(context.tenant_id, quote_id)
        if not lines or quote.total_cents <= 0:
            raise InvalidCrm("报价确认需要至少一行且金额大于 0")
        at = now()
        ok = self.store.transition_quote_status(
            context.tenant_id, quote_id, from_status="draft", to_status="confirmed", at=at
        )
        if not ok:
            raise CrmStateConflict("报价状态已被其他操作变更，请刷新后重试")
        self._record(
            AuditAction.CRM_QUOTE_CONFIRMED, context, "quote", quote_id,
            {"quote_id": quote_id, "amount_cents": quote.total_cents},
        )
        updated = self.store.get_quote(context.tenant_id, quote_id)
        return updated if updated is not None else quote

    def void_quote(self, context: UserContext, quote_id: str) -> Quote:
        quote = self.get_quote(context, quote_id)
        ensure_can_manage(context, quote.owner_id)
        if quote.status not in (QuoteStatus.DRAFT, QuoteStatus.CONFIRMED):
            raise CrmStateConflict("仅草稿或已确认报价可作废")
        at = now()
        ok = self.store.transition_quote_status(
            context.tenant_id, quote_id, from_status=str(quote.status), to_status="voided", at=at
        )
        if not ok:
            raise CrmStateConflict("报价状态已被其他操作变更，请刷新后重试")
        self._record(
            AuditAction.CRM_QUOTE_VOIDED, context, "quote", quote_id, {"quote_id": quote_id}
        )
        updated = self.store.get_quote(context.tenant_id, quote_id)
        return updated if updated is not None else quote

    def convert_quote_to_contract(
        self,
        context: UserContext,
        quote_id: str,
        *,
        title: str | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
    ) -> Contract:
        """报价转合同（单事务）：仅 `confirmed` 可转；金额取报价 total；quote 置 `converted`。"""
        quote = self.get_quote(context, quote_id)
        ensure_can_manage(context, quote.owner_id)
        if quote.status != QuoteStatus.CONFIRMED:
            raise CrmStateConflict("仅已确认报价可转合同")
        contract_id = new_contract_id()
        prefix = f"C-{now().strftime('%Y%m')}-"
        contract = Contract(
            tenant_id=context.tenant_id,
            contract_id=contract_id,
            account_id=quote.account_id,
            quote_id=quote_id,
            opportunity_id=quote.opportunity_id,
            contract_no=_next_no(prefix, self.store.count_contracts_with_prefix(context.tenant_id, prefix)),
            title=normalize_text(
                title or f"合同（报价 {quote.quote_no}）",
                max_length=MAX_NAME_LENGTH,
                required=True,
                field_name="合同标题",
            ),
            amount_cents=quote.total_cents,
            starts_on=normalize_optional_date(starts_on, field_name="开始日期"),
            ends_on=normalize_optional_date(ends_on, field_name="结束日期"),
            owner_id=quote.owner_id,
        )
        quote.status = "converted"
        quote.converted_contract_id = contract_id
        quote.updated_at = now()
        self.store.convert_quote_atomic(quote, contract)
        self._record(
            AuditAction.CRM_QUOTE_CONVERTED, context, "quote", quote_id,
            {"quote_id": quote_id, "contract_id": contract_id},
        )
        self._record(
            AuditAction.CRM_CONTRACT_CREATED, context, "contract", contract_id,
            {"contract_id": contract_id, "account_id": contract.account_id},
        )
        return contract

    # ------------------------------------------------------------ 合同

    def create_contract(
        self,
        context: UserContext,
        *,
        account_id: str,
        title: str,
        amount_cents: int = 0,
        opportunity_id: str | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
        document_object_key: str = "",
    ) -> Contract:
        ensure_crm_role(context)
        account = self._require_account(context, account_id)
        ensure_can_manage(context, account.owner_id)
        if opportunity_id is not None:
            opportunity = self._require_opportunity(context, opportunity_id)
            if opportunity.account_id != account_id:
                raise InvalidCrm("商机不属于该客户")
        prefix = f"C-{now().strftime('%Y%m')}-"
        contract = Contract(
            tenant_id=context.tenant_id,
            contract_id=new_contract_id(),
            account_id=account_id,
            opportunity_id=opportunity_id,
            contract_no=_next_no(prefix, self.store.count_contracts_with_prefix(context.tenant_id, prefix)),
            title=normalize_text(title, max_length=MAX_NAME_LENGTH, required=True, field_name="合同标题"),
            amount_cents=normalize_amount_cents(amount_cents),
            starts_on=normalize_optional_date(starts_on, field_name="开始日期"),
            ends_on=normalize_optional_date(ends_on, field_name="结束日期"),
            document_object_key=normalize_text(
                document_object_key, max_length=512, field_name="附件引用"
            ),
            owner_id=account.owner_id,
        )
        self.store.add_contract(contract)
        self._record(
            AuditAction.CRM_CONTRACT_CREATED, context, "contract", contract.contract_id,
            {"contract_id": contract.contract_id, "account_id": account_id},
        )
        return contract

    def get_contract(self, context: UserContext, contract_id: str) -> Contract:
        ensure_crm_role(context)
        contract = self.store.get_contract(context.tenant_id, contract_id)
        if contract is None:
            raise CrmNotFound(contract_id)
        ensure_can_view(context, contract.owner_id)
        return contract

    def list_contracts(
        self,
        context: UserContext,
        *,
        account_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contract], int]:
        ensure_crm_role(context)
        owner_filter: str | None = None
        if not can_view_all(context):
            owner_filter = context.user_id
        return self.store.list_contracts(
            context.tenant_id, owner_id=owner_filter, account_id=account_id, status=status,
            limit=limit, offset=offset,
        )

    def _transition_contract(self, context: UserContext, contract_id: str, to_status: str) -> Contract:
        contract = self.get_contract(context, contract_id)
        ensure_can_manage(context, contract.owner_id)
        allowed = CONTRACT_TRANSITIONS.get(contract.status, frozenset())
        if to_status not in allowed:
            raise CrmStateConflict(f"不允许的合同状态迁移：{contract.status} → {to_status}")
        return contract

    def submit_contract_for_sign(self, context: UserContext, contract_id: str) -> Contract:
        contract = self._transition_contract(context, contract_id, ContractStatus.PENDING_SIGN)
        contract.status = "pending_sign"
        contract.updated_at = now()
        self.store.update_contract(contract)
        return contract

    def register_signature(
        self,
        context: UserContext,
        contract_id: str,
        *,
        signed_at: datetime,
        document_object_key: str | None = None,
    ) -> Contract:
        """人工登记签署结果（本段无 provider；`signed` = 线下签署登记，不承诺法律效力）。"""
        if not isinstance(signed_at, datetime):
            raise InvalidCrm("签署日期格式不合法")
        contract = self._transition_contract(context, contract_id, ContractStatus.SIGNED)
        contract.status = "signed"
        contract.signed_at = signed_at
        if document_object_key is not None:
            contract.document_object_key = normalize_text(
                document_object_key, max_length=512, field_name="附件引用"
            )
        contract.updated_at = now()
        self.store.update_contract(contract)
        self._record(
            AuditAction.CRM_CONTRACT_SIGNED, context, "contract", contract_id, {"contract_id": contract_id}
        )
        return contract

    def register_payment(
        self, context: UserContext, contract_id: str, *, amount_cents: int
    ) -> Contract:
        """回款人工登记（原子增量；超 amount_cents ⇒ 409）。"""
        contract = self.get_contract(context, contract_id)
        ensure_can_manage(context, contract.owner_id)
        if contract.status != ContractStatus.SIGNED:
            raise CrmStateConflict("仅已签署合同可登记回款")
        delta = normalize_positive_amount_cents(amount_cents, field_name="回款金额")
        ok = self.store.increment_contract_paid(
            context.tenant_id, contract_id, delta_cents=delta
        )
        if not ok:
            raise CrmStateConflict("回款金额超过合同金额（或合同已被变更），请核对后重试")
        self._record(
            AuditAction.CRM_CONTRACT_PAYMENT_REGISTERED, context, "contract", contract_id,
            {"contract_id": contract_id, "amount_cents": delta},
        )
        updated = self.store.get_contract(context.tenant_id, contract_id)
        return updated if updated is not None else contract

    def void_contract(self, context: UserContext, contract_id: str) -> Contract:
        contract = self._transition_contract(context, contract_id, ContractStatus.VOIDED)
        contract.status = "voided"
        contract.updated_at = now()
        self.store.update_contract(contract)
        self._record(
            AuditAction.CRM_CONTRACT_VOIDED, context, "contract", contract_id, {"contract_id": contract_id}
        )
        return contract

    # ------------------------------------------------------------ 目标

    def set_target(
        self,
        context: UserContext,
        *,
        owner_id: str,
        period_month: date,
        amount_target_cents: int = 0,
        count_target: int = 0,
    ) -> Target:
        """目标写入（§2.9：限 `ceo` / `super_admin`；其余 ⇒ 403）。"""
        ensure_crm_role(context)
        ensure_manage_role(context)
        if not isinstance(period_month, date):
            raise InvalidCrm("目标月份格式不合法")
        if isinstance(count_target, bool) or not isinstance(count_target, int) or count_target < 0:
            raise InvalidCrm("目标单数必须为非负整数")
        target = Target(
            tenant_id=context.tenant_id,
            target_id=new_target_id(),
            owner_id=normalize_text(owner_id, max_length=64, required=True, field_name="目标归属人"),
            period_month=_month_start(period_month),
            amount_target_cents=normalize_amount_cents(amount_target_cents, field_name="目标金额"),
            count_target=count_target,
        )
        return self.store.upsert_target(target)

    def list_targets(
        self,
        context: UserContext,
        *,
        period_month: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Target], int]:
        ensure_crm_role(context)
        owner_filter: str | None = None
        if not can_view_all(context):
            owner_filter = context.user_id
        return self.store.list_targets(
            context.tenant_id, owner_id=owner_filter, period_month=period_month, limit=limit, offset=offset
        )

    # ------------------------------------------------------------ 自定义字段元数据

    def upsert_field_def(
        self,
        context: UserContext,
        *,
        object_key: str,
        field_key: str,
        label: str,
        field_type: str,
        required: bool = False,
        options: list[str] | None = None,
    ) -> FieldDef:
        """字段定义写入（管理动作，与目标写入同档：`ceo` / `super_admin`；其余 ⇒ 403）。

        §1.3-9：本段不做字段管理 UI，走 API；前端只读取渲染。
        """
        ensure_crm_role(context)
        ensure_manage_role(context)
        from .models import FIELD_OBJECTS, FIELD_TYPES, normalize_bool, normalize_field_key

        if object_key not in FIELD_OBJECTS:
            raise InvalidCrm("对象键不合法")
        if field_type not in FIELD_TYPES:
            raise InvalidCrm("字段类型不合法")
        clean_options: list[str] = []
        if field_type == "select":
            raw_options = options or []
            if not raw_options:
                raise InvalidCrm("select 类型必须提供受控选项")
            clean_options = [normalize_text(item, max_length=MAX_NAME_LENGTH, required=True, field_name="选项") for item in raw_options]
        definition = FieldDef(
            tenant_id=context.tenant_id,
            object_key=object_key,
            field_key=normalize_field_key(field_key),
            label=normalize_text(label, max_length=MAX_NAME_LENGTH, required=True, field_name="字段标签"),
            field_type=field_type,
            required=normalize_bool(required, field_name="必填标记"),
            options=tuple(clean_options),
        )
        return self.store.upsert_field_def(definition)

    def list_field_defs(self, context: UserContext, *, object_key: str) -> list[FieldDef]:
        ensure_crm_role(context)
        return self.store.list_field_defs(context.tenant_id, object_key)

    # ------------------------------------------------------------ 敏感字段揭示（专用出口 + 审计，§2.2）

    def reveal_sensitive(
        self, context: UserContext, *, entity: str, entity_id: str, field: str
    ) -> str:
        """返回单字段明文（**数据范围内** + 审计 `crm.sensitive.revealed`，不落字段值）。

        实体仅支持 `contact` / `lead`；字段限定在 `SENSITIVE_FIELDS` 集合内。
        """
        ensure_crm_role(context)
        allowed_fields = SENSITIVE_FIELDS.get(entity)
        if not allowed_fields:
            raise InvalidCrm("实体不支持敏感字段揭示")
        if field not in allowed_fields:
            raise InvalidCrm("字段不在敏感字段集合内")
        if entity == "contact":
            record = self.get_contact(context, entity_id)
            detail_key = "contact_id"
        else:
            record = self.get_lead(context, entity_id)
            detail_key = "lead_id"
        self._record(
            AuditAction.CRM_SENSITIVE_REVEALED, context, entity, entity_id,
            {detail_key: entity_id, "field_name": field},
        )
        return getattr(record, field, "")

    # ------------------------------------------------------------ 健康度重算（周期任务用，§2.11）

    def recompute_health_for_tenant(self, tenant_id: str) -> int:
        """逐租户重算全部客户健康度（幂等）；返回重算客户数并写一条**汇总**审计。

        批量收集（账户 / 商机 / 活动 / 合同 / 联系人）避免 N+1；**无租户数据时返回 0 且不写审计**
        （不伪造扫描结果，沿用既有周期任务口径）。worker 任务 `crm-health-recompute` 调用。
        """
        accounts = self.store.list_accounts_bulk(tenant_id)
        if not accounts:
            return 0
        account_ids = [account.account_id for account in accounts]
        opportunities = self.store.list_opportunities_for_accounts(tenant_id, account_ids)
        activities = self.store.list_activities_for_accounts(tenant_id, account_ids)
        contracts = self.store.list_contracts_for_accounts(tenant_id, account_ids)
        contacts = self.store.list_contacts_for_accounts(tenant_id, account_ids)

        opps_by_account: dict[str, list] = {}
        for opportunity in opportunities:
            opps_by_account.setdefault(opportunity.account_id, []).append(opportunity)
        acts_by_account: dict[str, list] = {}
        for activity in activities:
            if activity.account_id:
                acts_by_account.setdefault(activity.account_id, []).append(activity)
        contracts_by_account: dict[str, list] = {}
        for contract in contracts:
            contracts_by_account.setdefault(contract.account_id, []).append(contract)
        contact_counts = Counter(contact.account_id for contact in contacts if contact.account_id)

        computed_at = now()
        for account in accounts:
            result = compute_health(
                activities=acts_by_account.get(account.account_id, []),
                opportunities=opps_by_account.get(account.account_id, []),
                contact_count=contact_counts.get(account.account_id, 0),
                contracts=contracts_by_account.get(account.account_id, []),
                now=computed_at,
            )
            self.store.update_account_health(
                tenant_id, account.account_id, score=result.score, band=result.band,
                computed_at=computed_at,
            )
        if self.audit is not None:
            self.audit.record(
                AuditAction.CRM_HEALTH_RECOMPUTED,
                tenant_id=tenant_id,
                actor_id=None,
                target_type="crm_health",
                target_id=tenant_id,
                detail={"recomputed_count": len(accounts)},
            )
        return len(accounts)

    # ------------------------------------------------------------ 多维度进度指标（§2.6）

    def progress_summary(self, context: UserContext, *, scope: str = "me") -> dict:
        """多维度进度指标；`scope=all` 需管理角色（`department_lead` / `ceo` / `super_admin`）。"""
        ensure_crm_role(context)
        if scope not in ("me", "all"):
            raise InvalidCrm("scope 取值不合法")
        if scope == "all" and not can_view_all(context):
            raise PolicyError("当前岗位无权查看全量进度指标")
        owner_filter = context.user_id if scope == "me" else None
        accounts = self.store.list_accounts_bulk(context.tenant_id, owner_id=owner_filter)
        account_ids = [account.account_id for account in accounts]
        opportunities = self.store.list_opportunities_for_accounts(context.tenant_id, account_ids)
        stage_events = self.store.list_stage_events_for_opportunities(
            context.tenant_id, [opportunity.opportunity_id for opportunity in opportunities]
        )
        contracts = self.store.list_contracts_for_accounts(context.tenant_id, account_ids)

        month = _month_start(now().date())
        if scope == "me":
            target = self.store.get_target(context.tenant_id, context.user_id, month)
        else:
            rows, _ = self.store.list_targets(context.tenant_id, period_month=month, limit=200, offset=0)
            target = Target(
                tenant_id=context.tenant_id,
                target_id="aggregate",
                owner_id="*",
                period_month=month,
                amount_target_cents=sum(row.amount_target_cents for row in rows),
                count_target=sum(row.count_target for row in rows),
            ) if rows else None

        return compute_metrics(
            opportunities=opportunities,
            stage_events=stage_events,
            contracts=contracts,
            accounts=accounts,
            target=target,
        ).as_dict()

    # ------------------------------------------------------------ 跟进计划生成器（§2.7）

    def _ref_belongs(self, context: UserContext, account_id: str, kind: str, identifier: str) -> bool:
        """证据 / 目标引用校验：**存在 + 属本租户 + 归属链指向该客户**（§2.7 防幻觉闸门）。"""
        if kind == "account":
            return identifier == account_id
        if kind == "activity":
            record = self.store.get_activity(context.tenant_id, identifier)
            return record is not None and record.account_id == account_id
        if kind == "opportunity":
            record = self.store.get_opportunity(context.tenant_id, identifier)
            return record is not None and record.account_id == account_id
        if kind == "contract":
            record = self.store.get_contract(context.tenant_id, identifier)
            return record is not None and record.account_id == account_id
        if kind == "contact":
            record = self.store.get_contact(context.tenant_id, identifier)
            return record is not None and record.account_id == account_id
        return False

    def _validate_actions(
        self, context: UserContext, account_id: str, actions: list[dict]
    ) -> tuple[list[dict], list[str], list[dict]]:
        """对结构层已清洗的 actions 做引用真实性校验；无效引用丢弃并记 `dropped_refs`。"""
        valid_actions: list[dict] = []
        evidence_refs: list[str] = []
        dropped: list[dict] = []
        for action in actions:
            target_kind, _, target_id = action["target_ref"].partition(":")
            if not self._ref_belongs(context, account_id, target_kind, target_id):
                dropped.append({"reason": "invalid_target_ref", "raw": action["target_ref"]})
                continue
            kept: list[str] = []
            for ref in action["evidence_refs"]:
                kind, _, identifier = ref.partition(":")
                if self._ref_belongs(context, account_id, kind, identifier):
                    kept.append(ref)
                else:
                    dropped.append({"reason": "invalid_evidence_ref", "raw": ref})
            valid_actions.append({**action, "evidence_refs": kept})
            evidence_refs.extend(kept)
        return valid_actions, evidence_refs, dropped

    def _build_summary(
        self,
        account: Account,
        *,
        opportunities: list,
        activities: list,
        contracts: list,
        contact_count: int,
    ) -> dict:
        """构造输入摘要（脱敏口径）：只含结构化字段与**引用 id**，不含联系人姓名 / 电话 / 邮箱。"""
        health = compute_health(
            activities=activities, opportunities=opportunities, contact_count=contact_count, contracts=contracts
        )
        reference = now()
        ordered_activities = sorted(activities, key=lambda item: item.occurred_at, reverse=True)[:20]
        return {
            "account": {"id": account.account_id, "name": account.name, "industry": account.industry, "status": account.status},
            "health": {"score": health.score, "band": health.band, "parts": health.parts},
            "contact_count": contact_count,
            "activities": [
                {
                    "id": activity.activity_id,
                    "kind": activity.kind,
                    "subject": activity.subject[:200],
                    "occurred_at": activity.occurred_at.isoformat(),
                }
                for activity in ordered_activities
            ],
            "opportunities": [
                {
                    "id": opportunity.opportunity_id,
                    "name": opportunity.name,
                    "stage": opportunity.stage,
                    "amount_cents": opportunity.amount_cents,
                    "age_days": max(0, (reference - opportunity.stage_entered_at).days),
                }
                for opportunity in opportunities
            ],
            "contracts": [
                {
                    "id": contract.contract_id,
                    "status": contract.status,
                    "amount_cents": contract.amount_cents,
                    "paid_cents": contract.paid_cents,
                    "ends_on": contract.ends_on.isoformat() if contract.ends_on else None,
                }
                for contract in contracts
            ],
        }

    def generate_followup_plan(self, context: UserContext, account_id: str) -> Insight:
        """生成跟进计划（人工触发）：输入脱敏 → 模型网关 → 结构校验 → 引用校验 → 落库 + 审计。

        - 网关失败 ⇒ 抛 `FollowupPlanError`（接口层 502；**不落库、不降级**）。
        - 全部建议被丢弃 ⇒ 输出**服务端生成**的「依据不足」文案（`insufficient_evidence=true`）。
        - **建议永不直接执行**：本方法不提供任何采纳 / 自动执行路径。
        """
        account = self._require_account(context, account_id)
        opportunities = self.store.list_opportunities_for_accounts(context.tenant_id, [account_id])
        activities = self.store.list_activities_for_accounts(context.tenant_id, [account_id])
        contracts = self.store.list_contracts_for_accounts(context.tenant_id, [account_id])
        contacts = self.store.list_contacts_for_accounts(context.tenant_id, [account_id])

        summary = self._build_summary(
            account,
            opportunities=opportunities,
            activities=activities,
            contracts=contracts,
            contact_count=len(contacts),
        )
        raw = self.followup_generator.generate(summary)
        cleaned, structural_drops = sanitize_output(raw)
        actions, evidence_refs, reference_drops = self._validate_actions(context, account_id, cleaned["actions"])
        dropped_refs = structural_drops + reference_drops

        if not actions:
            content = {"actions": [], "summary": INSUFFICIENT_SUMMARY, "insufficient_evidence": True}
            status = "insufficient"
        else:
            content = {"actions": actions, "summary": cleaned["summary"]}
            status = "ok"

        digest = hashlib.sha256(json.dumps(summary, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        insight = Insight(
            tenant_id=context.tenant_id,
            insight_id=new_insight_id(),
            account_id=account_id,
            kind="followup_plan",
            input_digest=digest,
            content=content,
            evidence_refs=evidence_refs,
            dropped_refs=dropped_refs,
            model_key=self._followup_model_key,
            generated_by=context.user_id,
        )
        self.store.add_insight(insight)
        self._record(
            AuditAction.CRM_INSIGHT_GENERATED, context, "insight", insight.insight_id,
            {
                "account_id": account_id,
                "insight_id": insight.insight_id,
                "model_key": self._followup_model_key,
                "status": status,
            },
        )
        return insight

    def list_insights(
        self, context: UserContext, account_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Insight], int]:
        account = self._require_account(context, account_id)
        ensure_can_view(context, account.owner_id)
        return self.store.list_insights(context.tenant_id, account_id=account_id, limit=limit, offset=offset)