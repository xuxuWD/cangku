"""CRM 报价金额引擎（§2.4）：纯函数、整数分、Decimal 精确、ROUND_HALF_UP。

- 行小计 = ROUND_HALF_UP(qty × unit_price_cents)
- 行税额 = ROUND_HALF_UP(line_subtotal_cents × tax_rate_bp ÷ 10000)
- 单据 subtotal / tax = 各行求和；total = subtotal + tax

全程**禁用 float**：入参 qty 经 `Decimal(str(value))` 归一（float 入参会先转字符串再解析，
但调用方应传 str / int / Decimal；测试含 0.1×3 类 float 陷阱样本，float 实现必然差 1 分）。
税率用万分比整数（13% = 1300），精度上限 4 位小数（即 0.01bp）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .models import (
    MAX_LINES_PER_QUOTE,
    MAX_TEXT_LENGTH,
    InvalidCrm,
    QuoteLine,
    normalize_text,
)

_QTY_QUANTUM = Decimal("0.001")
_MAX_QTY = Decimal("999999999.999")
_ONE = Decimal("1")
_TEN_THOUSAND = Decimal("10000")


def normalize_qty(value: object, *, field_name: str = "数量") -> Decimal:
    """归一数量为 Decimal（> 0，最多 3 位小数，上限 12 位整数部分）。"""
    if isinstance(value, bool):
        raise InvalidCrm(f"{field_name}不合法")
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InvalidCrm(f"{field_name}不合法") from None
    if not qty.is_finite():
        raise InvalidCrm(f"{field_name}不合法")
    if qty <= 0:
        raise InvalidCrm(f"{field_name}必须大于 0")
    if qty > _MAX_QTY:
        raise InvalidCrm(f"{field_name}超过上限")
    if qty.as_tuple().exponent < -3:
        raise InvalidCrm(f"{field_name}最多 3 位小数")
    return qty


def normalize_tax_rate_bp(value: object, *, field_name: str = "税率") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidCrm(f"{field_name}必须为万分比整数")
    if not 0 <= value <= 10000:
        raise InvalidCrm(f"{field_name}超出 0–10000 范围")
    return int(value)


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def compute_line(qty: Decimal, unit_price_cents: int, tax_rate_bp: int) -> tuple[int, int]:
    """计算单行（小计分, 税额分）；纯函数，先写单测再实现。"""
    subtotal = _round_cents(qty * Decimal(unit_price_cents))
    tax = _round_cents(Decimal(subtotal) * Decimal(tax_rate_bp) / _TEN_THOUSAND)
    return subtotal, tax


def build_lines(tenant_id: str, quote_id: str, raw_lines: list[dict]) -> list[QuoteLine]:
    """校验并构造报价行（行数上限 200；数量 / 单价 / 税率逐行校验；金额服务端重算）。"""
    if not isinstance(raw_lines, list) or not raw_lines:
        raise InvalidCrm("报价至少需要一行")
    if len(raw_lines) > MAX_LINES_PER_QUOTE:
        raise InvalidCrm(f"报价行数超过上限 {MAX_LINES_PER_QUOTE}")

    lines: list[QuoteLine] = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise InvalidCrm("报价行格式不合法")
        description = normalize_text(
            raw.get("description"), max_length=MAX_TEXT_LENGTH, required=True, field_name="行描述"
        )
        qty = normalize_qty(raw.get("qty"))
        unit_price = raw.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            raise InvalidCrm("单价必须为整数分且不为负")
        tax_rate_bp = normalize_tax_rate_bp(raw.get("tax_rate_bp", 0))
        subtotal, tax = compute_line(qty, unit_price, tax_rate_bp)
        lines.append(
            QuoteLine(
                tenant_id=tenant_id,
                quote_id=quote_id,
                line_no=index,
                description=description,
                qty=f"{qty:.3f}",
                unit_price_cents=unit_price,
                tax_rate_bp=tax_rate_bp,
                line_subtotal_cents=subtotal,
                line_tax_cents=tax,
            )
        )
    return lines


def compute_totals(lines: list[QuoteLine]) -> tuple[int, int, int]:
    """单据合计（subtotal, tax, total）。"""
    subtotal = sum(line.line_subtotal_cents for line in lines)
    tax = sum(line.line_tax_cents for line in lines)
    return subtotal, tax, subtotal + tax


def qty_from_line(line: QuoteLine) -> Decimal:
    """从落库行（qty 为规范化字符串）还原 Decimal。"""
    return Decimal(line.qty)