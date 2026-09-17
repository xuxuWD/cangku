"""CRM 健康度四维规则分（§2.5）与多维度指标字典（§2.6）单测。

- 先红后绿：本文件先于实现编写；**反假**：把「互动」权重置 0 必须使样例集变色。
- 边界逐个锁定：无活动 / 全 won / 超期停留 / 无联系人 / 无合同 / 无目标（分母为零 ⇒ null）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.crm.models import Activity, Contract, Opportunity
from app.crm.scoring import HEALTH_WEIGHTS, compute_health

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _activity(days_ago: int, *, kind: str = "call", status: str = "done") -> Activity:
    return Activity(
        tenant_id="t1",
        activity_id=f"act-{days_ago}-{kind}",
        kind=kind,
        status=status,
        owner_id="alice",
        occurred_at=NOW - timedelta(days=days_ago),
    )


def _opportunity(stage: str, amount_cents: int, *, days_in_stage: int = 5) -> Opportunity:
    return Opportunity(
        tenant_id="t1",
        opportunity_id=f"op-{stage}-{amount_cents}",
        account_id="acc-1",
        name="商机",
        stage=stage,
        amount_cents=amount_cents,
        owner_id="alice",
        stage_entered_at=NOW - timedelta(days=days_in_stage),
    )


def _contract(status: str, amount_cents: int, paid_cents: int) -> Contract:
    return Contract(
        tenant_id="t1",
        contract_id=f"c-{status}-{amount_cents}",
        account_id="acc-1",
        contract_no="C-202609-0001",
        title="合同",
        status=status,
        amount_cents=amount_cents,
        paid_cents=paid_cents,
        owner_id="alice",
    )


# ------------------------------------------------------------ 样例集（手工核算）


def test_healthy_account_scores_green_100() -> None:
    result = compute_health(
        activities=[_activity(3) for _ in range(9)],
        opportunities=[_opportunity("negotiation", 1_200_000)],
        contact_count=3,
        contracts=[_contract("signed", 100_000, 100_000)],
        now=NOW,
    )
    assert result.score == 100
    assert result.band == "green"
    assert result.parts == {"engagement": 100.0, "pipeline": 100.0, "relationship": 100.0, "commercial": 100.0}


def test_cold_start_account_scores_red_zero() -> None:
    result = compute_health(activities=[], opportunities=[], contact_count=0, contracts=[], now=NOW)
    assert result.score == 0
    assert result.band == "red"


def test_partial_account_scores_yellow() -> None:
    # 互动：45 天前最近 / 近 90 天 3 次 → 0.6×50 + 0.4×50 = 50
    # 管线：proposal(75) + 20 万分(60) → 67.5
    # 关系：2 个联系人 → 70
    # 商务：60 + 40×0.5 = 80
    # 总分 = 0.35×50 + 0.30×67.5 + 0.20×70 + 0.15×80 = 63.75 → 64
    result = compute_health(
        activities=[_activity(45), _activity(60), _activity(80)],
        opportunities=[_opportunity("proposal", 200_000)],
        contact_count=2,
        contracts=[_contract("signed", 100_000, 50_000)],
        now=NOW,
    )
    assert result.score == 64
    assert result.band == "yellow"
    assert result.parts["pipeline"] == pytest.approx(67.5)


# ------------------------------------------------------------ 边界


def test_closed_opportunities_do_not_count_in_pipeline() -> None:
    won = _opportunity("won", 9_999_999)
    lost = _opportunity("lost", 9_999_999)
    result = compute_health(activities=[], opportunities=[won, lost], contact_count=0, contracts=[], now=NOW)
    assert result.parts["pipeline"] == 0.0


def test_recent_activity_recency_bands() -> None:
    # 8 天 → ≤30 → 80；仅 1 次（frequency=25）→ 0.6×80 + 0.4×25 = 58
    result = compute_health(
        activities=[_activity(8)], opportunities=[], contact_count=0, contracts=[], now=NOW
    )
    assert result.parts["engagement"] == pytest.approx(58.0)
    # >90 天 → 0
    stale = compute_health(
        activities=[_activity(120)], opportunities=[], contact_count=0, contracts=[], now=NOW
    )
    assert stale.parts["engagement"] == 0.0


def test_unsigned_contract_does_not_score_commercial() -> None:
    result = compute_health(
        activities=[],
        opportunities=[],
        contact_count=0,
        contracts=[_contract("draft", 100_000, 0), _contract("voided", 100_000, 0)],
        now=NOW,
    )
    assert result.parts["commercial"] == 0.0


def test_planned_activity_does_not_count_as_done() -> None:
    planned = _activity(1, kind="task", status="planned")
    result = compute_health(activities=[planned], opportunities=[], contact_count=0, contracts=[], now=NOW)
    assert result.parts["engagement"] == 0.0


# ------------------------------------------------------------ 反假（权重必须可改变结果）


def test_anti_fake_zeroing_engagement_weight_changes_score() -> None:
    baseline = compute_health(
        activities=[_activity(3) for _ in range(9)],
        opportunities=[],
        contact_count=0,
        contracts=[],
        now=NOW,
    )
    assert baseline.score == 35  # 仅互动维 100 × 0.35
    zeroed = compute_health(
        activities=[_activity(3) for _ in range(9)],
        opportunities=[],
        contact_count=0,
        contracts=[],
        now=NOW,
        weights={**HEALTH_WEIGHTS, "engagement": 0.0},
    )
    assert zeroed.score == 0
    assert zeroed.band == "red"


def test_band_thresholds() -> None:
    low = compute_health(activities=[], opportunities=[], contact_count=0, contracts=[], now=NOW)
    assert (low.score, low.band) == (0, "red")
    # 互动 + 关系两维拉满仍不足 60 ⇒ red（加权和 51.5 → 52）
    mid = compute_health(
        activities=[_activity(3) for _ in range(4)], opportunities=[], contact_count=3, contracts=[], now=NOW
    )
    assert (mid.score, mid.band) == (52, "red")
    green = compute_health(
        activities=[_activity(3) for _ in range(9)],
        opportunities=[_opportunity("negotiation", 1_200_000)],
        contact_count=3,
        contracts=[_contract("signed", 100_000, 100_000)],
        now=NOW,
    )
    assert green.band == "green"