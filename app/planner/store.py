from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
    PlanStepView,
)


class PlanProposalStore(Protocol):
    def add(self, proposal: PlanProposal) -> PlanProposal: ...
    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal: ...
    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None: ...
    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]: ...
    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal: ...
    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal: ...
    def mark_run_started(self, proposal_id: str, run_id: str) -> PlanProposal: ...


class InMemoryPlanProposalStore:
    """开发期内存仓储；状态流转在锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, PlanProposal] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def add(self, proposal: PlanProposal) -> PlanProposal:
        """写入提案；同一租户、任务与幂等键已存在时返回既有提案，不重复写入。"""
        key = (proposal.tenant_id, proposal.task_id, proposal.idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                return self._items[existing_id]
            self._items[proposal.proposal_id] = proposal
            self._idempotency[key] = proposal.proposal_id
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

    def mark_run_started(self, proposal_id: str, run_id: str) -> PlanProposal:
        with self._lock:
            item = self._by_id(proposal_id)
            item.run_id = run_id
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


class PostgresPlanProposalStore:
    """计划提案持久化；审批使用条件更新保证并发安全。"""

    _COLUMNS = (
        "proposal_id, task_id, tenant_id, goal, steps, generator_key, generator_model, "
        "created_by, idempotency_key, status, created_at, reviewed_by, reviewed_at, rejection_reason, run_id"
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
    def _hydrate(row: tuple) -> PlanProposal:
        raw_steps = row[4]
        if isinstance(raw_steps, str):
            raw_steps = json.loads(raw_steps)
        steps = tuple(
            PlanStepView(
                step_id=str(item["step_id"]),
                tool=str(item["tool"]),
                kind=str(item["kind"]),
                requires_approval=bool(item["requires_approval"]),
                args=dict(item.get("args") or {}),
            )
            for item in raw_steps
        )
        return PlanProposal(
            proposal_id=str(row[0]),
            task_id=str(row[1]),
            tenant_id=str(row[2]),
            goal=str(row[3]),
            steps=steps,
            generator_key=str(row[5]),
            generator_model=row[6],
            created_by=str(row[7]),
            idempotency_key=str(row[8]),
            status=PlanStatus(str(row[9])),
            created_at=row[10] if isinstance(row[10], datetime) else datetime.now(UTC),
            reviewed_by=row[11],
            reviewed_at=row[12],
            rejection_reason=row[13],
            run_id=row[14],
        )

    @staticmethod
    def _serialize(steps: tuple[PlanStepView, ...]) -> str:
        return json.dumps(
            [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "kind": step.kind,
                    "requires_approval": step.requires_approval,
                    "args": step.args,
                }
                for step in steps
            ],
            ensure_ascii=False,
        )

    def add(self, proposal: PlanProposal) -> PlanProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_plan_proposals ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, task_id, idempotency_key) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            proposal.proposal_id,
                            proposal.task_id,
                            proposal.tenant_id,
                            proposal.goal,
                            self._serialize(proposal.steps),
                            proposal.generator_key,
                            proposal.generator_model,
                            proposal.created_by,
                            proposal.idempotency_key,
                            proposal.status.value,
                            proposal.created_at,
                            proposal.reviewed_by,
                            proposal.reviewed_at,
                            proposal.rejection_reason,
                            proposal.run_id,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            f"""
                            SELECT {self._COLUMNS} FROM workbench_plan_proposals
                            WHERE tenant_id = %s AND task_id = %s AND idempotency_key = %s
                            """,
                            (proposal.tenant_id, proposal.task_id, proposal.idempotency_key),
                        )
                        row = cursor.fetchone()
        if row is None:
            raise PlanProposalNotFound(proposal.proposal_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE proposal_id = %s AND tenant_id = %s
                    """,
                    (proposal_id, tenant_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise PlanProposalNotFound(proposal_id)
        return self._hydrate(row)

    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE tenant_id = %s AND task_id = %s AND idempotency_key = %s
                    """,
                    (tenant_id, task_id, idempotency_key),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE tenant_id = %s AND task_id = %s ORDER BY created_at
                    """,
                    (tenant_id, task_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal:
        return self._review(proposal_id, reviewer=reviewer, status="approved", reason=None)

    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal:
        return self._review(proposal_id, reviewer=reviewer, status="rejected", reason=reason)

    def _review(self, proposal_id: str, *, reviewer: str, status: str, reason: str | None) -> PlanProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_plan_proposals
                        SET status = %s, reviewed_by = %s, reviewed_at = now(), rejection_reason = %s
                        WHERE proposal_id = %s AND status = 'pending_review'
                        RETURNING {self._COLUMNS}
                        """,
                        (status, reviewer, reason, proposal_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT proposal_id FROM workbench_plan_proposals WHERE proposal_id = %s",
                            (proposal_id,),
                        )
                        if cursor.fetchone() is None:
                            raise PlanProposalNotFound(proposal_id)
                        raise PlanProposalStateConflict("该提案当前状态不允许审批")
        return self._hydrate(row)

    def mark_run_started(self, proposal_id: str, run_id: str) -> PlanProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_plan_proposals
                        SET run_id = %s
                        WHERE proposal_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (run_id, proposal_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise PlanProposalNotFound(proposal_id)
        return self._hydrate(row)
