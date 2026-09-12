from __future__ import annotations

from app.agent_services import DataClassification
from app.domain import RiskLevel

PLAN_GENERATION_CAPABILITY = "plan_generation"

_RISK_CLASSIFICATION: dict[RiskLevel, DataClassification] = {
    RiskLevel.LOW: DataClassification.INTERNAL,
    RiskLevel.MEDIUM: DataClassification.CONFIDENTIAL,
    RiskLevel.HIGH: DataClassification.RESTRICTED,
    # `critical` 是最严档：与 `high` 同为 RESTRICTED（分级只有三档，不再另造一级）。
    RiskLevel.CRITICAL: DataClassification.RESTRICTED,
}


def classification_for_risk(risk_level: RiskLevel) -> DataClassification:
    """把服务端的任务风险等级映射为数据分级；未知或非法输入一律 fail-closed。"""
    if not isinstance(risk_level, RiskLevel):
        raise ValueError("未知的任务风险等级，已拒绝规划")
    try:
        return _RISK_CLASSIFICATION[risk_level]
    except KeyError as exc:
        raise ValueError("未知的任务风险等级，已拒绝规划") from exc
