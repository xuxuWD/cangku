from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import (
    OrchestrationProposal,
    OrchestrationProposalKind,
    OrchestrationProposalNotFound,
    OrchestrationProposalStateConflict,
    OrchestrationProposalStatus,
)


class OrchestrationProposalStore(Protocol):
    def add(self, proposal: OrchestrationProposal) -> OrchestrationProposal: ...
    def get(self, tenant_id: str, proposal_id: str) -> OrchestrationProposal: ...
    def list_for_tenant(self, tenant_id: str, *, limit: int) -> list[OrchestrationProposal]: ...
    def find_pending(
        self, tenant_id: str, kind: OrchestrationProposalKind, proposed_value: str
    ) -> OrchestrationProposal | None: ...
    def mark_approved(self, proposal_id: str, *, reviewer: str) -> OrchestrationProposal: ...
    def mark_rejected(
        self, proposal_id: str, *, reason: str, reviewer: str
    ) -> OrchestrationProposal: ...


class InMemoryOrchestrationProposalStore:
    """开发期内存仓储；审批状态流转在锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, OrchestrationProposal] = {}
        self._lock = RLock()

    def add(self, proposal: OrchestrationProposal) -> OrchestrationProposal:
        with self._lock:
            self._items[proposal.proposal_id] = proposal
            return proposal

    def get(self, tenant_id: str, proposal_id: str) -> OrchestrationProposal:
        with self._lock:
            item = self._items.get(proposal_id)
            if item is None or item.tenant_id != tenant_id:
                raise OrchestrationProposalNotFound(proposal_id)
            return item

    def list_for_tenant(self, tenant_id: str, *, limit: int) -> list[OrchestrationProposal]:
        with self._lock:
            items = [item for item in self._items.values() if item.tenant_id == tenant_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def find_pending(
        self, tenant_id: str, kind: OrchestrationProposalKind, proposed_value: str
    ) -> OrchestrationProposal | None:
        with self._lock:
            matches = [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id
                and item.kind == kind
                and item.proposed_value == proposed_value
                and item.status is OrchestrationProposalStatus.PENDING_REVIEW
            ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.created_at)

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> OrchestrationProposal:
        with self._lock:
            item = self._require_pending(proposal_id)
            item.status = OrchestrationProposalStatus.APPROVED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            return item

    def mark_rejected(
        self, proposal_id: str, *, reason: str, reviewer: str
    ) -> OrchestrationProposal:
        with self._lock:
            item = self._require_pending(proposal_id)
            item.status = OrchestrationProposalStatus.REJECTED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            item.rejection_reason = reason
            return item

    def _require_pending(self, proposal_id: str) -> OrchestrationProposal:
        item = self._items.get(proposal_id)
        if item is None:
            raise OrchestrationProposalNotFound(proposal_id)
        if item.status is not OrchestrationProposalStatus.PENDING_REVIEW:
            raise OrchestrationProposalStateConflict("该优化提案当前状态不允许审批")
        return item


class PostgresOrchestrationProposalStore:
    """优化提案持久化；审批使用条件更新保证并发安全。"""

    _COLUMNS = (
        "proposal_id, tenant_id, kind, current_value, proposed_value, rationale, "
        "metrics_snapshot, status, created_by, created_at, reviewed_by, reviewed_at, rejection_reason"
    )

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> OrchestrationProposal:
        raw_snapshot = row[6]
        if isinstance(raw_snapshot, str):
            raw_snapshot = json.loads(raw_snapshot)
        return OrchestrationProposal(
            proposal_id=str(row[0]),
            tenant_id=str(row[1]),
            kind=OrchestrationProposalKind(str(row[2])),
            current_value=str(row[3]),
            proposed_value=str(row[4]),
            rationale=str(row[5]),
            metrics_snapshot=dict(raw_snapshot or {}),
            status=OrchestrationProposalStatus(str(row[7])),
            created_by=str(row[8]),
            created_at=row[9] if isinstance(row[9], datetime) else datetime.now(UTC),
            reviewed_by=row[10],
            reviewed_at=row[11],
            rejection_reason=row[12],
        )

    def add(self, proposal: OrchestrationProposal) -> OrchestrationProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_orchestration_proposals ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            proposal.proposal_id,
                            proposal.tenant_id,
                            proposal.kind.value,
                            proposal.current_value,
                            proposal.proposed_value,
                            proposal.rationale,
                            json.dumps(proposal.metrics_snapshot, ensure_ascii=False),
                            proposal.status.value,
                            proposal.created_by,
                            proposal.created_at,
                            proposal.reviewed_by,
                            proposal.reviewed_at,
                            proposal.rejection_reason,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise OrchestrationProposalNotFound(proposal.proposal_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, proposal_id: str) -> OrchestrationProposal:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_orchestration_proposals
                    WHERE proposal_id = %s AND tenant_id = %s
                    """,
                    (proposal_id, tenant_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise OrchestrationProposalNotFound(proposal_id)
        return self._hydrate(row)

    def list_for_tenant(self, tenant_id: str, *, limit: int) -> list[OrchestrationProposal]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_orchestration_proposals
                    WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s
                    """,
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def find_pending(
        self, tenant_id: str, kind: OrchestrationProposalKind, proposed_value: str
    ) -> OrchestrationProposal | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_orchestration_proposals
                    WHERE tenant_id = %s AND kind = %s AND proposed_value = %s
                      AND status = 'pending_review'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (tenant_id, kind.value, proposed_value),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> OrchestrationProposal:
        return self._review(proposal_id, reviewer=reviewer, status="approved", reason=None)

    def mark_rejected(
        self, proposal_id: str, *, reason: str, reviewer: str
    ) -> OrchestrationProposal:
        return self._review(proposal_id, reviewer=reviewer, status="rejected", reason=reason)

    def _review(
        self, proposal_id: str, *, reviewer: str, status: str, reason: str | None
    ) -> OrchestrationProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_orchestration_proposals
                        SET status = %s, reviewed_by = %s, reviewed_at = now(), rejection_reason = %s
                        WHERE proposal_id = %s AND status = 'pending_review'
                        RETURNING {self._COLUMNS}
                        """,
                        (status, reviewer, reason, proposal_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT proposal_id FROM workbench_orchestration_proposals WHERE proposal_id = %s",
                            (proposal_id,),
                        )
                        if cursor.fetchone() is None:
                            raise OrchestrationProposalNotFound(proposal_id)
                        raise OrchestrationProposalStateConflict("该优化提案当前状态不允许审批")
        return self._hydrate(row)
