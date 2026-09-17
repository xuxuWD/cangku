"""CRM 纯函数单测（P5a §2.2 / §2.4）：掩码 / 剥离 / 金额引擎。

- 掩码与剥离为**敏感字段四件套**的出口；金额引擎为报价冻结的前置。
- 反假：float 陷阱样本（`2.675 × 100`）在 float 实现下必然差 1 分（Decimal 实现必须通过）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.crm.masking import mask_email, mask_record, mask_sensitive_fields, to_safe_dict
from app.crm.models import Contact, InvalidCrm, Lead
from app.crm.pricing import build_lines, compute_line, compute_totals, normalize_qty


# ------------------------------------------------------------ 掩码（§2.2）


def test_mask_email_keeps_domain_and_first_char() -> None:
    assert mask_email("alice@example.com") == "a***@example.com"


def test_mask_email_degenerate_inputs() -> None:
    assert mask_email("") == ""
    assert mask_email("no-at-sign") == "*" * len("no-at-sign")


def test_mask_email_missing_local_or_domain_is_fully_masked() -> None:
    assert mask_email("@missing-local.com") == "*" * len("@missing-local.com")
    assert mask_email("missing-domain@") == "*" * len("missing-domain@")


def test_mask_record_masks_only_sensitive_fields() -> None:
    contact = Contact(
        tenant_id="t1", contact_id="c1", name="张三", phone="13800001234", email="zhang@corp.cn",
        title="采购经理",
    )
    masked = mask_record(contact)
    assert masked["phone"] == "138****1234"
    assert masked["email"] == "z***@corp.cn"
    assert masked["name"] == "张三"
    assert masked["title"] == "采购经理"


def test_to_safe_dict_strips_sensitive_fields_entirely() -> None:
    lead = Lead(tenant_id="t1", lead_id="l1", name="李四", phone="13900002345", email="li@corp.cn")
    safe = to_safe_dict(lead)
    assert "phone" not in safe
    assert "email" not in safe
    assert safe["name"] == "李四"


def test_to_safe_dict_only_applies_to_registered_sensitive_objects() -> None:
    from app.crm.models import Account

    account = Account(tenant_id="t1", account_id="a1", name="某某公司")
    safe = to_safe_dict(account)
    assert safe["name"] == "某某公司"


def test_mask_sensitive_fields_on_plain_dict() -> None:
    payload = {"phone": "13800001234", "email": "a@b.cn", "name": "王五"}
    masked = mask_sensitive_fields("contact", payload)
    assert masked["phone"] == "138****1234"
    assert masked["email"] == "a***@b.cn"
    assert masked["name"] == "王五"
    # 未登记对象原样返回
    assert mask_sensitive_fields("account", payload) == payload


# ------------------------------------------------------------ 金额引擎（§2.4）


def test_normalize_qty_accepts_int_str_decimal() -> None:
    assert normalize_qty(2) == Decimal("2")
    assert normalize_qty("1.500") == Decimal("1.500")
    assert normalize_qty(Decimal("0.25")) == Decimal("0.25")


@pytest.mark.parametrize("bad", [0, -1, "abc", True, "0.0001", "1e30"])
def test_normalize_qty_rejects_invalid(bad) -> None:
    with pytest.raises(InvalidCrm):
        normalize_qty(bad)


def test_compute_line_round_half_up() -> None:
    assert compute_line(Decimal("2"), 10000, 1300) == (20000, 2600)
    assert compute_line(Decimal("0.5"), 9999, 0) == (5000, 0)  # 4999.5 → 5000（ROUND_HALF_UP）


def test_compute_line_float_trap() -> None:
    """反假样本：`2.675 × 100 = 267.5` → ROUND_HALF_UP = 268；float 实现会得 267（差 1 分）。"""
    subtotal, _ = compute_line(Decimal("2.675"), 100, 0)
    assert subtotal == 268


def test_compute_line_tax_rounding() -> None:
    # 行小计 10000 分，税率 650 bp（6.5%）⇒ 650 分
    assert compute_line(Decimal("1"), 10000, 650) == (10000, 650)
    # 行小计 101 分，税率 1300 ⇒ 13.13 → 13
    assert compute_line(Decimal("1"), 101, 1300) == (101, 13)


def test_build_lines_recomputes_totals_on_server() -> None:
    lines = build_lines(
        "t1",
        "q1",
        [
            {"description": "服务费", "qty": "2", "unit_price_cents": 50000, "tax_rate_bp": 1300},
            {"description": "实施费", "qty": "0.5", "unit_price_cents": 20000, "tax_rate_bp": 1300},
        ],
    )
    assert [line.line_no for line in lines] == [1, 2]
    subtotal, tax, total = compute_totals(lines)
    # 行1：100000 / 13000；行2：10000 / 1300
    assert (subtotal, tax, total) == (110000, 14300, 124300)


def test_build_lines_rejects_over_limit_and_bad_rows() -> None:
    with pytest.raises(InvalidCrm):
        build_lines("t1", "q1", [])
    with pytest.raises(InvalidCrm):
        build_lines("t1", "q1", [{"description": "", "qty": 1, "unit_price_cents": 1}])
    with pytest.raises(InvalidCrm):
        build_lines("t1", "q1", [{"description": "x", "qty": 1, "unit_price_cents": -1}])
    with pytest.raises(InvalidCrm):
        build_lines("t1", "q1", [{"description": "x", "qty": 1, "unit_price_cents": 1, "tax_rate_bp": 10001}])
    too_many = [{"description": f"行{i}", "qty": 1, "unit_price_cents": 1} for i in range(201)]
    with pytest.raises(InvalidCrm):
        build_lines("t1", "q1", too_many)