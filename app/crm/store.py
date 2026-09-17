"""CRM 仓储（内存实现）。PG 实现见 `store_postgres.py`，两者方法集一致。

- 所有查询严格带 `tenant_id`（不依赖调用方传入的租户条件）。
- 软删除：业务对象读写默认过滤 `deleted_at`；append-only（阶段事件 / 智能化记录）永不过滤。
- 权限（归属 / 岗位）在**服务层**统一判定（单一来源 `models.py`）；仓储只做数据存取
  （沿用记忆层 store 的定位口径）。
- 内存实现用 `RLock` 保护（多线程测试 / development 运行时）。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from threading import RLock

from .models import (
    Account,
    Activity,
    Contact,
    Contract,
    FieldDef,
    Insight,
    Lead,
    Opportunity,
    Quote,
    QuoteLine,
    StageEvent,
    Target,
)


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), 200))


class InMemoryCrmStore:
    """内存 CRM 仓储（development / 测试用）。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._accounts: dict[tuple[str, str], Account] = {}
        self._contacts: dict[tuple[str, str], Contact] = {}
        self._leads: dict[tuple[str, str], Lead] = {}
        self._opportunities: dict[tuple[str, str], Opportunity] = {}
        self._stage_events: list[StageEvent] = []
        self._activities: dict[tuple[str, str], Activity] = {}
        self._quotes: dict[tuple[str, str], Quote] = {}
        self._quote_lines: dict[tuple[str, str], list[QuoteLine]] = {}
        self._contracts: dict[tuple[str, str], Contract] = {}
        self._insights: list[Insight] = []
        self._targets: dict[tuple[str, str], Target] = {}
        self._field_defs: dict[tuple[str, str, str], FieldDef] = {}

    # ------------------------------------------------------------ 账户

    def add_account(self, account: Account) -> Account:
        with self._lock:
            self._accounts[(account.tenant_id, account.account_id)] = account
            return account

    def get_account(self, tenant_id: str, account_id: str) -> Account | None:
        with self._lock:
            account = self._accounts.get((tenant_id, account_id))
            if account is None or account.deleted_at is not None:
                return None
            return account

    def update_account(self, account: Account) -> None:
        with self._lock:
            self._accounts[(account.tenant_id, account.account_id)] = account

    def list_accounts(
        self, tenant_id: str, *, owner_id: str | None = None, status: str | None = None, limit: int, offset: int
    ) -> tuple[list[Account], int]:
        with self._lock:
            items = [
                a
                for a in self._accounts.values()
                if a.tenant_id == tenant_id
                and a.deleted_at is None
                and (owner_id is None or a.owner_id == owner_id)
                and (status is None or a.status == status)
            ]
            items.sort(key=lambda a: a.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    def list_account_ids_for_owner(self, tenant_id: str, owner_id: str) -> list[str]:
        with self._lock:
            return [
                a.account_id
                for a in self._accounts.values()
                if a.tenant_id == tenant_id and a.owner_id == owner_id and a.deleted_at is None
            ]

    def list_accounts_bulk(self, tenant_id: str, *, owner_id: str | None = None) -> list[Account]:
        """无分页全量（健康度重算 / 进度指标专用；单租户量级受控）。"""
        with self._lock:
            items = [
                a
                for a in self._accounts.values()
                if a.tenant_id == tenant_id
                and a.deleted_at is None
                and (owner_id is None or a.owner_id == owner_id)
            ]
            items.sort(key=lambda a: a.account_id)
            return items

    def list_tenant_ids(self) -> list[str]:
        with self._lock:
            return sorted({a.tenant_id for a in self._accounts.values() if a.deleted_at is None})

    def update_account_health(
        self, tenant_id: str, account_id: str, *, score: int, band: str, computed_at: datetime
    ) -> None:
        with self._lock:
            account = self._accounts.get((tenant_id, account_id))
            if account is None or account.deleted_at is not None:
                return
            account.health_score = score
            account.health_band = band
            account.health_computed_at = computed_at

    # ------------------------------------------------------------ 联系人

    def add_contact(self, contact: Contact) -> Contact:
        with self._lock:
            self._contacts[(contact.tenant_id, contact.contact_id)] = contact
            return contact

    def get_contact(self, tenant_id: str, contact_id: str) -> Contact | None:
        with self._lock:
            contact = self._contacts.get((tenant_id, contact_id))
            if contact is None or contact.deleted_at is not None:
                return None
            return contact

    def update_contact(self, contact: Contact) -> None:
        with self._lock:
            self._contacts[(contact.tenant_id, contact.contact_id)] = contact

    def list_contacts(
        self, tenant_id: str, *, account_id: str | None = None, limit: int, offset: int
    ) -> tuple[list[Contact], int]:
        with self._lock:
            items = [
                c
                for c in self._contacts.values()
                if c.tenant_id == tenant_id
                and c.deleted_at is None
                and (account_id is None or c.account_id == account_id)
            ]
            items.sort(key=lambda c: c.created_at)
            return items[offset : offset + _clamp(limit)], len(items)

    def count_contacts_for_account(self, tenant_id: str, account_id: str) -> int:
        with self._lock:
            return sum(
                1
                for c in self._contacts.values()
                if c.tenant_id == tenant_id and c.account_id == account_id and c.deleted_at is None
            )

    def list_contacts_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Contact]:
        keys = set(account_ids)
        with self._lock:
            return [
                c
                for c in self._contacts.values()
                if c.tenant_id == tenant_id and c.deleted_at is None and c.account_id in keys
            ]

    # ------------------------------------------------------------ 线索

    def add_lead(self, lead: Lead) -> Lead:
        with self._lock:
            self._leads[(lead.tenant_id, lead.lead_id)] = lead
            return lead

    def get_lead(self, tenant_id: str, lead_id: str) -> Lead | None:
        with self._lock:
            lead = self._leads.get((tenant_id, lead_id))
            if lead is None or lead.deleted_at is not None:
                return None
            return lead

    def update_lead(self, lead: Lead) -> None:
        with self._lock:
            self._leads[(lead.tenant_id, lead.lead_id)] = lead

    def list_leads(
        self, tenant_id: str, *, owner_id: str | None = None, status: str | None = None, limit: int, offset: int
    ) -> tuple[list[Lead], int]:
        with self._lock:
            items = [
                lead
                for lead in self._leads.values()
                if lead.tenant_id == tenant_id
                and lead.deleted_at is None
                and (owner_id is None or lead.owner_id == owner_id)
                and (status is None or lead.status == status)
            ]
            items.sort(key=lambda lead: lead.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    # ------------------------------------------------------------ 商机

    def add_opportunity(self, opportunity: Opportunity) -> Opportunity:
        with self._lock:
            self._opportunities[(opportunity.tenant_id, opportunity.opportunity_id)] = opportunity
            return opportunity

    def get_opportunity(self, tenant_id: str, opportunity_id: str) -> Opportunity | None:
        with self._lock:
            opportunity = self._opportunities.get((tenant_id, opportunity_id))
            if opportunity is None or opportunity.deleted_at is not None:
                return None
            return opportunity

    def update_opportunity(self, opportunity: Opportunity) -> None:
        with self._lock:
            self._opportunities[(opportunity.tenant_id, opportunity.opportunity_id)] = opportunity

    def transition_opportunity_stage(
        self, tenant_id: str, opportunity_id: str, *, from_stage: str, to_stage: str, at: datetime
    ) -> bool:
        """条件迁移（首写获胜）：仅当当前 stage = from_stage 时更新；返回是否生效。"""
        with self._lock:
            opportunity = self._opportunities.get((tenant_id, opportunity_id))
            if opportunity is None or opportunity.deleted_at is not None or opportunity.stage != from_stage:
                return False
            opportunity.stage = to_stage
            opportunity.stage_entered_at = at
            opportunity.updated_at = at
            if to_stage in ("won", "lost"):
                opportunity.closed_at = at
            return True

    def list_opportunities(
        self,
        tenant_id: str,
        *,
        owner_id: str | None = None,
        account_id: str | None = None,
        stage: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Opportunity], int]:
        with self._lock:
            items = [
                o
                for o in self._opportunities.values()
                if o.tenant_id == tenant_id
                and o.deleted_at is None
                and (owner_id is None or o.owner_id == owner_id)
                and (account_id is None or o.account_id == account_id)
                and (stage is None or o.stage == stage)
            ]
            items.sort(key=lambda o: o.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    def list_opportunities_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Opportunity]:
        keys = set(account_ids)
        with self._lock:
            return [
                o
                for o in self._opportunities.values()
                if o.tenant_id == tenant_id and o.deleted_at is None and o.account_id in keys
            ]

    # ------------------------------------------------------------ 阶段事件（append-only）

    def append_stage_event(self, event: StageEvent) -> StageEvent:
        with self._lock:
            self._stage_events.append(event)
            return event

    def list_stage_events(self, tenant_id: str, opportunity_id: str) -> list[StageEvent]:
        with self._lock:
            items = [
                event
                for event in self._stage_events
                if event.tenant_id == tenant_id and event.opportunity_id == opportunity_id
            ]
            items.sort(key=lambda event: event.occurred_at)
            return items

    def list_stage_events_for_opportunities(
        self, tenant_id: str, opportunity_ids: Iterable[str]
    ) -> list[StageEvent]:
        keys = set(opportunity_ids)
        with self._lock:
            return [e for e in self._stage_events if e.tenant_id == tenant_id and e.opportunity_id in keys]

    def convert_lead_atomic(
        self, lead: Lead, account: Account, contact: Contact, opportunity: Opportunity | None = None
    ) -> None:
        """线索转化（单事务语义）：建 Account + Contact（+ 可选 Opportunity）+ 更新 Lead。

        PG 实现为真事务；内存实现锁内连续写（无半成品可观察）。
        """
        with self._lock:
            self._accounts[(account.tenant_id, account.account_id)] = account
            self._contacts[(contact.tenant_id, contact.contact_id)] = contact
            if opportunity is not None:
                self._opportunities[(opportunity.tenant_id, opportunity.opportunity_id)] = opportunity
            self._leads[(lead.tenant_id, lead.lead_id)] = lead

    # ------------------------------------------------------------ 活动

    def add_activity(self, activity: Activity) -> Activity:
        with self._lock:
            self._activities[(activity.tenant_id, activity.activity_id)] = activity
            return activity

    def get_activity(self, tenant_id: str, activity_id: str) -> Activity | None:
        with self._lock:
            activity = self._activities.get((tenant_id, activity_id))
            if activity is None or activity.deleted_at is not None:
                return None
            return activity

    def update_activity(self, activity: Activity) -> None:
        with self._lock:
            self._activities[(activity.tenant_id, activity.activity_id)] = activity

    def list_activities(
        self,
        tenant_id: str,
        *,
        owner_id: str | None = None,
        account_id: str | None = None,
        contact_id: str | None = None,
        opportunity_id: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Activity], int]:
        with self._lock:
            items = [
                a
                for a in self._activities.values()
                if a.tenant_id == tenant_id
                and a.deleted_at is None
                and (owner_id is None or a.owner_id == owner_id)
                and (account_id is None or a.account_id == account_id)
                and (contact_id is None or a.contact_id == contact_id)
                and (opportunity_id is None or a.opportunity_id == opportunity_id)
            ]
            items.sort(key=lambda a: a.occurred_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    def list_activities_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Activity]:
        keys = set(account_ids)
        with self._lock:
            return [
                a
                for a in self._activities.values()
                if a.tenant_id == tenant_id and a.deleted_at is None and a.account_id in keys
            ]

    def list_due_activities(self, tenant_id: str, *, due_before: datetime) -> list[Activity]:
        """待提醒任务：`kind='task'` 且 `planned` 且 `due_at <= due_before` 且当日未提醒。"""
        with self._lock:
            return [
                a
                for a in self._activities.values()
                if a.tenant_id == tenant_id
                and a.deleted_at is None
                and a.kind == "task"
                and a.status == "planned"
                and a.due_at is not None
                and a.due_at <= due_before
            ]

    # ------------------------------------------------------------ 报价

    def add_quote(self, quote: Quote, lines: list[QuoteLine]) -> Quote:
        with self._lock:
            self._quotes[(quote.tenant_id, quote.quote_id)] = quote
            self._quote_lines[(quote.tenant_id, quote.quote_id)] = list(lines)
            return quote

    def get_quote(self, tenant_id: str, quote_id: str) -> Quote | None:
        with self._lock:
            quote = self._quotes.get((tenant_id, quote_id))
            if quote is None or quote.deleted_at is not None:
                return None
            return quote

    def update_quote(self, quote: Quote, lines: list[QuoteLine] | None = None) -> None:
        with self._lock:
            self._quotes[(quote.tenant_id, quote.quote_id)] = quote
            if lines is not None:
                self._quote_lines[(quote.tenant_id, quote.quote_id)] = list(lines)

    def list_quote_lines(self, tenant_id: str, quote_id: str) -> list[QuoteLine]:
        with self._lock:
            items = list(self._quote_lines.get((tenant_id, quote_id), []))
            items.sort(key=lambda line: line.line_no)
            return items

    def list_quotes(
        self,
        tenant_id: str,
        *,
        owner_id: str | None = None,
        account_id: str | None = None,
        status: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Quote], int]:
        with self._lock:
            items = [
                q
                for q in self._quotes.values()
                if q.tenant_id == tenant_id
                and q.deleted_at is None
                and (owner_id is None or q.owner_id == owner_id)
                and (account_id is None or q.account_id == account_id)
                and (status is None or q.status == status)
            ]
            items.sort(key=lambda q: q.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    def count_quotes_with_prefix(self, tenant_id: str, prefix: str) -> int:
        with self._lock:
            return sum(
                1
                for q in self._quotes.values()
                if q.tenant_id == tenant_id and q.quote_no.startswith(prefix)
            )

    def transition_quote_status(
        self, tenant_id: str, quote_id: str, *, from_status: str, to_status: str, at: datetime
    ) -> bool:
        """条件迁移（首写获胜）：仅当当前 status = from_status 时更新；返回是否生效。"""
        with self._lock:
            quote = self._quotes.get((tenant_id, quote_id))
            if quote is None or quote.deleted_at is not None or quote.status != from_status:
                return False
            quote.status = to_status
            if to_status in ("confirmed", "converted") and quote.confirmed_at is None:
                quote.confirmed_at = at
            quote.updated_at = at
            return True

    def convert_quote_atomic(self, quote: Quote, contract: Contract) -> None:
        """报价转合同（单事务语义）：建 Contract + 更新 Quote（converted / 回填合同 id）。"""
        with self._lock:
            self._contracts[(contract.tenant_id, contract.contract_id)] = contract
            self._quotes[(quote.tenant_id, quote.quote_id)] = quote

    # ------------------------------------------------------------ 合同

    def add_contract(self, contract: Contract) -> Contract:
        with self._lock:
            self._contracts[(contract.tenant_id, contract.contract_id)] = contract
            return contract

    def get_contract(self, tenant_id: str, contract_id: str) -> Contract | None:
        with self._lock:
            contract = self._contracts.get((tenant_id, contract_id))
            if contract is None or contract.deleted_at is not None:
                return None
            return contract

    def update_contract(self, contract: Contract) -> None:
        with self._lock:
            self._contracts[(contract.tenant_id, contract.contract_id)] = contract

    def increment_contract_paid(self, tenant_id: str, contract_id: str, *, delta_cents: int) -> bool:
        """回款原子增量累加（并发安全）；超 `amount_cents` 时不生效（返回 False）。"""
        with self._lock:
            contract = self._contracts.get((tenant_id, contract_id))
            if contract is None or contract.deleted_at is not None:
                return False
            if contract.paid_cents + delta_cents > contract.amount_cents:
                return False
            contract.paid_cents += delta_cents
            contract.updated_at = datetime.now(UTC)
            return True

    def list_contracts(
        self,
        tenant_id: str,
        *,
        owner_id: str | None = None,
        account_id: str | None = None,
        status: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Contract], int]:
        with self._lock:
            items = [
                c
                for c in self._contracts.values()
                if c.tenant_id == tenant_id
                and c.deleted_at is None
                and (owner_id is None or c.owner_id == owner_id)
                and (account_id is None or c.account_id == account_id)
                and (status is None or c.status == status)
            ]
            items.sort(key=lambda c: c.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    def list_contracts_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Contract]:
        keys = set(account_ids)
        with self._lock:
            return [
                c
                for c in self._contracts.values()
                if c.tenant_id == tenant_id and c.deleted_at is None and c.account_id in keys
            ]

    def list_contracts_in_renewal_window(self, tenant_id: str, *, from_date: date, until: date) -> list[Contract]:
        """续约窗口：`signed` 且 `from_date <= ends_on <= until`（已过期由 `list_expired_contracts` 承接）。"""
        with self._lock:
            return [
                c
                for c in self._contracts.values()
                if c.tenant_id == tenant_id
                and c.deleted_at is None
                and c.status == "signed"
                and c.ends_on is not None
                and from_date <= c.ends_on <= until
            ]

    def list_expired_contracts(self, tenant_id: str, *, today: date) -> list[Contract]:
        with self._lock:
            return [
                c
                for c in self._contracts.values()
                if c.tenant_id == tenant_id
                and c.deleted_at is None
                and c.status == "signed"
                and c.ends_on is not None
                and c.ends_on < today
            ]

    def count_contracts_with_prefix(self, tenant_id: str, prefix: str) -> int:
        with self._lock:
            return sum(
                1
                for c in self._contracts.values()
                if c.tenant_id == tenant_id and c.contract_no.startswith(prefix)
            )

    # ------------------------------------------------------------ 智能化记录（append-only）

    def add_insight(self, insight: Insight) -> Insight:
        with self._lock:
            self._insights.append(insight)
            return insight

    def list_insights(
        self, tenant_id: str, *, account_id: str, limit: int, offset: int
    ) -> tuple[list[Insight], int]:
        with self._lock:
            items = [
                i for i in self._insights if i.tenant_id == tenant_id and i.account_id == account_id
            ]
            items.sort(key=lambda i: i.created_at, reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    # ------------------------------------------------------------ 目标

    def upsert_target(self, target: Target) -> Target:
        with self._lock:
            for key, existing in self._targets.items():
                if (
                    existing.tenant_id == target.tenant_id
                    and existing.owner_id == target.owner_id
                    and existing.period_month == target.period_month
                    and existing.deleted_at is None
                ):
                    existing.amount_target_cents = target.amount_target_cents
                    existing.count_target = target.count_target
                    existing.updated_at = target.updated_at
                    return existing
            self._targets[(target.tenant_id, target.target_id)] = target
            return target

    def get_target(self, tenant_id: str, owner_id: str, period_month: date) -> Target | None:
        with self._lock:
            for target in self._targets.values():
                if (
                    target.tenant_id == tenant_id
                    and target.owner_id == owner_id
                    and target.period_month == period_month
                    and target.deleted_at is None
                ):
                    return target
            return None

    def list_targets(
        self, tenant_id: str, *, owner_id: str | None = None, period_month: date | None = None, limit: int, offset: int
    ) -> tuple[list[Target], int]:
        with self._lock:
            items = [
                t
                for t in self._targets.values()
                if t.tenant_id == tenant_id
                and t.deleted_at is None
                and (owner_id is None or t.owner_id == owner_id)
                and (period_month is None or t.period_month == period_month)
            ]
            items.sort(key=lambda t: (t.period_month, t.owner_id), reverse=True)
            return items[offset : offset + _clamp(limit)], len(items)

    # ------------------------------------------------------------ 自定义字段元数据

    def upsert_field_def(self, definition: FieldDef) -> FieldDef:
        with self._lock:
            self._field_defs[(definition.tenant_id, definition.object_key, definition.field_key)] = definition
            return definition

    def list_field_defs(self, tenant_id: str, object_key: str) -> list[FieldDef]:
        with self._lock:
            items = [
                d
                for d in self._field_defs.values()
                if d.tenant_id == tenant_id and d.object_key == object_key
            ]
            items.sort(key=lambda d: d.field_key)
            return items