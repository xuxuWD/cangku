"""CRM 多维度进度指标（§2.6 的 P5a 子集）：纯函数、分母为零一律 `null`（不编造）。

指标：管线覆盖率 / 赢率 / 销售周期 / 阶段转化率 / 管线账龄 / 管线创建速率 / 健康分档分布 /
续约窗口 / 回款进度 / 目标达成度。SLA 与发票相关指标归二期（无数据源）。

`scope` 过滤（me / all）由**服务层**在传入集合前完成（仓储查询带 owner 过滤），本模块只做聚合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .models import Account, Contract, Opportunity, StageEvent, Target
from .models import now as _now
from .scoring import _ACTIVE_STAGES

_CREATION_WINDOW_DAYS = 30
_STAGE_PAIRS = (
    ("qualification", "proposal"),
    ("proposal", "negotiation"),
    ("negotiation", "won"),
)


@dataclass(frozen=True)
class Metrics:
    pipeline_coverage: float | None
    pipeline_coverage_note: str
    win_rate: float | None
    sales_cycle_days: float | None
    stage_conversion: dict[str, float | None]
    pipeline_age_days: float | None
    creation_rate_30d: int
    health_distribution: dict[str, int]
    renewal_window_count: int
    renewal_window_amount_cents: int
    payment_progress: float | None
    overdue_contract_count: int
    target_attainment_amount: float | None
    target_attainment_count: float | None
    target_note: str
    generated_at: datetime = field(default_factory=_now)

    def as_dict(self) -> dict:
        return {
            "pipeline_coverage": self.pipeline_coverage,
            "pipeline_coverage_note": self.pipeline_coverage_note,
            "win_rate": self.win_rate,
            "sales_cycle_days": self.sales_cycle_days,
            "stage_conversion": self.stage_conversion,
            "pipeline_age_days": self.pipeline_age_days,
            "creation_rate_30d": self.creation_rate_30d,
            "health_distribution": self.health_distribution,
            "renewal_window_count": self.renewal_window_count,
            "renewal_window_amount_cents": self.renewal_window_amount_cents,
            "payment_progress": self.payment_progress,
            "overdue_contract_count": self.overdue_contract_count,
            "target_attainment_amount": self.target_attainment_amount,
            "target_attainment_count": self.target_attainment_count,
            "target_note": self.target_note,
        }


def _month_start(value: date) -> date:
    return value.replace(day=1)


def compute_metrics(
    *,
    opportunities: list[Opportunity],
    stage_events: list[StageEvent],
    contracts: list[Contract],
    accounts: list[Account],
    target: Target | None,
    now: datetime | None = None,
) -> Metrics:
    reference = now or _now()
    today = reference.date() if isinstance(reference, datetime) else reference
    active = [o for o in opportunities if o.stage in _ACTIVE_STAGES and o.deleted_at is None]
    closed = [o for o in opportunities if o.stage in ("won", "lost") and o.deleted_at is None]
    won = [o for o in closed if o.stage == "won"]

    # 目标（当月）
    target_amount = target.amount_target_cents if target is not None else 0
    target_count = target.count_target if target is not None else 0
    has_target = target is not None and (target_amount > 0 or target_count > 0)

    # 管线覆盖率
    if not has_target or target_amount <= 0:
        pipeline_coverage = None
        pipeline_note = "no_target"
    else:
        pipeline_coverage = round(sum(o.amount_cents for o in active) / target_amount, 4)
        pipeline_note = ""

    # 赢率
    win_rate = round(len(won) / len(closed), 4) if closed else None

    # 销售周期（仅 won）
    cycles = [
        (o.closed_at - o.created_at).total_seconds() / 86400
        for o in won
        if o.closed_at is not None and o.created_at is not None
    ]
    sales_cycle_days = round(sum(cycles) / len(cycles), 2) if cycles else None

    # 阶段转化率（相邻对：进入下一阶段数 ÷ 进入本阶段数）
    stage_conversion: dict[str, float | None] = {}
    for source, sink in _STAGE_PAIRS:
        entered_source = sum(1 for e in stage_events if e.to_stage == source)
        advanced = sum(1 for e in stage_events if e.from_stage == source and e.to_stage == sink)
        stage_conversion[f"{source}->{sink}"] = round(advanced / entered_source, 4) if entered_source else None

    # 管线账龄（进行中）
    ages = [(reference - o.stage_entered_at).total_seconds() / 86400 for o in active]
    pipeline_age_days = round(sum(ages) / len(ages), 2) if ages else None

    # 创建速率（近 30 天）
    creation_rate_30d = sum(
        1 for o in opportunities if o.deleted_at is None and (reference - o.created_at).days <= _CREATION_WINDOW_DAYS
    )

    # 健康分档分布
    distribution = {"green": 0, "yellow": 0, "red": 0, "uncomputed": 0}
    for account in accounts:
        if account.deleted_at is not None:
            continue
        if account.health_band in ("green", "yellow", "red"):
            distribution[account.health_band] += 1
        else:
            distribution["uncomputed"] += 1

    # 续约窗口（未来 90 天内到期的 signed 合同）
    renewal = [
        c
        for c in contracts
        if c.deleted_at is None
        and c.status == "signed"
        and c.ends_on is not None
        and 0 <= (c.ends_on - today).days <= 90
    ]

    # 回款进度（signed 合同口径）+ 已到期未结清
    signed = [c for c in contracts if c.deleted_at is None and c.status == "signed"]
    total_amount = sum(c.amount_cents for c in signed)
    total_paid = sum(c.paid_cents for c in signed)
    payment_progress = round(total_paid / total_amount, 4) if total_amount > 0 else None
    overdue_contract_count = sum(
        1 for c in signed if c.ends_on is not None and c.ends_on < today and c.paid_cents < c.amount_cents
    )

    # 目标达成度（当月 won）
    month = _month_start(today)
    won_this_month = [o for o in won if o.closed_at is not None and _month_start(o.closed_at.date()) == month]
    if not has_target:
        target_attainment_amount = None
        target_attainment_count = None
        target_note = "no_target"
    else:
        target_attainment_amount = (
            round(sum(o.amount_cents for o in won_this_month) / target_amount, 4) if target_amount > 0 else None
        )
        target_attainment_count = (
            round(len(won_this_month) / target_count, 4) if target_count > 0 else None
        )
        target_note = ""

    return Metrics(
        pipeline_coverage=pipeline_coverage,
        pipeline_coverage_note=pipeline_note,
        win_rate=win_rate,
        sales_cycle_days=sales_cycle_days,
        stage_conversion=stage_conversion,
        pipeline_age_days=pipeline_age_days,
        creation_rate_30d=creation_rate_30d,
        health_distribution=distribution,
        renewal_window_count=len(renewal),
        renewal_window_amount_cents=sum(c.amount_cents for c in renewal),
        payment_progress=payment_progress,
        overdue_contract_count=overdue_contract_count,
        target_attainment_amount=target_attainment_amount,
        target_attainment_count=target_attainment_count,
        target_note=target_note,
    )