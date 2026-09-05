import pytest

from app.agent_services import (
    GrowthProposalStore,
    MemoryScope,
    MemoryStore,
    ModelGateway,
    ModelNotAllowed,
    ProposalNotFound,
    ProviderModel,
)


def test_model_gateway_uses_approved_fallback_for_text() -> None:
    gateway = ModelGateway(
        [
            ProviderModel("primary", {"text"}, sensitive_data=False, enabled=True),
            ProviderModel("fallback", {"text"}, sensitive_data=False, enabled=True),
        ]
    )

    route = gateway.choose(capability="text", data_classification="internal", preferred="missing")

    assert route.model_key == "primary"
    assert route.reason == "capability_default"


def test_sensitive_data_never_falls_back_to_model_that_forbids_it() -> None:
    gateway = ModelGateway(
        [
            ProviderModel("external", {"text"}, sensitive_data=False, enabled=True),
        ]
    )

    with pytest.raises(ModelNotAllowed):
        gateway.choose(capability="text", data_classification="sensitive")
    with pytest.raises(ModelNotAllowed):
        gateway.choose(capability="text", data_classification="restricted")
    with pytest.raises(ModelNotAllowed):
        gateway.choose(capability="text", data_classification="top_secret")


def test_memory_isolated_by_scope_and_can_be_promoted_after_review() -> None:
    memories = MemoryStore()
    memories.remember("tenant-1", "agent-1", MemoryScope.USER, "u-1", "偏好简洁表达")
    memories.remember("tenant-2", "agent-1", MemoryScope.USER, "u-1", "另一租户内容")
    memories.remember("tenant-1", "agent-1", MemoryScope.PROJECT, "p-1", "本项目使用中文界面")

    assert memories.list_for("tenant-1", "agent-1", MemoryScope.USER, "u-1") == ["偏好简洁表达"]
    assert memories.list_for("tenant-1", "agent-1", MemoryScope.USER, "u-2") == []
    assert memories.list_for("tenant-2", "agent-1", MemoryScope.USER, "u-1") == ["另一租户内容"]
    assert memories.list_for("tenant-1", "agent-1", MemoryScope.PROJECT, "p-1") == ["本项目使用中文界面"]

    proposal = memories.propose_promotion("tenant-1", "agent-1", "偏好简洁表达", source="task-1")
    assert proposal.status == "pending_review"
    assert memories.approve_promotion(proposal.id, tenant_id="tenant-1", reviewer="admin-1") == "approved"


def test_growth_proposal_requires_review_before_activation() -> None:
    proposals = GrowthProposalStore()
    proposal = proposals.create(
        agent_key="content-operator",
        kind="prompt",
        summary="更少使用技术术语",
        diff="将输出语言调整为普通员工能理解的中文",
    )

    assert proposals.activate(proposal.id) == "pending_review"
    assert proposals.review(proposal.id, reviewer="admin-1", approved=True) == "approved"
    assert proposals.activate(proposal.id) == "active"


def test_model_capabilities_are_immutable_and_invalid_proposal_is_not_found() -> None:
    capabilities = {"text"}
    model = ProviderModel("safe", capabilities, sensitive_data=True)
    capabilities.add("video")
    assert model.capabilities == frozenset({"text"})

    with pytest.raises(ProposalNotFound):
        GrowthProposalStore().activate("missing")
