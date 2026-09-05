import pytest

from app.capabilities import CapabilityPolicy, CapabilityState
from app.domain import PolicyError, UserContext


def test_high_risk_capabilities_require_review_instead_of_direct_enable() -> None:
    policy = CapabilityPolicy()
    admin = UserContext("t-1", "admin", "super_admin")

    for capability in (
        "third_party_skill_install",
        "shell_execution",
        "privileged_sandbox",
        "knowledge_write",
        "prompt_update",
        "workflow_update",
    ):
        decision = policy.authorize(admin, capability, environment="production")
        assert decision.state == CapabilityState.REVIEW_REQUIRED


def test_approved_changes_are_scoped_and_cannot_be_granted_to_regular_employees() -> None:
    policy = CapabilityPolicy()
    employee = UserContext("t-1", "u-1", "employee")
    admin = UserContext("t-1", "admin", "super_admin")

    with pytest.raises(PolicyError):
        policy.authorize(employee, "workflow_update", environment="production", approved=True)
    with pytest.raises(PolicyError):
        policy.authorize(admin, "shell_execution", environment="production", approved=True)

    allowed = policy.authorize(
        admin,
        "knowledge_write",
        environment="staging",
        approved=True,
        scope="draft",
    )
    assert allowed.state == CapabilityState.ALLOWED


def test_unknown_capability_is_denied() -> None:
    with pytest.raises(PolicyError, match="未知能力"):
        CapabilityPolicy().authorize(UserContext("t-1", "admin", "super_admin"), "unknown")
