"""CRM（P5a）**真库**回归（迁移 035）。

口径（沿用 `tests/test_memory_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**。
  - 目标库必须是**已完成全部迁移（含 035）**的库；本文件**不建表、不迁移**，缺表时**显式失败**。
  - 只操作本文件声明的两个租户数据，每个用例前后自清。
  - ✅ 本文件应纳入 `.github/workflows/ci.yml` 的 `postgres` job（与既有真库测试一并真跑）。

重点（规格 §4）：① 转化单事务**无半成品**；② 复合外键跨租户拒写；③ 阶段机「首写获胜」；
④ 报价金额往返（NUMERIC 精度）+ confirmed 冻结；⑤ 回款原子增量 + 上限；⑥ 敏感字段揭示审计不落值。
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from app.audit.models import AuditAction, build_record
from app.crm.models import Account, Contact, Opportunity, StageEvent, new_opportunity_id
from app.crm.service import CrmService
from app.crm.store_postgres import PostgresCrmStore
from app.domain import UserContext

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-crm-pg"
TENANT_OTHER = "test-crm-pg-other"
ALICE = "acct-crm-pg-alice"
BOB = "acct-crm-pg-bob"
CEO = "acct-crm-pg-ceo"

_PURGE_ORDER = (
    "workbench_crm_quote_lines",
    "workbench_crm_contracts",
    "workbench_crm_quotes",
    "workbench_crm_insights",
    "workbench_crm_opportunity_stage_events",
    "workbench_crm_activities",
    "workbench_crm_opportunities",
    "workbench_crm_contacts",
    "workbench_crm_leads",
    "workbench_crm_targets",
    "workbench_crm_field_defs",
    "workbench_crm_accounts",
)


class RecordingAudit:
    """走真实 `build_record`（审计白名单在真库测试内同样被强制执行）。"""

    def __init__(self) -> None:
        self.records: list = []

    def record(self, action, *, tenant_id=None, actor_id=None, target_type=None, target_id=None, detail=None):
        self.records.append(
            build_record(
                action,
                tenant_id=tenant_id,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
            )
        )


@pytest.fixture()
def env():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    audit = RecordingAudit()
    service = CrmService(PostgresCrmStore(connection), audit=audit)
    yield service, connection, audit
    _purge(connection)
    connection.close()


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        for table in _PURGE_ORDER:
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = %s OR tenant_id = %s", (TENANT, TENANT_OTHER))


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _bob() -> UserContext:
    return UserContext(TENANT, BOB, "employee")


def _ceo() -> UserContext:
    return UserContext(TENANT, CEO, "ceo")


# ------------------------------------------------------------ ① 转化单事务（无半成品）


def test_convert_lead_atomic_rolls_back_on_failure(env) -> None:
    service, _, _ = env
    psycopg = pytest.importorskip("psycopg")
    store = service.store
    lead = service.create_lead(_alice(), name="回滚测试", company="某某公司")

    account = Account(tenant_id=TENANT, account_id="acc-rollback", name="账户", owner_id=ALICE)
    contact = Contact(
        tenant_id=TENANT, contact_id="con-rollback", name="联系人", account_id="acc-rollback", owner_id=ALICE
    )
    # 构造违规：商机引用**不存在**的客户 ⇒ 复合外键失败 ⇒ 整个事务回滚
    bad = Opportunity(
        tenant_id=TENANT, opportunity_id="op-rollback", account_id="acc-missing", name="坏商机", owner_id=ALICE
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        store.convert_lead_atomic(lead, account, contact, bad)

    assert store.get_account(TENANT, "acc-rollback") is None
    assert store.get_contact(TENANT, "con-rollback") is None
    refreshed = store.get_lead(TENANT, lead.lead_id)
    assert refreshed is not None and refreshed.status == "open"


def test_convert_lead_success_roundtrip(env) -> None:
    service, _, audit = env
    lead = service.create_lead(_alice(), name="王小明", company="某某科技", phone="13800001234")
    account, contact, opportunity = service.convert_lead(
        _alice(), lead.lead_id, create_opportunity=True, opportunity_name="首单"
    )
    refreshed = service.get_lead(_alice(), lead.lead_id)
    assert refreshed.status == "converted"
    assert refreshed.converted_account_id == account.account_id
    events = service.list_stage_events(_alice(), opportunity.opportunity_id)
    assert len(events) == 1 and events[0].to_stage == "qualification"
    assert [r.action for r in audit.records].count(AuditAction.CRM_LEAD_CONVERTED) == 1
    assert contact.phone == "13800001234"  # 服务端存储保留原值（出口掩码在接口层）


def test_duplicate_convert_conflicts_and_cross_owner_hidden(env) -> None:
    from app.crm.models import CrmNotFound, CrmStateConflict

    service, _, _ = env
    lead = service.create_lead(_alice(), name="王小明")
    service.convert_lead(_alice(), lead.lead_id)
    with pytest.raises(CrmStateConflict):
        service.convert_lead(_alice(), lead.lead_id)
    other = service.create_lead(_bob(), name="他人线索")
    with pytest.raises(CrmNotFound):
        service.convert_lead(_alice(), other.lead_id)


# ------------------------------------------------------------ ② 复合外键跨租户拒写


def test_cross_tenant_foreign_key_rejected(env) -> None:
    service, connection, _ = env
    psycopg = pytest.importorskip("psycopg")
    other_account = Account(
        tenant_id=TENANT_OTHER, account_id="acc-other", name="他租户账户", owner_id="acct-other"
    )
    service.store.add_account(other_account)
    # 用**(本租户, 他租户 account_id)** 组合插入联系人 ⇒ 复合外键找不到匹配行 ⇒ 违规
    contact = Contact(
        tenant_id=TENANT, contact_id="con-cross", name="跨租户", account_id="acc-other", owner_id=ALICE
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        service.store.add_contact(contact)


# ------------------------------------------------------------ ③ 阶段机（首写获胜 + 事件）


def test_stage_machine_first_write_wins(env) -> None:
    service, _, audit = env
    account = service.create_account(_alice(), name="某某公司")
    opportunity = service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)
    store = service.store
    at = datetime.now(UTC)
    assert store.transition_opportunity_stage(
        TENANT, opportunity.opportunity_id, from_stage="qualification", to_stage="proposal", at=at
    )
    # 同 from 并发：第二次不生效（首写获胜）
    assert not store.transition_opportunity_stage(
        TENANT, opportunity.opportunity_id, from_stage="qualification", to_stage="lost", at=at
    )
    events = service.list_stage_events(_alice(), opportunity.opportunity_id)
    # 阶段事件由服务层 append（此处直接调 store 的迁移不写事件）⇒ 仅创建事件 1 条
    assert len(events) == 1
    # 服务层迁移（含事件 + 审计 + 终态 closed_at）
    updated = service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="negotiation")
    assert updated.stage == "negotiation"
    won = service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="won")
    assert won.stage == "won" and won.closed_at is not None
    events = service.list_stage_events(_alice(), opportunity.opportunity_id)
    assert [(e.from_stage, e.to_stage) for e in events] == [
        (None, "qualification"),
        ("proposal", "negotiation"),
        ("negotiation", "won"),
    ]
    assert [r.action for r in audit.records].count(AuditAction.CRM_OPPORTUNITY_STAGE_CHANGED) == 2


# ------------------------------------------------------------ ④ 报价往返（精度 + 冻结 + 转合同）


def test_quote_roundtrip_precision_freeze_and_convert(env) -> None:
    from app.crm.models import CrmStateConflict

    service, _, _ = env
    account = service.create_account(_ceo(), name="某某公司")
    quote = service.create_quote(
        _ceo(),
        account_id=account.account_id,
        lines=[
            {"description": "服务费", "qty": "2", "unit_price_cents": 50000, "tax_rate_bp": 1300},
            {"description": "实施费", "qty": "0.125", "unit_price_cents": 20000, "tax_rate_bp": 1300},
        ],
    )
    # 行 2：0.125 × 20000 = 2500 分；税 1300bp = 325 分
    assert (quote.subtotal_cents, quote.tax_cents, quote.total_cents) == (102500, 13325, 115825)
    lines = service.store.list_quote_lines(TENANT, quote.quote_id)
    assert [line.qty for line in lines] == ["2.000", "0.125"]
    assert [line.line_subtotal_cents for line in lines] == [100000, 2500]
    # 确认（confirmed_at 落库）→ 冻结
    confirmed = service.confirm_quote(_ceo(), quote.quote_id)
    assert confirmed.status == "confirmed" and confirmed.confirmed_at is not None
    with pytest.raises(CrmStateConflict):
        service.replace_quote_lines(
            _ceo(), quote.quote_id, lines=[{"description": "x", "qty": 1, "unit_price_cents": 1}]
        )
    # 转合同（单事务）
    contract = service.convert_quote_to_contract(_ceo(), quote.quote_id)
    assert contract.amount_cents == 115825
    refreshed = service.get_quote(_ceo(), quote.quote_id)
    assert refreshed.status == "converted" and refreshed.converted_contract_id == contract.contract_id


# ------------------------------------------------------------ ⑤ 合同回款（原子增量 + 上限）


def test_contract_payment_atomic_and_limit(env) -> None:
    from app.crm.models import CrmStateConflict

    service, _, audit = env
    account = service.create_account(_ceo(), name="某某公司")
    contract = service.create_contract(
        _ceo(), account_id=account.account_id, title="年度合同", amount_cents=100000,
        ends_on=date(2027, 9, 1),
    )
    service.submit_contract_for_sign(_ceo(), contract.contract_id)
    signed = service.register_signature(_ceo(), contract.contract_id, signed_at=datetime.now(UTC))
    assert signed.status == "signed"
    first = service.register_payment(_ceo(), contract.contract_id, amount_cents=40000)
    second = service.register_payment(_ceo(), contract.contract_id, amount_cents=60000)
    assert (first.paid_cents, second.paid_cents) == (40000, 100000)
    with pytest.raises(CrmStateConflict):
        service.register_payment(_ceo(), contract.contract_id, amount_cents=1)
    records = [r for r in audit.records if r.action is AuditAction.CRM_CONTRACT_PAYMENT_REGISTERED]
    assert len(records) == 2


# ------------------------------------------------------------ ⑥ 敏感字段揭示（审计不落值）


def test_reveal_sensitive_audits_without_value(env) -> None:
    from app.crm.models import CrmNotFound

    service, _, audit = env
    account = service.create_account(_alice(), name="某某公司")
    contact = service.create_contact(
        _alice(), name="王小明", account_id=account.account_id, phone="13800001234", email="ming@corp.cn"
    )
    assert service.reveal_sensitive(_alice(), entity="contact", entity_id=contact.contact_id, field="phone") == "13800001234"
    with pytest.raises(CrmNotFound):
        service.reveal_sensitive(_bob(), entity="contact", entity_id=contact.contact_id, field="phone")
    reveal_records = [r for r in audit.records if r.action is AuditAction.CRM_SENSITIVE_REVEALED]
    assert len(reveal_records) == 1
    payload = str([r.detail for r in audit.records])
    assert "13800001234" not in payload and "ming@corp.cn" not in payload


# ------------------------------------------------------------ ⑦ 自定义字段白名单（含 field_defs 落库）


def test_custom_fields_whitelist_roundtrip(env) -> None:
    from app.crm.models import InvalidCrm

    service, _, _ = env
    service.upsert_field_def(
        _ceo(), object_key="account", field_key="tier", label="客户分级", field_type="select",
        options=["A", "B", "C"],
    )
    account = service.create_account(_alice(), name="某某公司", custom_fields={"tier": "A"})
    assert account.custom_fields == {"tier": "A"}
    refreshed = service.get_account(_alice(), account.account_id)
    assert refreshed.custom_fields == {"tier": "A"}
    # 未定义键 / 越权取值 / 类型不符
    with pytest.raises(InvalidCrm):
        service.create_account(_alice(), name="另一家", custom_fields={"unknown_key": "x"})
    with pytest.raises(InvalidCrm):
        service.create_account(_alice(), name="另一家", custom_fields={"tier": "Z"})


# ------------------------------------------------------------ ⑧ 目标（管理角色 + UPSERT）


def test_target_upsert_and_role_gate(env) -> None:
    from app.domain import PolicyError

    service, _, _ = env
    with pytest.raises(PolicyError):
        service.set_target(_alice(), owner_id=ALICE, period_month=date(2026, 9, 1))
    first = service.set_target(
        _ceo(), owner_id=ALICE, period_month=date(2026, 9, 15), amount_target_cents=1000000, count_target=10
    )
    assert first.period_month == date(2026, 9, 1)  # 归一为月首日
    second = service.set_target(
        _ceo(), owner_id=ALICE, period_month=date(2026, 9, 1), amount_target_cents=2000000, count_target=20
    )
    assert second.amount_target_cents == 2000000
    items, total = service.list_targets(_ceo(), period_month=date(2026, 9, 1))
    assert total == 1 and items[0].count_target == 20
    # 员工只读自己的目标
    own, own_total = service.list_targets(_alice())
    assert own_total == 1 and own[0].owner_id == ALICE


def test_stage_event_model_helper_used_in_tests(env) -> None:
    """（占位一致性）StageEvent 构造与 new_opportunity_id 在真库下可往返。"""
    service, _, _ = env
    account = service.create_account(_alice(), name="某某公司")
    opportunity_id = new_opportunity_id()
    service.store.add_opportunity(
        Opportunity(
            tenant_id=TENANT, opportunity_id=opportunity_id, account_id=account.account_id,
            name="直插商机", owner_id=ALICE,
        )
    )
    event = StageEvent(
        tenant_id=TENANT, event_id="ev-direct", opportunity_id=opportunity_id, from_stage=None,
        to_stage="qualification", amount_cents=0, actor_id=ALICE,
    )
    service.store.append_stage_event(event)
    assert len(service.store.list_stage_events(TENANT, opportunity_id)) == 1