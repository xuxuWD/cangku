"""治理判定：自治等级 × 风险档 × 阈值的审批矩阵，含反假测试与「刻度只有一份」的守护。

背景：EvoFlow 完整源码研读（`docs/evoflow-source-study-and-adaptation-plan.md` §1.1）
查出 P1a 的 `full_auto` **完全免批且无兜底**。判定口径由段一规格
（`docs/superpowers/specs/2026-09-12-governance-closure-design.md` §2.2）定下，本文件守护之。
"""

from __future__ import annotations

import re
from itertools import product
from pathlib import Path

import pytest

from app.domain import RISK_ORDER, RiskLevel, risk_at_least
from app.workforce.models import (
    AUTONOMY_LEVELS,
    FALLBACK_RISKY_THRESHOLD,
    NEVER_EXEMPT_RISK,
    RISK_THRESHOLDS,
    needs_approval,
)

ROOT = Path(__file__).resolve().parents[1]

# 手写期望表（**不是照实现算出来的**），键为 自治等级 → 阈值 → 风险档 → 是否必须审批。
EXPECTED: dict[str, dict[str, dict[str, bool]]] = {
    # 一律审批：阈值不参与判定。
    "approval_for_all": {
        threshold: {"low": True, "medium": True, "high": True, "critical": True}
        for threshold in RISK_THRESHOLDS
    },
    # 按阈值：只在「风险不低于阈值」时要审批。
    "approval_for_risky": {
        "low": {"low": True, "medium": True, "high": True, "critical": True},
        "medium": {"low": False, "medium": True, "high": True, "critical": True},
        "high": {"low": False, "medium": False, "high": True, "critical": True},
        "critical": {"low": False, "medium": False, "high": False, "critical": True},
    },
    # 除 critical 外免批：阈值不参与判定。
    "full_auto": {
        threshold: {"low": False, "medium": False, "high": False, "critical": True}
        for threshold in RISK_THRESHOLDS
    },
}


@pytest.mark.parametrize(
    ("autonomy_level", "risk_threshold", "risk_level"),
    [(a, t, r) for a in AUTONOMY_LEVELS for t in RISK_THRESHOLDS for r in RISK_THRESHOLDS],
)
def test_approval_matrix(autonomy_level: str, risk_threshold: str, risk_level: str) -> None:
    assert (
        needs_approval(autonomy_level, risk_level, risk_threshold)
        is EXPECTED[autonomy_level][risk_threshold][risk_level]
    )


def test_critical_is_never_exempt_for_full_auto() -> None:
    """反假测试：把 `full_auto` 下的 `critical` 判成免批，本用例必须变红。

    真实的退化写法都会被它拦住，例如：① `full_auto` 分支里把 `critical` 也免掉；
    ② 兜底常量被删或被改成别的档。
    """
    assert needs_approval("full_auto", "critical", "high") is True
    assert needs_approval("full_auto", "critical", "critical") is True
    assert NEVER_EXEMPT_RISK == "critical"


def test_no_autonomy_level_exempts_critical() -> None:
    """任何自治等级、任何阈值配置下，`critical` 都必须审批。"""
    for autonomy_level, risk_threshold in product(AUTONOMY_LEVELS, RISK_THRESHOLDS):
        assert needs_approval(autonomy_level, NEVER_EXEMPT_RISK, risk_threshold) is True


@pytest.mark.parametrize(
    ("autonomy_level", "risk_level", "risk_threshold"),
    [
        ("auto_everything", "high", "high"),  # 未知自治等级
        ("full_auto", "extreme", "high"),  # 未知风险档
        ("", "", ""),
        ("full_auto", "CRITICAL", "high"),  # 大小写不同即未知，不做宽松回落
        ("full_auto", None, "high"),
        ("approval_for_risky", "low", "extreme"),  # 未知阈值 → 按最低档处理
        ("approval_for_risky", "medium", ""),
        ("approval_for_risky", "medium", None),
    ],
)
def test_unknown_values_fail_closed(autonomy_level: str, risk_level: str, risk_threshold: str) -> None:
    """未知取值一律要审批（fail-closed），不得被当成免批。"""
    assert needs_approval(autonomy_level, risk_level, risk_threshold) is True


def test_fallback_threshold_is_the_lowest_tier() -> None:
    """阈值取值非法时按最低档处理 = 一律审批（宁严不松）。"""
    assert FALLBACK_RISKY_THRESHOLD == RISK_THRESHOLDS[0]


def test_risk_scale_has_exactly_one_source() -> None:
    """刻度与序只能有一份：`workforce` 的阈值集合必须就是领域刻度的取值集合。"""
    assert RISK_THRESHOLDS == tuple(RISK_ORDER)
    assert list(RISK_ORDER) == [level.value for level in RiskLevel]
    # 序与枚举声明顺序一致（由低到高），且是稠密的 0..n-1
    assert [RISK_ORDER[level.value] for level in RiskLevel] == list(range(len(RiskLevel)))


def test_risk_at_least_treats_critical_as_at_least_high() -> None:
    """`critical` 必须算「不低于 high」——否则 critical 会绕过一切以 high 为界的闸门。"""
    assert risk_at_least(RiskLevel.CRITICAL, RiskLevel.HIGH) is True
    assert risk_at_least(RiskLevel.HIGH, RiskLevel.HIGH) is True
    assert risk_at_least(RiskLevel.MEDIUM, RiskLevel.HIGH) is False
    assert risk_at_least(RiskLevel.LOW, RiskLevel.LOW) is True


@pytest.mark.parametrize(
    ("migration", "column"),
    [
        ("024_governance_risk_levels.sql", "risk_threshold"),
        ("025_task_risk_level_critical.sql", "risk_level"),
    ],
)
def test_db_check_matches_risk_scale(migration: str, column: str) -> None:
    """数据库的 `CHECK` 取值集合必须与代码里的刻度**逐项相等**。

    防的正是「代码加了一档、迁移没跟上」这类漂移（`023` 的 `temperature` 就栽在这里）。
    """
    sql = (ROOT / "migrations" / migration).read_text(encoding="utf-8")
    match = re.search(rf"{column} IN \(([^)]*)\)", sql)
    assert match is not None, f"{migration} 未找到 {column} 的 IN 列表"
    values = tuple(item.strip().strip("'") for item in match.group(1).split(","))
    assert values == RISK_THRESHOLDS
