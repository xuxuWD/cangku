import pytest

from app.planner.models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)
from app.planner.store import InMemoryPlanProposalStore


def proposal(task_id: str = "task-1", *, idempotency_key: str = "id-1", created_by: str = "u-1") -> PlanProposal:
    return PlanProposal(
        task_id=task_id,
        tenant_id="t-1",
        goal="整理选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by=created_by,
        idempotency_key=idempotency_key,
    )


def test_add_and_get_roundtrip() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    assert store.get("t-1", saved.proposal_id) is saved


def test_get_rejects_other_tenant() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    with pytest.raises(PlanProposalNotFound):
        store.get("t-other", saved.proposal_id)


def test_find_by_idempotency_is_scoped_to_tenant_and_task() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    assert store.find_by_idempotency("t-1", "task-1", "id-1") is saved
    assert store.find_by_idempotency("t-1", "task-2", "id-1") is None
    assert store.find_by_idempotency("t-other", "task-1", "id-1") is None


def test_approve_only_from_pending_review() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    approved = store.mark_approved(saved.proposal_id, reviewer="ceo-1")

    assert approved.status is PlanStatus.APPROVED
    assert approved.reviewed_by == "ceo-1"
    assert approved.reviewed_at is not None
    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved(saved.proposal_id, reviewer="ceo-1")


def test_reject_records_reason_and_blocks_approval() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    rejected = store.mark_rejected(saved.proposal_id, reason="步骤不完整", reviewer="ceo-1")

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.rejection_reason == "步骤不完整"
    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved(saved.proposal_id, reviewer="ceo-1")


def test_mark_approved_rejects_unknown_proposal() -> None:
    store = InMemoryPlanProposalStore()

    with pytest.raises(PlanProposalNotFound):
        store.mark_approved("plan-missing", reviewer="ceo-1")


def test_list_for_task_is_tenant_scoped() -> None:
    store = InMemoryPlanProposalStore()
    store.add(proposal())
    store.add(proposal(idempotency_key="id-2"))

    assert len(store.list_for_task("t-1", "task-1")) == 2
    assert store.list_for_task("t-other", "task-1") == []
