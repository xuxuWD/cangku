from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)


class PlanProposalStore(Protocol):
    def add(self, proposal: PlanProposal) -> PlanProposal: ...
    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal: ...
    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None: ...
    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]: ...
    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal: ...
    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal: ...


class InMemoryPlanProposalStore:
    """开发期内存仓储；状态流转在锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, PlanProposal] = {}
        self._lock = RLock()

    def add(self, proposal: PlanProposal) -> PlanProposal:
        with self._lock:
            self._items[proposal.proposal_id] = proposal
            return proposal

    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        with self._lock:
            return self._require(tenant_id, proposal_id)

    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None:
        with self._lock:
            for item in self._items.values():
                if (
                    item.tenant_id == tenant_id
                    and item.task_id == task_id
                    and item.idempotency_key == idempotency_key
                ):
                    return item
            return None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]:
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.task_id == task_id
            ]

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal:
        with self._lock:
            item = self._by_id(proposal_id)
            if item.status is not PlanStatus.PENDING_REVIEW:
                raise PlanProposalStateConflict("该提案当前状态不允许审批")
            item.status = PlanStatus.APPROVED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            return item

    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal:
        with self._lock:
            item = self._by_id(proposal_id)
            if item.status is not PlanStatus.PENDING_REVIEW:
                raise PlanProposalStateConflict("该提案当前状态不允许审批")
            item.status = PlanStatus.REJECTED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            item.rejection_reason = reason
            return item

    def _require(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        item = self._items.get(proposal_id)
        if item is None or item.tenant_id != tenant_id:
            raise PlanProposalNotFound(proposal_id)
        return item

    def _by_id(self, proposal_id: str) -> PlanProposal:
        item = self._items.get(proposal_id)
        if item is None:
            raise PlanProposalNotFound(proposal_id)
        return item
