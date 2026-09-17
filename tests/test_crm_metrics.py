"""指标字典（§2.6）单测：分母为零返回 `null`（不编造）、受控口径逐项锚定。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.crm.metrics import compute_metrics
from app.crm.models import Account, Contract, Opportunity, StageEvent, Target

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _account(band: str | None) -> Account:
    return Account(
        tenant_id="t1", account_id=f"acc-{band}", name="客户", owner_id="alice", health_band=band,
        health_score=None if band is None else 80,
    )


def _opportunity(
    stage: str, amount_cents: int, *, created_days_ago: int = 10, closed_days_ago: int | None = None,
    in_stage_days: int = 5,
) -> Opportunity:
    return Opportunity(
        tenant_id="t1", opportunity_id=f"op-{stage}-{amount_cents}-{created_days_ago}", account_id="acc-1",
        name="商机", stage=stage, amount_cents=amount_cents, owner_id="alice",
        stage_entered_at=NOW - timedelta(days=in_stage_days),
        created_at=NOW - timedelta(days=created_days_ago),
        closed_at=None if closed_days_ago is None else NOW - timedelta(days=closed_days_ago),
    )


def _contract(status: str, amount: int, paid: int, *, ends_in_days: int | None = None) -> Contract:
    return Contract(
        tenant_id="t1", contract_id=f"c-{status}-{amount}-{paid}", account_id="acc-1",
        contract_no="C-202609-0001", title="合同", status=status, amount_cents=amount, paid_cents=paid,
        owner_id="alice",
        ends_on=None if ends_in_days is None else (NOW + timedelta(days=ends_in_days)).date(),
    )


def _event(source: str | None, sink: str) -> StageEvent:
    return StageEvent(
        tenant_id="t1", event_id=f"ev-{source}-{sink}", opportunity_id="op-1",
        from_stage=source, to_stage=sink, amount_cents=0, actor_id="alice",
    )


def test_no_target_yields_null_and_note() -> None:
    metrics = compute_metrics(
        opportunities=[], stage_events=[], contracts=[], accounts=[], target=None, now=NOW
    )
    assert metrics.pipeline_coverage is None and metrics.pipeline_coverage_note == "no_target"
    assert metrics.target_attainment_amount is None and metrics.target_note == "no_target"
    assert metrics.win_rate is None
    assert metrics.payment_progress is None


def test_core_metrics_with_full_sample() -> None:
    target = Target(
        tenant_id="t1", target_id="tgt-1", owner_id="alice", period_month=date(2026, 9, 1),
        amount_target_cents=1_000_000, count_target=10,
    )
    opportunities = [
        _opportunity("negotiation", 2_000_000, in_stage_days=15),   # 进行中
        _opportunity("proposal", 500_000, in_stage_days=5),          # 进行中
        _opportunity("won", 1_000_000, created_days_ago=40, closed_days_ago=10),  # 当月 won？closed 9/7 ✓
        _opportunity("lost", 300_000, created_days_ago=30, closed_days_ago=5),
    ]
    events = [
        _event(None, "qualification"),
        _event(None, "qualification"),
        _event(None, "qualification"),
        _event("qualification", "proposal"),
        _event("qualification", "proposal"),
        _event("proposal", "negotiation"),
    ]
    contracts = [
        _contract("signed", 1_000_000, 400_000, ends_in_days=60),    # 续约窗口内
        _contract("signed", 500_000, 500_000, ends_in_days=200),     # 不在窗口
        _contract("signed", 200_000, 0, ends_in_days=-3),            # 已到期未结清
    ]
    accounts = [_account("green"), _account("green"), _account("yellow"), _account("red"), _account(None)]

    metrics = compute_metrics(
        opportunities=opportunities, stage_events=events, contracts=contracts, accounts=accounts,
        target=target, now=NOW,
    )
    # 管线覆盖率 = (2,000,000 + 500,000) / 1,000,000 = 2.5
    assert metrics.pipeline_coverage == pytest.approx(2.5)
    assert metrics.pipeline_coverage_note == ""
    # 赢率 = 1 / 2 = 0.5
    assert metrics.win_rate == pytest.approx(0.5)
    # 销售周期：仅 1 个 won（40 - 10 = 30 天）
    assert metrics.sales_cycle_days == pytest.approx(30.0)
    # 阶段转化率：qualification→proposal = 2/3（进入 qualification 3 次）；proposal→negotiation = 1/2（进入 proposal 2 次）；negotiation→won = 0/1
    assert metrics.stage_conversion["qualification->proposal"] == pytest.approx(0.6667)
    assert metrics.stage_conversion["proposal->negotiation"] == pytest.approx(0.5)
    assert metrics.stage_conversion["negotiation->won"] == pytest.approx(0.0)
    # 管线账龄 = (15 + 5) / 2
    assert metrics.pipeline_age_days == pytest.approx(10.0)
    # 创建速率（近 30 天）：created 10 / 5 / 30 天前共 3 个（won 为 40 天前，不在窗口）
    assert metrics.creation_rate_30d == 3
    # 健康分档分布
    assert metrics.health_distribution == {"green": 2, "yellow": 1, "red": 1, "uncomputed": 1}
    # 续约窗口：1 个 / 1,000,000 分
    assert metrics.renewal_window_count == 1
    assert metrics.renewal_window_amount_cents == 1_000_000
    # 回款进度 = (400,000 + 500,000 + 0) / (1,000,000 + 500,000 + 200,000)
    assert metrics.payment_progress == pytest.approx(0.5294, abs=0.0001)
    assert metrics.overdue_contract_count == 1
    # 目标达成度：当月 won 1,000,000 / 1,000,000 = 1.0；单数 1 / 10 = 0.1
    assert metrics.target_attainment_amount == pytest.approx(1.0)
    assert metrics.target_attainment_count == pytest.approx(0.1)


def test_zero_denominators_return_null_not_fabricated() -> None:
    # 无已关闭商机 ⇒ 赢率 null；无阶段事件 ⇒ 转化率全 null；无 signed 合同 ⇒ 回款 null
    metrics = compute_metrics(
        opportunities=[_opportunity("qualification", 1000)], stage_events=[], contracts=[],
        accounts=[], target=None, now=NOW,
    )
    assert metrics.win_rate is None
    assert all(value is None for value in metrics.stage_conversion.values())
    assert metrics.payment_progress is None
    assert metrics.sales_cycle_days is None
    assert metrics.pipeline_age_days is not None  # 有进行中商机 ⇒ 有账龄


def test_as_dict_is_json_friendly() -> None:
    metrics = compute_metrics(
        opportunities=[], stage_events=[], contracts=[], accounts=[], target=None, now=NOW
    )
    payload = metrics.as_dict()
    assert payload["pipeline_coverage"] is None
    assert payload["health_distribution"] == {"green": 0, "yellow": 0, "red": 0, "uncomputed": 0}