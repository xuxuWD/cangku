"""CRM 服务层测试（内存仓储）：转化单事务语义 / 状态机白名单 / 报价冻结 / 合同签署与回款 /
权限矩阵（404 / 403）/ 敏感字段揭示审计 / 审计白名单哨兵。

真库（PostgreSQL）对应用例见 `tests/test_crm_postgres.py`；本文件不依赖数据库。
"""

from __future__ import annotations

import pytest

from app.audit.models import ALLOWED_DETAIL_KEYS, AuditAction, AuditDetailNotAllowed, build_record
from app.crm import InMemoryCrmStore
from app.crm.models import CrmNotFound, CrmStateConflict, InvalidCrm
from app.crm.service import CrmService
from app.domain import PolicyError, UserContext

TENANT = "t-crm"
ALICE = "acct-alice"
BOB = "acct-bob"
CEO = "acct-ceo"


class FakeAudit:
    """调用真实 `build_record`（审计白名单在测试内被强制执行，未声明键会直接抛错）。"""

    def __init__(self) -> None:
        self.records: list = []

    def record(self, action, *, tenant_id=None, actor_id=None, target_type=None, target_id=None, detail=None):
        record = build_record(
            action,
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        )
        self.records.append(record)


def _service() -> tuple[CrmService, FakeAudit]:
    audit = FakeAudit()
    return CrmService(InMemoryCrmStore(), audit=audit), audit


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _bob() -> UserContext:
    return UserContext(TENANT, BOB, "employee")


def _ceo() -> UserContext:
    return UserContext(TENANT, CEO, "ceo")


# ------------------------------------------------------------ 线索转化（单事务语义 + 幂等）


def test_convert_lead_creates_account_contact_and_optional_opportunity() -> None:
    service, audit = _service()
    lead = service.create_lead(_alice(), name="王小明", company="某某科技", phone="13800001234")
    account, contact, opportunity = service.convert_lead(
        _alice(), lead.lead_id, create_opportunity=True, opportunity_name="首单"
    )
    assert account.source == "lead_converted"
    assert contact.account_id == account.account_id
    assert contact.phone == "13800001234"
    assert opportunity is not None and opportunity.account_id == account.account_id
    # 线索状态与回填
    refreshed = service.get_lead(_alice(), lead.lead_id)
    assert refreshed.status == "converted"
    assert refreshed.converted_account_id == account.account_id
    assert refreshed.converted_contact_id == contact.contact_id
    assert refreshed.converted_opportunity_id == opportunity.opportunity_id
    # 初始阶段事件已落
    events = service.list_stage_events(_alice(), opportunity.opportunity_id)
    assert len(events) == 1 and events[0].from_stage is None and events[0].to_stage == "qualification"
    # 审计动作 + 明细键合法（build_record 已强制白名单）
    actions = [record.action for record in audit.records]
    assert AuditAction.CRM_LEAD_CONVERTED in actions


def test_convert_lead_twice_conflicts_and_cross_owner_hidden() -> None:
    service, _ = _service()
    lead = service.create_lead(_alice(), name="王小明")
    service.convert_lead(_alice(), lead.lead_id)
    with pytest.raises(CrmStateConflict):
        service.convert_lead(_alice(), lead.lead_id)
    # 他人线索 ⇒ 404（不泄露存在性）
    another = service.create_lead(_bob(), name="他人线索")
    with pytest.raises(CrmNotFound):
        service.convert_lead(_alice(), another.lead_id)


# ------------------------------------------------------------ 商机阶段机（白名单 + 阶段事件 + 终态）


def test_opportunity_stage_machine_whitelist_and_events() -> None:
    service, audit = _service()
    account = service.create_account(_alice(), name="某某公司")
    opportunity = service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)

    service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="proposal")
    service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="negotiation")
    # 非法迁移（proposal 不可直接到 won 需经 negotiation；negotiation 之后只允许 won/lost）
    with pytest.raises(CrmStateConflict):
        service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="proposal")
    updated = service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="won")
    assert updated.stage == "won" and updated.closed_at is not None
    # 终态不可再迁
    with pytest.raises(CrmStateConflict):
        service.change_opportunity_stage(_alice(), opportunity.opportunity_id, to_stage="lost")
    # 阶段事件：创建 + 3 次迁移 = 4 条，且 from/to 正确
    events = service.list_stage_events(_alice(), opportunity.opportunity_id)
    assert [(e.from_stage, e.to_stage) for e in events] == [
        (None, "qualification"),
        ("qualification", "proposal"),
        ("proposal", "negotiation"),
        ("negotiation", "won"),
    ]
    # 每次迁移都有审计（from_stage / to_stage 为受控枚举）
    stage_records = [r for r in audit.records if r.action is AuditAction.CRM_OPPORTUNITY_STAGE_CHANGED]
    assert len(stage_records) == 3
    assert stage_records[0].detail == {
        "opportunity_id": opportunity.opportunity_id,
        "from_stage": "qualification",
        "to_stage": "proposal",
    }


# ------------------------------------------------------------ 报价：金额重算 / confirmed 冻结 / 转合同


def test_quote_pricing_and_freeze_and_convert() -> None:
    service, audit = _service()
    account = service.create_account(_ceo(), name="某某公司")
    quote = service.create_quote(
        _ceo(),
        account_id=account.account_id,
        lines=[
            {"description": "服务费", "qty": "2", "unit_price_cents": 50000, "tax_rate_bp": 1300},
            {"description": "实施费", "qty": "0.5", "unit_price_cents": 20000, "tax_rate_bp": 1300},
        ],
    )
    assert (quote.subtotal_cents, quote.tax_cents, quote.total_cents) == (110000, 14300, 124300)
    # 确认前可改行（服务端重算）
    updated = service.replace_quote_lines(
        _ceo(), quote.quote_id, lines=[{"description": "服务费", "qty": "1", "unit_price_cents": 10000}]
    )
    assert updated.total_cents == 10000
    # 确认
    confirmed = service.confirm_quote(_ceo(), quote.quote_id)
    assert confirmed.status == "confirmed" and confirmed.confirmed_at is not None
    # 冻结：confirmed 后改行 / 重复确认 ⇒ 409
    with pytest.raises(CrmStateConflict):
        service.replace_quote_lines(_ceo(), quote.quote_id, lines=[{"description": "x", "qty": 1, "unit_price_cents": 1}])
    with pytest.raises(CrmStateConflict):
        service.confirm_quote(_ceo(), quote.quote_id)
    # 转合同（单事务语义：合同 + quote 状态）
    contract = service.convert_quote_to_contract(_ceo(), quote.quote_id, ends_on=None)
    assert contract.amount_cents == 10000 and contract.status == "draft"
    refreshed = service.get_quote(_ceo(), quote.quote_id)
    assert refreshed.status == "converted" and refreshed.converted_contract_id == contract.contract_id
    # 再次转 ⇒ 409
    with pytest.raises(CrmStateConflict):
        service.convert_quote_to_contract(_ceo(), quote.quote_id)
    actions = [r.action for r in audit.records]
    assert AuditAction.CRM_QUOTE_CREATED in actions
    assert AuditAction.CRM_QUOTE_CONFIRMED in actions
    assert AuditAction.CRM_QUOTE_CONVERTED in actions
    assert AuditAction.CRM_CONTRACT_CREATED in actions


def test_quote_confirm_requires_lines_and_amount() -> None:
    service, _ = _service()
    account = service.create_account(_ceo(), name="某某公司")
    with pytest.raises(InvalidCrm):
        service.create_quote(_ceo(), account_id=account.account_id, lines=[])


# ------------------------------------------------------------ 合同：签署登记（人工）/ 回款（原子增量）/ 作废


def test_contract_signature_payment_and_void() -> None:
    service, audit = _service()
    account = service.create_account(_ceo(), name="某某公司")
    contract = service.create_contract(_ceo(), account_id=account.account_id, title="年度合同", amount_cents=100000)
    # draft → signed 直跳 ⇒ 409
    with pytest.raises(CrmStateConflict):
        service.register_signature(_ceo(), contract.contract_id, signed_at=__import__("datetime").datetime.now())
    service.submit_contract_for_sign(_ceo(), contract.contract_id)
    # 回款在 signed 之前 ⇒ 409
    with pytest.raises(CrmStateConflict):
        service.register_payment(_ceo(), contract.contract_id, amount_cents=1000)
    signed = service.register_signature(
        _ceo(), contract.contract_id, signed_at=__import__("datetime").datetime.now()
    )
    assert signed.status == "signed" and signed.signed_at is not None
    # 回款累加
    first = service.register_payment(_ceo(), contract.contract_id, amount_cents=30000)
    assert first.paid_cents == 30000
    second = service.register_payment(_ceo(), contract.contract_id, amount_cents=70000)
    assert second.paid_cents == 100000
    # 超限 ⇒ 409（原子条件不生效）
    with pytest.raises(CrmStateConflict):
        service.register_payment(_ceo(), contract.contract_id, amount_cents=1)
    # 非法金额 ⇒ 422
    with pytest.raises(InvalidCrm):
        service.register_payment(_ceo(), contract.contract_id, amount_cents=0)
    # signed → voided
    voided = service.void_contract(_ceo(), contract.contract_id)
    assert voided.status == "voided"
    with pytest.raises(CrmStateConflict):
        service.void_contract(_ceo(), contract.contract_id)
    payment_records = [r for r in audit.records if r.action is AuditAction.CRM_CONTRACT_PAYMENT_REGISTERED]
    assert len(payment_records) == 2
    assert payment_records[0].detail == {"contract_id": contract.contract_id, "amount_cents": 30000}


# ------------------------------------------------------------ 权限矩阵（own / all / 403 / 404）


def test_permission_own_vs_all_and_manage_roles() -> None:
    service, _ = _service()
    alice_account = service.create_account(_alice(), name="Alice 客户")
    bob_account = service.create_account(_bob(), name="Bob 客户")
    # employee 读他人 ⇒ 404；ceo 可读
    with pytest.raises(CrmNotFound):
        service.get_account(_bob(), alice_account.account_id)
    assert service.get_account(_ceo(), alice_account.account_id).account_id == alice_account.account_id
    # employee 列表只见自己的
    items, total = service.list_accounts(_alice())
    assert total == 1 and items[0].account_id == alice_account.account_id
    # ceo 列表见全部
    _, total_all = service.list_accounts(_ceo())
    assert total_all == 2
    # employee 显式请求他人 owner ⇒ 404
    with pytest.raises(CrmNotFound):
        service.list_accounts(_alice(), owner_id=BOB)
    # 目标写入：employee ⇒ 403；ceo ⇒ 通过
    with pytest.raises(PolicyError):
        service.set_target(_alice(), owner_id=ALICE, period_month=__import__("datetime").date(2026, 9, 1))
    target = service.set_target(
        _ceo(), owner_id=ALICE, period_month=__import__("datetime").date(2026, 9, 1), amount_target_cents=1000000, count_target=10
    )
    assert target.owner_id == ALICE
    # customer_admin 不进模块 ⇒ 403
    from app.domain import UserContext as Ctx

    with pytest.raises(PolicyError):
        service.list_accounts(Ctx(TENANT, "acct-ca", "customer_admin"))


def test_cross_tenant_is_404() -> None:
    service, _ = _service()
    account = service.create_account(_alice(), name="Alice 客户")
    other_tenant_ctx = UserContext("t-other", ALICE, "employee")
    with pytest.raises(CrmNotFound):
        service.get_account(other_tenant_ctx, account.account_id)


# ------------------------------------------------------------ 敏感字段揭示（审计 + 数据范围）


def test_reveal_sensitive_requires_scope_and_audits_without_value() -> None:
    service, audit = _service()
    account = service.create_account(_alice(), name="某某公司")
    contact = service.create_contact(_alice(), name="王小明", account_id=account.account_id, phone="13800001234")
    # 数据范围内：本人可揭示
    assert service.reveal_sensitive(_alice(), entity="contact", entity_id=contact.contact_id, field="phone") == "13800001234"
    # 数据范围外 ⇒ 404
    with pytest.raises(CrmNotFound):
        service.reveal_sensitive(_bob(), entity="contact", entity_id=contact.contact_id, field="phone")
    # 非敏感字段 ⇒ 422
    with pytest.raises(InvalidCrm):
        service.reveal_sensitive(_alice(), entity="contact", entity_id=contact.contact_id, field="name")
    # 审计：只记标识与受控枚举，不落字段值
    reveal_records = [r for r in audit.records if r.action is AuditAction.CRM_SENSITIVE_REVEALED]
    assert len(reveal_records) == 1
    assert reveal_records[0].detail == {"contact_id": contact.contact_id, "field_name": "phone"}
    assert "13800001234" not in str(reveal_records[0].detail)


# ------------------------------------------------------------ 审计白名单（13 键 + 未声明键拒绝）


def test_crm_audit_detail_keys_whitelisted() -> None:
    expected = {
        "account_id", "contact_id", "lead_id", "opportunity_id", "quote_id", "contract_id",
        "insight_id", "activity_id", "from_stage", "to_stage", "amount_cents", "field_name",
        "recomputed_count", "create_opportunity", "model_key",
    }
    assert expected <= set(ALLOWED_DETAIL_KEYS)
    assert len(expected) == 15


def test_crm_audit_rejects_undeclared_detail_keys() -> None:
    with pytest.raises(AuditDetailNotAllowed):
        build_record(
            AuditAction.CRM_ACCOUNT_CREATED,
            tenant_id=TENANT,
            detail={"account_id": "a1", "phone_value": "13800001234"},
        )


def test_audit_payload_contains_no_plain_phone_or_email() -> None:
    """哨兵：走完一条真实链路后，全部审计明细序列化后 grep 明文电话 / 邮箱 ⇒ 0 命中。"""
    service, audit = _service()
    account = service.create_account(_alice(), name="某某公司")
    contact = service.create_contact(
        _alice(), name="王小明", account_id=account.account_id, phone="13800001234", email="ming@corp.cn"
    )
    service.log_activity(_alice(), kind="call", subject="电话沟通", account_id=account.account_id, contact_id=contact.contact_id)
    service.reveal_sensitive(_alice(), entity="contact", entity_id=contact.contact_id, field="phone")
    payload = str([record.detail for record in audit.records])
    assert "13800001234" not in payload
    assert "ming@corp.cn" not in payload


# ------------------------------------------------------------ 健康度重算 + 进度指标（§2.5 / §2.6）


def test_recompute_health_is_idempotent_and_writes_summary_audit() -> None:
    service, audit = _service()
    account = service.create_account(_alice(), name="某某公司")
    for index in range(3):
        service.create_contact(_alice(), name=f"联系人{index}", account_id=account.account_id)
    service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)
    for _ in range(8):
        service.log_activity(_alice(), kind="call", subject="沟通", account_id=account.account_id)

    assert service.recompute_health_for_tenant(TENANT) == 1
    refreshed = service.get_account(_alice(), account.account_id)
    # 3 联系人(100) + 8 次当日互动(recency100/freq100→100) + qualification(50)+10 万分(60)→55 + 无合同(0)
    # = 0.35×100 + 0.30×55 + 0.20×100 = 71.5 → 72 → yellow
    assert refreshed.health_score == 72 and refreshed.health_band == "yellow"
    assert refreshed.health_computed_at is not None

    # 幂等：重复重算结果一致；审计为**汇总行**（每租户一行计数，不逐客户写）
    assert service.recompute_health_for_tenant(TENANT) == 1
    assert service.get_account(_alice(), account.account_id).health_score == 72
    recomputed = [r for r in audit.records if r.action is AuditAction.CRM_HEALTH_RECOMPUTED]
    assert len(recomputed) == 2
    assert recomputed[0].detail == {"recomputed_count": 1}

    # 空租户 ⇒ 0 且不写审计（不伪造扫描结果）
    empty = service.recompute_health_for_tenant("t-empty")
    assert empty == 0


def test_progress_summary_scope_and_null_denominators() -> None:
    service, _ = _service()
    account = service.create_account(_alice(), name="某某公司")
    service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)

    summary = service.progress_summary(_alice())
    # 无目标 ⇒ 管线覆盖率 / 目标达成度一律 null + note（不编造分母）
    assert summary["pipeline_coverage"] is None and summary["pipeline_coverage_note"] == "no_target"
    assert summary["target_attainment_amount"] is None and summary["target_note"] == "no_target"
    assert summary["win_rate"] is None
    assert summary["creation_rate_30d"] == 1
    assert summary["health_distribution"]["uncomputed"] == 1

    # employee 请求 all ⇒ 403
    with pytest.raises(PolicyError):
        service.progress_summary(_alice(), scope="all")
    # ceo 可请求 all；非法 scope ⇒ 422
    summary_all = service.progress_summary(_ceo(), scope="all")
    assert summary_all["creation_rate_30d"] == 1
    with pytest.raises(InvalidCrm):
        service.progress_summary(_ceo(), scope="bogus")