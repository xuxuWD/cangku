import pytest

from app.agent_services import DataClassification
from app.domain import RiskLevel
from app.planner.classification import classification_for_risk


@pytest.mark.parametrize(
    ("risk_level", "expected"),
    [
        (RiskLevel.LOW, DataClassification.INTERNAL),
        (RiskLevel.MEDIUM, DataClassification.CONFIDENTIAL),
        (RiskLevel.HIGH, DataClassification.RESTRICTED),
    ],
)
def test_classification_for_risk_maps_known_levels(risk_level: RiskLevel, expected: DataClassification) -> None:
    assert classification_for_risk(risk_level) is expected


@pytest.mark.parametrize("bad", ["low", "medium", "high", "unknown", None, 1, object()])
def test_classification_for_risk_fails_closed_on_invalid_input(bad: object) -> None:
    with pytest.raises(ValueError):
        classification_for_risk(bad)  # type: ignore[arg-type]


def test_every_declared_risk_level_has_a_classification() -> None:
    """新增风险档却忘了补分级映射 → 该档任务会被 fail-closed 拒绝规划。

    `critical` 与 `high` 同为最严档 RESTRICTED（分级本身只有三档，不另造一级）。
    """
    for risk_level in RiskLevel:
        assert classification_for_risk(risk_level) is not None
    assert classification_for_risk(RiskLevel.CRITICAL) is DataClassification.RESTRICTED
