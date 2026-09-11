from datetime import UTC, datetime

import pytest

from app.orchestration.models import (
    OrchestrationProposal,
    OrchestrationProposalKind,
    OrchestrationProposalNotFound,
    OrchestrationProposalStateConflict,
    OrchestrationProposalStatus,
)
from app.orchestration.store import InMemoryOrchestrationProposalStore


def proposal(
    *,
    tenant_id: str = "t-1",
    proposed: str = "agentscope",
    kind: OrchestrationProposalKind = OrchestrationProposalKind.RUNTIME_DEFAULT,
    created_at: datetime | None = None,
) -> OrchestrationProposal:
    return OrchestrationProposal(
        tenant_id=tenant_id,
        kind=kind,
        current_value="mock",
        proposed_value=proposed,
        rationale="理由",
        metrics_snapshot={
            "current": {"runtime_key": "mock", "run_count": 10},
            "proposed": {"runtime_key": "agentscope", "run_count": 10},
        },
        created_by="ceo-1",
        created_at=created_at or datetime(2026, 9, 11, tzinfo=UTC),
    )


def test_add_and_get_round_trip() -> None:
    store = InMemoryOrchestrationProposalStore()
    saved = store.add(proposal())

    assert store.get("t-1", saved.proposal_id) is saved


def test_get_rejects_cross_tenant_and_unknown() -> None:
    store = InMemoryOrchestrationProposalStore()
    saved = store.add(proposal())

    with pytest.raises(OrchestrationProposalNotFound):
        store.get("t-other", saved.proposal_id)
    with pytest.raises(OrchestrationProposalNotFound):
        store.get("t-1", "orch-missing")


def test_list_for_tenant_is_scoped_and_limited() -> None:
    store = InMemoryOrchestrationProposalStore()
    base = datetime(2026, 9, 11, tzinfo=UTC)
    store.add(proposal(proposed="a", created_at=base))
    store.add(proposal(proposed="b", created_at=base))
    store.add(proposal(tenant_id="t-other", proposed="c", created_at=base))

    items = store.list_for_tenant("t-1", limit=50)

    assert {item.proposed_value for item in items} == {"a", "b"}
    assert all(item.tenant_id == "t-1" for item in items)
    assert store.list_for_tenant("t-1", limit=1) == items[:1]


def test_find_pending_matches_kind_and_proposed_value() -> None:
    store = InMemoryOrchestrationProposalStore()
    saved = store.add(proposal())

    assert (
        store.find_pending("t-1", OrchestrationProposalKind.RUNTIME_DEFAULT, "agentscope") is saved
    )
    assert store.find_pending("t-1", OrchestrationProposalKind.RUNTIME_DEFAULT, "other") is None
    assert store.find_pending("t-other", OrchestrationProposalKind.RUNTIME_DEFAULT, "agentscope") is None


def test_find_pending_ignores_reviewed_proposals() -> None:
    store = InMemoryOrchestrationProposalStore()
    saved = store.add(proposal())
    store.mark_approved(saved.proposal_id, reviewer="ceo-1")

    assert store.find_pending("t-1", OrchestrationProposalKind.RUNTIME_DEFAULT, "agentscope") is None


def test_approve_and_reject_state_machine() -> None:
    store = InMemoryOrchestrationProposalStore()
    saved = store.add(proposal())

    approved = store.mark_approved(saved.proposal_id, reviewer="ceo-1")

    assert approved.status is OrchestrationProposalStatus.APPROVED
    assert approved.reviewed_by == "ceo-1"
    assert approved.reviewed_at is not None

    with pytest.raises(OrchestrationProposalStateConflict):
        store.mark_approved(saved.proposal_id, reviewer="ceo-2")

    other = store.add(proposal(proposed="next"))
    rejected = store.mark_rejected(other.proposal_id, reason="理由不足", reviewer="ceo-1")

    assert rejected.status is OrchestrationProposalStatus.REJECTED
    assert rejected.rejection_reason == "理由不足"

    with pytest.raises(OrchestrationProposalStateConflict):
        store.mark_rejected(other.proposal_id, reason="再来", reviewer="ceo-1")


def test_mark_approved_unknown_proposal_is_not_found() -> None:
    store = InMemoryOrchestrationProposalStore()

    with pytest.raises(OrchestrationProposalNotFound):
        store.mark_approved("orch-missing", reviewer="ceo-1")
