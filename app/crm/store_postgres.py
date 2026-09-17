"""CRM 仓储（PostgreSQL 实现，迁移 035）。方法集与 `store.py` 的内存实现一致。

- 连接支持「单连接」或「连接池」（沿用记忆层 `PostgresMemoryStore._connection` 手法）。
- 写路径用 `connection.transaction()` 包事务；JSONB 列以 `json.dumps` + `%s::jsonb` 写入。
- 所有查询严格带 `tenant_id`；软删除默认过滤；append-only 表（阶段事件 / 智能化记录）不过滤。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from contextlib import contextmanager, nullcontext
from datetime import date, datetime

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

_ACCOUNT_COLUMNS = (
    "tenant_id, account_id, name, industry, source, owner_id, status, custom_fields, "
    "health_score, health_band, health_computed_at, created_at, updated_at, deleted_at"
)
_CONTACT_COLUMNS = (
    "tenant_id, contact_id, account_id, name, title, phone, email, is_primary, birthday, "
    "owner_id, custom_fields, created_at, updated_at, deleted_at"
)
_LEAD_COLUMNS = (
    "tenant_id, lead_id, name, company, phone, email, source, owner_id, status, "
    "converted_account_id, converted_contact_id, converted_opportunity_id, custom_fields, "
    "created_at, updated_at, deleted_at"
)
_OPPORTUNITY_COLUMNS = (
    "tenant_id, opportunity_id, account_id, name, stage, amount_cents, expected_close, owner_id, "
    "stage_entered_at, closed_at, custom_fields, created_at, updated_at, deleted_at"
)
_STAGE_EVENT_COLUMNS = (
    "tenant_id, event_id, opportunity_id, from_stage, to_stage, amount_cents, actor_id, occurred_at"
)
_ACTIVITY_COLUMNS = (
    "tenant_id, activity_id, kind, subject, content, account_id, contact_id, opportunity_id, "
    "owner_id, status, due_at, occurred_at, reminded_on, created_by_kind, created_at, updated_at, deleted_at"
)
_QUOTE_COLUMNS = (
    "tenant_id, quote_id, account_id, opportunity_id, quote_no, status, subtotal_cents, tax_cents, "
    "total_cents, valid_until, confirmed_at, converted_contract_id, owner_id, created_at, updated_at, deleted_at"
)
_QUOTE_LINE_COLUMNS = (
    "tenant_id, quote_id, line_no, description, qty, unit_price_cents, tax_rate_bp, "
    "line_subtotal_cents, line_tax_cents"
)
_CONTRACT_COLUMNS = (
    "tenant_id, contract_id, account_id, quote_id, opportunity_id, contract_no, title, status, "
    "amount_cents, paid_cents, starts_on, ends_on, document_object_key, signed_at, owner_id, "
    "created_at, updated_at, deleted_at"
)
_INSIGHT_COLUMNS = (
    "tenant_id, insight_id, account_id, kind, input_digest, content, evidence_refs, dropped_refs, "
    "model_key, generated_by, created_at"
)
_TARGET_COLUMNS = (
    "tenant_id, target_id, owner_id, period_month, amount_target_cents, count_target, "
    "created_at, updated_at, deleted_at"
)
_FIELD_DEF_COLUMNS = (
    "tenant_id, object_key, field_key, label, field_type, required, options, active, created_at"
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


class PostgresCrmStore:
    """CRM 持久化（表 `workbench_crm_*`，迁移 035）。"""

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    # ------------------------------------------------------------ hydrate

    @staticmethod
    def _account(row: tuple) -> Account:
        return Account(
            tenant_id=str(row[0]), account_id=str(row[1]), name=str(row[2]), industry=str(row[3]),
            source=str(row[4]), owner_id=str(row[5]), status=str(row[6]),
            custom_fields=_loads(row[7], {}), health_score=row[8],
            health_band=None if row[9] is None else str(row[9]), health_computed_at=row[10],
            created_at=row[11], updated_at=row[12], deleted_at=row[13],
        )

    @staticmethod
    def _contact(row: tuple) -> Contact:
        return Contact(
            tenant_id=str(row[0]), contact_id=str(row[1]),
            account_id=None if row[2] is None else str(row[2]), name=str(row[3]), title=str(row[4]),
            phone=str(row[5]), email=str(row[6]), is_primary=bool(row[7]),
            birthday=row[8], owner_id=str(row[9]), custom_fields=_loads(row[10], {}),
            created_at=row[11], updated_at=row[12], deleted_at=row[13],
        )

    @staticmethod
    def _lead(row: tuple) -> Lead:
        return Lead(
            tenant_id=str(row[0]), lead_id=str(row[1]), name=str(row[2]), company=str(row[3]),
            phone=str(row[4]), email=str(row[5]), source=str(row[6]), owner_id=str(row[7]),
            status=str(row[8]),
            converted_account_id=None if row[9] is None else str(row[9]),
            converted_contact_id=None if row[10] is None else str(row[10]),
            converted_opportunity_id=None if row[11] is None else str(row[11]),
            custom_fields=_loads(row[12], {}), created_at=row[13], updated_at=row[14], deleted_at=row[15],
        )

    @staticmethod
    def _opportunity(row: tuple) -> Opportunity:
        return Opportunity(
            tenant_id=str(row[0]), opportunity_id=str(row[1]), account_id=str(row[2]), name=str(row[3]),
            stage=str(row[4]), amount_cents=int(row[5]), expected_close=row[6], owner_id=str(row[7]),
            stage_entered_at=row[8], closed_at=row[9], custom_fields=_loads(row[10], {}),
            created_at=row[11], updated_at=row[12], deleted_at=row[13],
        )

    @staticmethod
    def _stage_event(row: tuple) -> StageEvent:
        return StageEvent(
            tenant_id=str(row[0]), event_id=str(row[1]), opportunity_id=str(row[2]),
            from_stage=None if row[3] is None else str(row[3]), to_stage=str(row[4]),
            amount_cents=int(row[5]), actor_id=str(row[6]), occurred_at=row[7],
        )

    @staticmethod
    def _activity(row: tuple) -> Activity:
        return Activity(
            tenant_id=str(row[0]), activity_id=str(row[1]), kind=str(row[2]), subject=str(row[3]),
            content=str(row[4]),
            account_id=None if row[5] is None else str(row[5]),
            contact_id=None if row[6] is None else str(row[6]),
            opportunity_id=None if row[7] is None else str(row[7]),
            owner_id=str(row[8]), status=str(row[9]), due_at=row[10], occurred_at=row[11],
            reminded_on=row[12], created_by_kind=str(row[13]), created_at=row[14],
            updated_at=row[15], deleted_at=row[16],
        )

    @staticmethod
    def _quote(row: tuple) -> Quote:
        return Quote(
            tenant_id=str(row[0]), quote_id=str(row[1]), account_id=str(row[2]),
            opportunity_id=None if row[3] is None else str(row[3]), quote_no=str(row[4]),
            status=str(row[5]), subtotal_cents=int(row[6]), tax_cents=int(row[7]),
            total_cents=int(row[8]), valid_until=row[9], confirmed_at=row[10],
            converted_contract_id=None if row[11] is None else str(row[11]),
            owner_id=str(row[12]), created_at=row[13], updated_at=row[14], deleted_at=row[15],
        )

    @staticmethod
    def _quote_line(row: tuple) -> QuoteLine:
        return QuoteLine(
            tenant_id=str(row[0]), quote_id=str(row[1]), line_no=int(row[2]), description=str(row[3]),
            qty=f"{row[4]:.3f}", unit_price_cents=int(row[5]), tax_rate_bp=int(row[6]),
            line_subtotal_cents=int(row[7]), line_tax_cents=int(row[8]),
        )

    @staticmethod
    def _contract(row: tuple) -> Contract:
        return Contract(
            tenant_id=str(row[0]), contract_id=str(row[1]), account_id=str(row[2]),
            quote_id=None if row[3] is None else str(row[3]),
            opportunity_id=None if row[4] is None else str(row[4]),
            contract_no=str(row[5]), title=str(row[6]), status=str(row[7]),
            amount_cents=int(row[8]), paid_cents=int(row[9]), starts_on=row[10], ends_on=row[11],
            document_object_key=str(row[12]), signed_at=row[13], owner_id=str(row[14]),
            created_at=row[15], updated_at=row[16], deleted_at=row[17],
        )

    @staticmethod
    def _insight(row: tuple) -> Insight:
        return Insight(
            tenant_id=str(row[0]), insight_id=str(row[1]), account_id=str(row[2]), kind=str(row[3]),
            input_digest=str(row[4]), content=_loads(row[5], {}),
            evidence_refs=_loads(row[6], []), dropped_refs=_loads(row[7], []),
            model_key=str(row[8]), generated_by=str(row[9]), created_at=row[10],
        )

    @staticmethod
    def _target(row: tuple) -> Target:
        return Target(
            tenant_id=str(row[0]), target_id=str(row[1]), owner_id=str(row[2]),
            period_month=row[3], amount_target_cents=int(row[4]), count_target=int(row[5]),
            created_at=row[6], updated_at=row[7], deleted_at=row[8],
        )

    @staticmethod
    def _field_def(row: tuple) -> FieldDef:
        return FieldDef(
            tenant_id=str(row[0]), object_key=str(row[1]), field_key=str(row[2]), label=str(row[3]),
            field_type=str(row[4]), required=bool(row[5]), options=tuple(_loads(row[6], [])),
            active=bool(row[7]), created_at=row[8],
        )

    # ------------------------------------------------------------ 账户

    def add_account(self, account: Account) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_accounts ({_ACCOUNT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)",
                        (
                            account.tenant_id, account.account_id, account.name, account.industry,
                            account.source, account.owner_id, account.status, _json(account.custom_fields),
                            account.health_score, account.health_band, account.health_computed_at,
                            account.created_at, account.updated_at, account.deleted_at,
                        ),
                    )
        return account

    def get_account(self, tenant_id: str, account_id: str) -> Account | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM workbench_crm_accounts "
                    "WHERE tenant_id = %s AND account_id = %s AND deleted_at IS NULL",
                    (tenant_id, account_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._account(row)

    def update_account(self, account: Account) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_accounts
                        SET name = %s, industry = %s, source = %s, owner_id = %s, status = %s,
                            custom_fields = %s::jsonb, health_score = %s, health_band = %s,
                            health_computed_at = %s, updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND account_id = %s
                        """,
                        (
                            account.name, account.industry, account.source, account.owner_id,
                            account.status, _json(account.custom_fields), account.health_score,
                            account.health_band, account.health_computed_at, account.updated_at,
                            account.deleted_at, account.tenant_id, account.account_id,
                        ),
                    )

    def list_accounts(
        self, tenant_id: str, *, owner_id: str | None = None, status: str | None = None, limit: int, offset: int
    ) -> tuple[list[Account], int]:
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if owner_id is not None:
            where.append("owner_id = %s")
            params.append(owner_id)
        if status is not None:
            where.append("status = %s")
            params.append(status)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_crm_accounts WHERE {clause}", tuple(params)
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM workbench_crm_accounts WHERE {clause} "
                    "ORDER BY created_at DESC, account_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._account(row) for row in rows], total

    def list_account_ids_for_owner(self, tenant_id: str, owner_id: str) -> list[str]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT account_id FROM workbench_crm_accounts "
                    "WHERE tenant_id = %s AND owner_id = %s AND deleted_at IS NULL",
                    (tenant_id, owner_id),
                )
                rows = cursor.fetchall()
        return [str(row[0]) for row in rows]

    def list_accounts_bulk(self, tenant_id: str, *, owner_id: str | None = None) -> list[Account]:
        """无分页全量（健康度重算 / 进度指标专用；单租户量级受控）。"""
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if owner_id is not None:
            where.append("owner_id = %s")
            params.append(owner_id)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM workbench_crm_accounts WHERE {clause} "
                    "ORDER BY account_id",
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [self._account(row) for row in rows]

    def list_tenant_ids(self) -> list[str]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT tenant_id FROM workbench_crm_accounts WHERE deleted_at IS NULL"
                )
                rows = cursor.fetchall()
        return sorted(str(row[0]) for row in rows)

    def update_account_health(
        self, tenant_id: str, account_id: str, *, score: int, band: str, computed_at: datetime
    ) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_accounts
                        SET health_score = %s, health_band = %s, health_computed_at = %s, updated_at = %s
                        WHERE tenant_id = %s AND account_id = %s AND deleted_at IS NULL
                        """,
                        (score, band, computed_at, computed_at, tenant_id, account_id),
                    )

    # ------------------------------------------------------------ 联系人

    def add_contact(self, contact: Contact) -> Contact:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_contacts ({_CONTACT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                        (
                            contact.tenant_id, contact.contact_id, contact.account_id, contact.name,
                            contact.title, contact.phone, contact.email, contact.is_primary,
                            contact.birthday, contact.owner_id, _json(contact.custom_fields),
                            contact.created_at, contact.updated_at, contact.deleted_at,
                        ),
                    )
        return contact

    def get_contact(self, tenant_id: str, contact_id: str) -> Contact | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTACT_COLUMNS} FROM workbench_crm_contacts "
                    "WHERE tenant_id = %s AND contact_id = %s AND deleted_at IS NULL",
                    (tenant_id, contact_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._contact(row)

    def update_contact(self, contact: Contact) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_contacts
                        SET account_id = %s, name = %s, title = %s, phone = %s, email = %s,
                            is_primary = %s, birthday = %s, owner_id = %s, custom_fields = %s::jsonb,
                            updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND contact_id = %s
                        """,
                        (
                            contact.account_id, contact.name, contact.title, contact.phone,
                            contact.email, contact.is_primary, contact.birthday, contact.owner_id,
                            _json(contact.custom_fields), contact.updated_at, contact.deleted_at,
                            contact.tenant_id, contact.contact_id,
                        ),
                    )

    def list_contacts(
        self, tenant_id: str, *, account_id: str | None = None, limit: int, offset: int
    ) -> tuple[list[Contact], int]:
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if account_id is not None:
            where.append("account_id = %s")
            params.append(account_id)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_crm_contacts WHERE {clause}", tuple(params)
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_CONTACT_COLUMNS} FROM workbench_crm_contacts WHERE {clause} "
                    "ORDER BY created_at LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._contact(row) for row in rows], total

    def count_contacts_for_account(self, tenant_id: str, account_id: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM workbench_crm_contacts "
                    "WHERE tenant_id = %s AND account_id = %s AND deleted_at IS NULL",
                    (tenant_id, account_id),
                )
                return int(cursor.fetchone()[0])

    def list_contacts_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Contact]:
        keys = [str(key) for key in account_ids]
        if not keys:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTACT_COLUMNS} FROM workbench_crm_contacts "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND account_id = ANY(%s)",
                    (tenant_id, keys),
                )
                rows = cursor.fetchall()
        return [self._contact(row) for row in rows]

    # ------------------------------------------------------------ 线索

    def add_lead(self, lead: Lead) -> Lead:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_leads ({_LEAD_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                        (
                            lead.tenant_id, lead.lead_id, lead.name, lead.company, lead.phone,
                            lead.email, lead.source, lead.owner_id, lead.status,
                            lead.converted_account_id, lead.converted_contact_id,
                            lead.converted_opportunity_id, _json(lead.custom_fields),
                            lead.created_at, lead.updated_at, lead.deleted_at,
                        ),
                    )
        return lead

    def get_lead(self, tenant_id: str, lead_id: str) -> Lead | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_LEAD_COLUMNS} FROM workbench_crm_leads "
                    "WHERE tenant_id = %s AND lead_id = %s AND deleted_at IS NULL",
                    (tenant_id, lead_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._lead(row)

    def update_lead(self, lead: Lead) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_leads
                        SET name = %s, company = %s, phone = %s, email = %s, source = %s,
                            owner_id = %s, status = %s, converted_account_id = %s,
                            converted_contact_id = %s, converted_opportunity_id = %s,
                            custom_fields = %s::jsonb, updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND lead_id = %s
                        """,
                        (
                            lead.name, lead.company, lead.phone, lead.email, lead.source,
                            lead.owner_id, lead.status, lead.converted_account_id,
                            lead.converted_contact_id, lead.converted_opportunity_id,
                            _json(lead.custom_fields), lead.updated_at, lead.deleted_at,
                            lead.tenant_id, lead.lead_id,
                        ),
                    )

    def list_leads(
        self, tenant_id: str, *, owner_id: str | None = None, status: str | None = None, limit: int, offset: int
    ) -> tuple[list[Lead], int]:
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if owner_id is not None:
            where.append("owner_id = %s")
            params.append(owner_id)
        if status is not None:
            where.append("status = %s")
            params.append(status)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM workbench_crm_leads WHERE {clause}", tuple(params))
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_LEAD_COLUMNS} FROM workbench_crm_leads WHERE {clause} "
                    "ORDER BY created_at DESC, lead_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._lead(row) for row in rows], total

    # ------------------------------------------------------------ 商机

    def add_opportunity(self, opportunity: Opportunity) -> Opportunity:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_opportunities ({_OPPORTUNITY_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                        (
                            opportunity.tenant_id, opportunity.opportunity_id, opportunity.account_id,
                            opportunity.name, opportunity.stage, opportunity.amount_cents,
                            opportunity.expected_close, opportunity.owner_id, opportunity.stage_entered_at,
                            opportunity.closed_at, _json(opportunity.custom_fields),
                            opportunity.created_at, opportunity.updated_at, opportunity.deleted_at,
                        ),
                    )
        return opportunity

    def get_opportunity(self, tenant_id: str, opportunity_id: str) -> Opportunity | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_OPPORTUNITY_COLUMNS} FROM workbench_crm_opportunities "
                    "WHERE tenant_id = %s AND opportunity_id = %s AND deleted_at IS NULL",
                    (tenant_id, opportunity_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._opportunity(row)

    def update_opportunity(self, opportunity: Opportunity) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_opportunities
                        SET account_id = %s, name = %s, stage = %s, amount_cents = %s,
                            expected_close = %s, owner_id = %s, stage_entered_at = %s, closed_at = %s,
                            custom_fields = %s::jsonb, updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND opportunity_id = %s
                        """,
                        (
                            opportunity.account_id, opportunity.name, opportunity.stage,
                            opportunity.amount_cents, opportunity.expected_close, opportunity.owner_id,
                            opportunity.stage_entered_at, opportunity.closed_at,
                            _json(opportunity.custom_fields), opportunity.updated_at,
                            opportunity.deleted_at, opportunity.tenant_id, opportunity.opportunity_id,
                        ),
                    )

    def transition_opportunity_stage(
        self, tenant_id: str, opportunity_id: str, *, from_stage: str, to_stage: str, at: datetime
    ) -> bool:
        """条件迁移（首写获胜）：仅当当前 stage = from_stage 时更新；返回是否生效。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_opportunities
                        SET stage = %s, stage_entered_at = %s, updated_at = %s,
                            closed_at = CASE WHEN %s IN ('won', 'lost') THEN %s ELSE closed_at END
                        WHERE tenant_id = %s AND opportunity_id = %s AND stage = %s AND deleted_at IS NULL
                        """,
                        (
                            to_stage, at, at, to_stage, at, tenant_id, opportunity_id, from_stage,
                        ),
                    )
                    return int(cursor.rowcount or 0) == 1

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
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if owner_id is not None:
            where.append("owner_id = %s")
            params.append(owner_id)
        if account_id is not None:
            where.append("account_id = %s")
            params.append(account_id)
        if stage is not None:
            where.append("stage = %s")
            params.append(stage)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_crm_opportunities WHERE {clause}", tuple(params)
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_OPPORTUNITY_COLUMNS} FROM workbench_crm_opportunities WHERE {clause} "
                    "ORDER BY created_at DESC, opportunity_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._opportunity(row) for row in rows], total

    def list_opportunities_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Opportunity]:
        keys = [str(key) for key in account_ids]
        if not keys:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_OPPORTUNITY_COLUMNS} FROM workbench_crm_opportunities "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND account_id = ANY(%s)",
                    (tenant_id, keys),
                )
                rows = cursor.fetchall()
        return [self._opportunity(row) for row in rows]

    # ------------------------------------------------------------ 阶段事件（append-only）

    def append_stage_event(self, event: StageEvent) -> StageEvent:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_opportunity_stage_events ({_STAGE_EVENT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            event.tenant_id, event.event_id, event.opportunity_id, event.from_stage,
                            event.to_stage, event.amount_cents, event.actor_id, event.occurred_at,
                        ),
                    )
        return event

    def list_stage_events(self, tenant_id: str, opportunity_id: str) -> list[StageEvent]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_STAGE_EVENT_COLUMNS} FROM workbench_crm_opportunity_stage_events "
                    "WHERE tenant_id = %s AND opportunity_id = %s ORDER BY occurred_at, event_id",
                    (tenant_id, opportunity_id),
                )
                rows = cursor.fetchall()
        return [self._stage_event(row) for row in rows]

    def list_stage_events_for_opportunities(
        self, tenant_id: str, opportunity_ids: Iterable[str]
    ) -> list[StageEvent]:
        keys = [str(key) for key in opportunity_ids]
        if not keys:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_STAGE_EVENT_COLUMNS} FROM workbench_crm_opportunity_stage_events "
                    "WHERE tenant_id = %s AND opportunity_id = ANY(%s) ORDER BY occurred_at, event_id",
                    (tenant_id, keys),
                )
                rows = cursor.fetchall()
        return [self._stage_event(row) for row in rows]

    def convert_lead_atomic(
        self, lead: Lead, account: Account, contact: Contact, opportunity: Opportunity | None = None
    ) -> None:
        """线索转化（**单事务**）：建 Account + Contact（+ 可选 Opportunity）+ 更新 Lead。

        任一步失败 ⇒ 整体回滚，无半成品（真库用例 1 断言）。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_accounts ({_ACCOUNT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)",
                        (
                            account.tenant_id, account.account_id, account.name, account.industry,
                            account.source, account.owner_id, account.status, _json(account.custom_fields),
                            account.health_score, account.health_band, account.health_computed_at,
                            account.created_at, account.updated_at, account.deleted_at,
                        ),
                    )
                    cursor.execute(
                        f"INSERT INTO workbench_crm_contacts ({_CONTACT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                        (
                            contact.tenant_id, contact.contact_id, contact.account_id, contact.name,
                            contact.title, contact.phone, contact.email, contact.is_primary,
                            contact.birthday, contact.owner_id, _json(contact.custom_fields),
                            contact.created_at, contact.updated_at, contact.deleted_at,
                        ),
                    )
                    if opportunity is not None:
                        cursor.execute(
                            f"INSERT INTO workbench_crm_opportunities ({_OPPORTUNITY_COLUMNS}) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                            (
                                opportunity.tenant_id, opportunity.opportunity_id,
                                opportunity.account_id, opportunity.name, opportunity.stage,
                                opportunity.amount_cents, opportunity.expected_close,
                                opportunity.owner_id, opportunity.stage_entered_at, opportunity.closed_at,
                                _json(opportunity.custom_fields), opportunity.created_at,
                                opportunity.updated_at, opportunity.deleted_at,
                            ),
                        )
                    cursor.execute(
                        """
                        UPDATE workbench_crm_leads
                        SET status = %s, converted_account_id = %s, converted_contact_id = %s,
                            converted_opportunity_id = %s, updated_at = %s
                        WHERE tenant_id = %s AND lead_id = %s
                        """,
                        (
                            lead.status, lead.converted_account_id, lead.converted_contact_id,
                            lead.converted_opportunity_id, lead.updated_at, lead.tenant_id, lead.lead_id,
                        ),
                    )

    # ------------------------------------------------------------ 活动

    def add_activity(self, activity: Activity) -> Activity:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_activities ({_ACTIVITY_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            activity.tenant_id, activity.activity_id, activity.kind, activity.subject,
                            activity.content, activity.account_id, activity.contact_id,
                            activity.opportunity_id, activity.owner_id, activity.status, activity.due_at,
                            activity.occurred_at, activity.reminded_on, activity.created_by_kind,
                            activity.created_at, activity.updated_at, activity.deleted_at,
                        ),
                    )
        return activity

    def get_activity(self, tenant_id: str, activity_id: str) -> Activity | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_ACTIVITY_COLUMNS} FROM workbench_crm_activities "
                    "WHERE tenant_id = %s AND activity_id = %s AND deleted_at IS NULL",
                    (tenant_id, activity_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._activity(row)

    def update_activity(self, activity: Activity) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_activities
                        SET kind = %s, subject = %s, content = %s, account_id = %s, contact_id = %s,
                            opportunity_id = %s, owner_id = %s, status = %s, due_at = %s,
                            occurred_at = %s, reminded_on = %s, created_by_kind = %s,
                            updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND activity_id = %s
                        """,
                        (
                            activity.kind, activity.subject, activity.content, activity.account_id,
                            activity.contact_id, activity.opportunity_id, activity.owner_id,
                            activity.status, activity.due_at, activity.occurred_at, activity.reminded_on,
                            activity.created_by_kind, activity.updated_at, activity.deleted_at,
                            activity.tenant_id, activity.activity_id,
                        ),
                    )

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
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        for column, value in (
            ("owner_id", owner_id),
            ("account_id", account_id),
            ("contact_id", contact_id),
            ("opportunity_id", opportunity_id),
        ):
            if value is not None:
                where.append(f"{column} = %s")
                params.append(value)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_crm_activities WHERE {clause}", tuple(params)
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_ACTIVITY_COLUMNS} FROM workbench_crm_activities WHERE {clause} "
                    "ORDER BY occurred_at DESC, activity_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._activity(row) for row in rows], total

    def list_activities_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Activity]:
        keys = [str(key) for key in account_ids]
        if not keys:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_ACTIVITY_COLUMNS} FROM workbench_crm_activities "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND account_id = ANY(%s)",
                    (tenant_id, keys),
                )
                rows = cursor.fetchall()
        return [self._activity(row) for row in rows]

    def list_due_activities(self, tenant_id: str, *, due_before: datetime) -> list[Activity]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_ACTIVITY_COLUMNS} FROM workbench_crm_activities "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND kind = 'task' AND status = 'planned' "
                    "AND due_at IS NOT NULL AND due_at <= %s ORDER BY due_at, activity_id",
                    (tenant_id, due_before),
                )
                rows = cursor.fetchall()
        return [self._activity(row) for row in rows]

    # ------------------------------------------------------------ 报价

    def add_quote(self, quote: Quote, lines: list[QuoteLine]) -> Quote:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_quotes ({_QUOTE_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            quote.tenant_id, quote.quote_id, quote.account_id, quote.opportunity_id,
                            quote.quote_no, quote.status, quote.subtotal_cents, quote.tax_cents,
                            quote.total_cents, quote.valid_until, quote.confirmed_at,
                            quote.converted_contract_id, quote.owner_id, quote.created_at,
                            quote.updated_at, quote.deleted_at,
                        ),
                    )
                    self._insert_quote_lines(cursor, lines)
        return quote

    @staticmethod
    def _insert_quote_lines(cursor, lines: list[QuoteLine]) -> None:
        for line in lines:
            cursor.execute(
                f"INSERT INTO workbench_crm_quote_lines ({_QUOTE_LINE_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    line.tenant_id, line.quote_id, line.line_no, line.description, line.qty,
                    line.unit_price_cents, line.tax_rate_bp, line.line_subtotal_cents, line.line_tax_cents,
                ),
            )

    def get_quote(self, tenant_id: str, quote_id: str) -> Quote | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_QUOTE_COLUMNS} FROM workbench_crm_quotes "
                    "WHERE tenant_id = %s AND quote_id = %s AND deleted_at IS NULL",
                    (tenant_id, quote_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._quote(row)

    def update_quote(self, quote: Quote, lines: list[QuoteLine] | None = None) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_quotes
                        SET account_id = %s, opportunity_id = %s, status = %s, subtotal_cents = %s,
                            tax_cents = %s, total_cents = %s, valid_until = %s, confirmed_at = %s,
                            converted_contract_id = %s, owner_id = %s, updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND quote_id = %s
                        """,
                        (
                            quote.account_id, quote.opportunity_id, quote.status, quote.subtotal_cents,
                            quote.tax_cents, quote.total_cents, quote.valid_until, quote.confirmed_at,
                            quote.converted_contract_id, quote.owner_id, quote.updated_at,
                            quote.deleted_at, quote.tenant_id, quote.quote_id,
                        ),
                    )
                    if lines is not None:
                        cursor.execute(
                            "DELETE FROM workbench_crm_quote_lines WHERE tenant_id = %s AND quote_id = %s",
                            (quote.tenant_id, quote.quote_id),
                        )
                        self._insert_quote_lines(cursor, lines)

    def transition_quote_status(
        self, tenant_id: str, quote_id: str, *, from_status: str, to_status: str, at: datetime
    ) -> bool:
        """条件迁移（首写获胜）：仅当当前 status = from_status 时更新；返回是否生效。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_quotes
                        SET status = %s, updated_at = %s,
                            confirmed_at = CASE WHEN %s IN ('confirmed', 'converted')
                                                THEN COALESCE(confirmed_at, %s) ELSE confirmed_at END
                        WHERE tenant_id = %s AND quote_id = %s AND status = %s AND deleted_at IS NULL
                        """,
                        (to_status, at, to_status, at, tenant_id, quote_id, from_status),
                    )
                    return int(cursor.rowcount or 0) == 1

    def list_quote_lines(self, tenant_id: str, quote_id: str) -> list[QuoteLine]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_QUOTE_LINE_COLUMNS} FROM workbench_crm_quote_lines "
                    "WHERE tenant_id = %s AND quote_id = %s ORDER BY line_no",
                    (tenant_id, quote_id),
                )
                rows = cursor.fetchall()
        return [self._quote_line(row) for row in rows]

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
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        for column, value in (("owner_id", owner_id), ("account_id", account_id), ("status", status)):
            if value is not None:
                where.append(f"{column} = %s")
                params.append(value)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM workbench_crm_quotes WHERE {clause}", tuple(params))
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_QUOTE_COLUMNS} FROM workbench_crm_quotes WHERE {clause} "
                    "ORDER BY created_at DESC, quote_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._quote(row) for row in rows], total

    def count_quotes_with_prefix(self, tenant_id: str, prefix: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM workbench_crm_quotes WHERE tenant_id = %s AND quote_no LIKE %s",
                    (tenant_id, f"{prefix}%"),
                )
                return int(cursor.fetchone()[0])

    def convert_quote_atomic(self, quote: Quote, contract: Contract) -> None:
        """报价转合同（**单事务**）：建 Contract + 更新 Quote（converted / 回填合同 id）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_contracts ({_CONTRACT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            contract.tenant_id, contract.contract_id, contract.account_id,
                            contract.quote_id, contract.opportunity_id, contract.contract_no,
                            contract.title, contract.status, contract.amount_cents, contract.paid_cents,
                            contract.starts_on, contract.ends_on, contract.document_object_key,
                            contract.signed_at, contract.owner_id, contract.created_at,
                            contract.updated_at, contract.deleted_at,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE workbench_crm_quotes
                        SET status = %s, converted_contract_id = %s, updated_at = %s
                        WHERE tenant_id = %s AND quote_id = %s
                        """,
                        (
                            quote.status, quote.converted_contract_id, quote.updated_at,
                            quote.tenant_id, quote.quote_id,
                        ),
                    )

    # ------------------------------------------------------------ 合同

    def add_contract(self, contract: Contract) -> Contract:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_contracts ({_CONTRACT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            contract.tenant_id, contract.contract_id, contract.account_id,
                            contract.quote_id, contract.opportunity_id, contract.contract_no,
                            contract.title, contract.status, contract.amount_cents, contract.paid_cents,
                            contract.starts_on, contract.ends_on, contract.document_object_key,
                            contract.signed_at, contract.owner_id, contract.created_at,
                            contract.updated_at, contract.deleted_at,
                        ),
                    )
        return contract

    def get_contract(self, tenant_id: str, contract_id: str) -> Contract | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTRACT_COLUMNS} FROM workbench_crm_contracts "
                    "WHERE tenant_id = %s AND contract_id = %s AND deleted_at IS NULL",
                    (tenant_id, contract_id),
                )
                row = cursor.fetchone()
        return None if row is None else self._contract(row)

    def update_contract(self, contract: Contract) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_contracts
                        SET account_id = %s, quote_id = %s, opportunity_id = %s, title = %s,
                            status = %s, amount_cents = %s, paid_cents = %s, starts_on = %s,
                            ends_on = %s, document_object_key = %s, signed_at = %s, owner_id = %s,
                            updated_at = %s, deleted_at = %s
                        WHERE tenant_id = %s AND contract_id = %s
                        """,
                        (
                            contract.account_id, contract.quote_id, contract.opportunity_id,
                            contract.title, contract.status, contract.amount_cents, contract.paid_cents,
                            contract.starts_on, contract.ends_on, contract.document_object_key,
                            contract.signed_at, contract.owner_id, contract.updated_at,
                            contract.deleted_at, contract.tenant_id, contract.contract_id,
                        ),
                    )

    def increment_contract_paid(self, tenant_id: str, contract_id: str, *, delta_cents: int) -> bool:
        """回款原子增量累加（并发安全）；超 `amount_cents` 时不生效（返回 False）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_crm_contracts
                        SET paid_cents = paid_cents + %s, updated_at = now()
                        WHERE tenant_id = %s AND contract_id = %s AND deleted_at IS NULL
                          AND paid_cents + %s <= amount_cents
                        """,
                        (delta_cents, tenant_id, contract_id, delta_cents),
                    )
                    return int(cursor.rowcount or 0) == 1

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
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        for column, value in (("owner_id", owner_id), ("account_id", account_id), ("status", status)):
            if value is not None:
                where.append(f"{column} = %s")
                params.append(value)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM workbench_crm_contracts WHERE {clause}", tuple(params)
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_CONTRACT_COLUMNS} FROM workbench_crm_contracts WHERE {clause} "
                    "ORDER BY created_at DESC, contract_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._contract(row) for row in rows], total

    def list_contracts_for_accounts(self, tenant_id: str, account_ids: Iterable[str]) -> list[Contract]:
        keys = [str(key) for key in account_ids]
        if not keys:
            return []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTRACT_COLUMNS} FROM workbench_crm_contracts "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND account_id = ANY(%s)",
                    (tenant_id, keys),
                )
                rows = cursor.fetchall()
        return [self._contract(row) for row in rows]

    def list_contracts_in_renewal_window(self, tenant_id: str, *, from_date: date, until: date) -> list[Contract]:
        """续约窗口：`signed` 且 `from_date <= ends_on <= until`（已过期由 `list_expired_contracts` 承接）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTRACT_COLUMNS} FROM workbench_crm_contracts "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND status = 'signed' "
                    "AND ends_on IS NOT NULL AND ends_on >= %s AND ends_on <= %s "
                    "ORDER BY ends_on, contract_id",
                    (tenant_id, from_date, until),
                )
                rows = cursor.fetchall()
        return [self._contract(row) for row in rows]

    def list_expired_contracts(self, tenant_id: str, *, today: date) -> list[Contract]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_CONTRACT_COLUMNS} FROM workbench_crm_contracts "
                    "WHERE tenant_id = %s AND deleted_at IS NULL AND status = 'signed' "
                    "AND ends_on IS NOT NULL AND ends_on < %s ORDER BY ends_on, contract_id",
                    (tenant_id, today),
                )
                rows = cursor.fetchall()
        return [self._contract(row) for row in rows]

    def count_contracts_with_prefix(self, tenant_id: str, prefix: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM workbench_crm_contracts "
                    "WHERE tenant_id = %s AND contract_no LIKE %s",
                    (tenant_id, f"{prefix}%"),
                )
                return int(cursor.fetchone()[0])

    # ------------------------------------------------------------ 智能化记录（append-only）

    def add_insight(self, insight: Insight) -> Insight:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO workbench_crm_insights ({_INSIGHT_COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)",
                        (
                            insight.tenant_id, insight.insight_id, insight.account_id, insight.kind,
                            insight.input_digest, _json(insight.content), _json(insight.evidence_refs),
                            _json(insight.dropped_refs), insight.model_key, insight.generated_by,
                            insight.created_at,
                        ),
                    )
        return insight

    def list_insights(
        self, tenant_id: str, *, account_id: str, limit: int, offset: int
    ) -> tuple[list[Insight], int]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM workbench_crm_insights WHERE tenant_id = %s AND account_id = %s",
                    (tenant_id, account_id),
                )
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_INSIGHT_COLUMNS} FROM workbench_crm_insights "
                    "WHERE tenant_id = %s AND account_id = %s ORDER BY created_at DESC, insight_id "
                    "LIMIT %s OFFSET %s",
                    (tenant_id, account_id, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._insight(row) for row in rows], total

    # ------------------------------------------------------------ 目标

    def upsert_target(self, target: Target) -> Target:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_crm_targets
                            (tenant_id, target_id, owner_id, period_month, amount_target_cents, count_target)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, owner_id, period_month)
                        DO UPDATE SET amount_target_cents = EXCLUDED.amount_target_cents,
                                      count_target = EXCLUDED.count_target,
                                      updated_at = now()
                        RETURNING tenant_id, target_id, owner_id, period_month,
                                  amount_target_cents, count_target, created_at, updated_at, deleted_at
                        """,
                        (
                            target.tenant_id, target.target_id, target.owner_id, target.period_month,
                            target.amount_target_cents, target.count_target,
                        ),
                    )
                    row = cursor.fetchone()
        return self._target(row)

    def get_target(self, tenant_id: str, owner_id: str, period_month: date) -> Target | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_TARGET_COLUMNS} FROM workbench_crm_targets "
                    "WHERE tenant_id = %s AND owner_id = %s AND period_month = %s AND deleted_at IS NULL",
                    (tenant_id, owner_id, period_month),
                )
                row = cursor.fetchone()
        return None if row is None else self._target(row)

    def list_targets(
        self, tenant_id: str, *, owner_id: str | None = None, period_month: date | None = None, limit: int, offset: int
    ) -> tuple[list[Target], int]:
        where = ["tenant_id = %s", "deleted_at IS NULL"]
        params: list[object] = [tenant_id]
        if owner_id is not None:
            where.append("owner_id = %s")
            params.append(owner_id)
        if period_month is not None:
            where.append("period_month = %s")
            params.append(period_month)
        clause = " AND ".join(where)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM workbench_crm_targets WHERE {clause}", tuple(params))
                total = int(cursor.fetchone()[0])
                cursor.execute(
                    f"SELECT {_TARGET_COLUMNS} FROM workbench_crm_targets WHERE {clause} "
                    "ORDER BY period_month DESC, owner_id LIMIT %s OFFSET %s",
                    (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
                )
                rows = cursor.fetchall()
        return [self._target(row) for row in rows], total

    # ------------------------------------------------------------ 自定义字段元数据

    def upsert_field_def(self, definition: FieldDef) -> FieldDef:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workbench_crm_field_defs
                            (tenant_id, object_key, field_key, label, field_type, required, options, active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (tenant_id, object_key, field_key)
                        DO UPDATE SET label = EXCLUDED.label, field_type = EXCLUDED.field_type,
                                      required = EXCLUDED.required, options = EXCLUDED.options,
                                      active = EXCLUDED.active
                        """,
                        (
                            definition.tenant_id, definition.object_key, definition.field_key,
                            definition.label, definition.field_type, definition.required,
                            _json(list(definition.options)), definition.active,
                        ),
                    )
        return definition

    def list_field_defs(self, tenant_id: str, object_key: str) -> list[FieldDef]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_FIELD_DEF_COLUMNS} FROM workbench_crm_field_defs "
                    "WHERE tenant_id = %s AND object_key = %s ORDER BY field_key",
                    (tenant_id, object_key),
                )
                rows = cursor.fetchall()
        return [self._field_def(row) for row in rows]