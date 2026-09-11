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
