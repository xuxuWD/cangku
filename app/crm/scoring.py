"""CRM 健康度四维规则分（§2.5）：纯函数、可解释、**不做机器学习**。

四维（权重为模块级常量，可经 `weights` 参数替换以便单测）：
- 互动活跃度（0.35）：`0.6 × recency + 0.4 × frequency`
- 管线与金额（0.30）：取**最大进行中商机**：`0.5 × 阶段分 + 0.5 × 金额分`
- 关系面（0.20）：联系人覆盖数分档
- 商务与回款（0.15）：有 `signed` 合同 = 60 基础分 + 40 × 合同回款进度

分档：`green ≥ 80` / `yellow 60–79` / `red < 60`（阈值经评审可调）。
未计算 = NULL（由**调用方**决定是否落库；本函数只对给定集合出分）。
第五维「支持」slot 保留（二期工单上线后启用，§2.5 / §5-8）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import (
    HEALTH_BAND_GREEN,
    HEALTH_BAND_YELLOW,
    HEALTH_WEIGHTS,
    Activity,
    Contract,
    Opportunity,
)
from .models import now as _now

# 进行中阶段（已终止不计管线维）。
_ACTIVE_STAGES = frozenset({"qualification", "proposal", "negotiation"})
# 频率窗口（天）。
_FREQUENCY_WINDOW_DAYS = 90


@dataclass(frozen=True)
class HealthScore:
    score: int
    band: str
    parts: dict[str, float]


def _recency_score(days: int | None) -> float:
    if days is None:
        return 0.0
    if days <= 7:
        return 100.0
    if days <= 30:
        return 80.0
    if days <= 60:
        return 50.0
    if days <= 90:
        return 20.0
    return 0.0


def _frequency_score(count: int) -> float:
    if count >= 8:
        return 100.0
    if count >= 4:
        return 75.0
    if count >= 2:
        return 50.0
    if count >= 1:
        return 25.0
    return 0.0


def _stage_score(stage: str) -> float:
    return {"negotiation": 100.0, "proposal": 75.0, "qualification": 50.0}.get(stage, 0.0)


def _amount_score(amount_cents: int) -> float:
    if amount_cents >= 1_000_000:
        return 100.0
    if amount_cents >= 500_000:
        return 80.0
    if amount_cents >= 100_000:
        return 60.0
    if amount_cents >= 10_000:
        return 40.0
    if amount_cents > 0:
        return 20.0
    return 0.0


def _relationship_score(contact_count: int) -> float:
    if contact_count >= 3:
        return 100.0
    if contact_count == 2:
        return 70.0
    if contact_count == 1:
        return 40.0
    return 0.0


def _commercial_score(contracts: list[Contract]) -> float:
    signed = [c for c in contracts if c.status == "signed" and c.deleted_at is None]
    if not signed:
        return 0.0
    total = sum(c.amount_cents for c in signed)
    paid = sum(c.paid_cents for c in signed)
    progress = (paid / total) if total > 0 else 0.0
    return 60.0 + 40.0 * min(1.0, progress)


def compute_health(
    *,
    activities: list[Activity],
    opportunities: list[Opportunity],
    contact_count: int,
    contracts: list[Contract],
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> HealthScore:
    """四维加权到 0–100 整数；输入为**该客户**的活动 / 商机 / 联系人计数 / 合同。"""
    reference = now or _now()
    done = [a for a in activities if a.status == "done" and a.deleted_at is None]
    recent_days: int | None = None
    if done:
        latest = max(a.occurred_at for a in done)
        recent_days = max(0, (reference - latest).days)
    window_count = sum(1 for a in done if 0 <= (reference - a.occurred_at).days <= _FREQUENCY_WINDOW_DAYS)
    engagement = 0.6 * _recency_score(recent_days) + 0.4 * _frequency_score(window_count)

    active = [o for o in opportunities if o.stage in _ACTIVE_STAGES and o.deleted_at is None]
    pipeline = 0.0
    if active:
        best = max(active, key=lambda o: o.amount_cents)
        pipeline = 0.5 * _stage_score(best.stage) + 0.5 * _amount_score(best.amount_cents)

    relationship = _relationship_score(max(0, int(contact_count)))
    commercial = _commercial_score(contracts)

    effective = dict(HEALTH_WEIGHTS if weights is None else weights)
    raw = (
        effective.get("engagement", 0.0) * engagement
        + effective.get("pipeline", 0.0) * pipeline
        + effective.get("relationship", 0.0) * relationship
        + effective.get("commercial", 0.0) * commercial
    )
    score = max(0, min(100, round(raw)))
    band = "green" if score >= HEALTH_BAND_GREEN else ("yellow" if score >= HEALTH_BAND_YELLOW else "red")
    return HealthScore(
        score=score,
        band=band,
        parts={
            "engagement": round(engagement, 4),
            "pipeline": round(pipeline, 4),
            "relationship": round(relationship, 4),
            "commercial": round(commercial, 4),
        },
    )