"""S2 运行验收决议（`workbench_run_acceptance_decisions`，迁移 `040`）：**append-only** 决议历史。

性质（契约「运行验收决议（S2 · 人工验收）」）：

    - **人的结论**：记录「谁在什么时候把这次交付判为已确认 / 已打回（含理由）」；
      与机器结论（`app/runtime/acceptance.py` 的结构判定，**纯函数不落库**）分开存放；
    - **只记录**：不改运行状态、不触发重跑、不发通知；
    - **幂等**：同租户同 `idempotency_key` 重放返回既有行（`created=False`），不产生第二行；
    - **append-only + 不设保留期**：打回 → 重做 → 再确认的序列可追溯，作为合规记录与运行记录同寿命；
    - **理由正文只落本表**：不进审计明细（审计侧只记 `reason_present`）。

跨租户拒写（既有手法）：PG 侧走**复合外键** `(tenant_id, run_id) → workbench_run_records`
（父表唯一约束由迁移 `027` 补齐）——租户不匹配时父行不存在 ⇒ 直接拒写，无需应用层判定。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

DECISION_CONFIRMED: Literal["confirmed"] = "confirmed"
DECISION_REJECTED: Literal["rejected"] = "rejected"
DECISIONS = (DECISION_CONFIRMED, DECISION_REJECTED)

MAX_REASON_LENGTH = 500
MAX_IDEMPOTENCY_KEY_LENGTH = 200


class AcceptanceDecisionError(ValueError):
    """入参不合法（服务端 fail-closed：宁可不记录，也不写半条 / 写错语义）。"""


@dataclass(frozen=True)
class AcceptanceDecision:
    """一行验收决议（**只读投影**；`tenant_id` / `idempotency_key` 不得外泄给客户端）。"""

    tenant_id: str
    run_id: str
    decision_id: str
    decision: str
    reason: str
    idempotency_key: str
    decided_by: str
    decided_by_role: str
    structural_verdict: str
    created_at: datetime

    def to_view(self) -> dict[str, object]:
        """对外视图：**不含** `tenant_id` 与 `idempotency_key`。"""
        return {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "decided_at": self.created_at,
            "structural_verdict": self.structural_verdict,
        }


def _now() -> datetime:
    return datetime.now(UTC)


def validate_decision(
    *,
    decision: str,
    reason: str | None,
    idempotency_key: str,
    structural_verdict: str,
) -> tuple[str, str]:
    """校验并归一入参（返回 `(decision, reason)`）：不合法即抛错，不猜测、不补默认语义。"""
    if decision not in DECISIONS:
        raise AcceptanceDecisionError("验收结论只能是 confirmed 或 rejected")
    text = (reason or "").strip()
    if decision == DECISION_REJECTED and not text:
        raise AcceptanceDecisionError("打回重做必须写明原因")
    if len(text) > MAX_REASON_LENGTH:
        raise AcceptanceDecisionError(f"原因不超过 {MAX_REASON_LENGTH} 字")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise AcceptanceDecisionError("缺少幂等键")
    if len(idempotency_key.strip()) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise AcceptanceDecisionError("幂等键过长")
    if structural_verdict not in {"met", "unmet"}:
        raise AcceptanceDecisionError("结构判定取值非法")
    return decision, text


class AcceptanceDecisionStore(Protocol):
    """写读两端的最小接口（内存实现与 PG 实现口径一致）。"""

    def record(self, decision: AcceptanceDecision) -> tuple[AcceptanceDecision, bool]: ...

    def list_for_run(self, tenant_id: str, run_id: str) -> list[AcceptanceDecision]: ...


class InMemoryAcceptanceDecisionStore:
    """内存实现（仅 development；口径与 PG 实现一致，含幂等与校验）。"""

    def __init__(self, *, id_factory=None) -> None:
        self._new_id = id_factory or (lambda: uuid4().hex)
        self._rows: list[AcceptanceDecision] = []

    def record(self, decision: AcceptanceDecision) -> tuple[AcceptanceDecision, bool]:
        for row in self._rows:
            if row.tenant_id == decision.tenant_id and row.idempotency_key == decision.idempotency_key:
                return row, False
        stored = AcceptanceDecision(
            tenant_id=decision.tenant_id,
            run_id=decision.run_id,
            decision_id=self._new_id(),
            decision=decision.decision,
            reason=decision.reason,
            idempotency_key=decision.idempotency_key,
            decided_by=decision.decided_by,
            decided_by_role=decision.decided_by_role,
            structural_verdict=decision.structural_verdict,
            created_at=decision.created_at,
        )
        self._rows.append(stored)
        return stored, True

    def list_for_run(self, tenant_id: str, run_id: str) -> list[AcceptanceDecision]:
        rows = [row for row in self._rows if row.tenant_id == tenant_id and row.run_id == run_id]
        return sorted(rows, key=lambda row: (row.created_at, row.decision_id), reverse=True)


class PostgresAcceptanceDecisionStore:
    """PG 实现（迁移 040）；跨租户写由**复合外键**拒绝（`(tenant_id, run_id)` 父行必须存在）。"""

    def __init__(self, connection_or_pool: Any) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    def record(self, decision: AcceptanceDecision) -> tuple[AcceptanceDecision, bool]:
        row = (
            decision.tenant_id,
            decision.run_id,
            uuid4().hex,
            decision.decision,
            decision.reason,
            decision.idempotency_key,
            decision.decided_by,
            decision.decided_by_role,
            decision.structural_verdict,
            decision.created_at,
        )
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # 幂等：同键冲突时**不写**，随后按幂等键读回既有行（与内存实现同语义）。
                    cursor.execute(
                        """
                        INSERT INTO workbench_run_acceptance_decisions
                            (tenant_id, run_id, decision_id, decision, reason, idempotency_key,
                             decided_by, decided_by_role, structural_verdict, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                        RETURNING decision_id
                        """,
                        row,
                    )
                    inserted = cursor.fetchone() is not None
                    if inserted:
                        return (
                            AcceptanceDecision(
                                tenant_id=decision.tenant_id,
                                run_id=decision.run_id,
                                decision_id=row[2],
                                decision=decision.decision,
                                reason=decision.reason,
                                idempotency_key=decision.idempotency_key,
                                decided_by=decision.decided_by,
                                decided_by_role=decision.decided_by_role,
                                structural_verdict=decision.structural_verdict,
                                created_at=decision.created_at,
                            ),
                            True,
                        )
                    cursor.execute(
                        """
                        SELECT tenant_id, run_id, decision_id, decision, reason, idempotency_key,
                               decided_by, decided_by_role, structural_verdict, created_at
                        FROM workbench_run_acceptance_decisions
                        WHERE tenant_id = %s AND idempotency_key = %s
                        """,
                        (decision.tenant_id, decision.idempotency_key),
                    )
                    existing = cursor.fetchone()
        if existing is None:  # pragma: no cover - 冲突但读不回：状态不一致时如实报错，不伪造
            raise AcceptanceDecisionError("幂等键冲突但读回失败")
        return (
            AcceptanceDecision(
                tenant_id=str(existing[0]),
                run_id=str(existing[1]),
                decision_id=str(existing[2]),
                decision=str(existing[3]),
                reason=str(existing[4]),
                idempotency_key=str(existing[5]),
                decided_by=str(existing[6]),
                decided_by_role=str(existing[7]),
                structural_verdict=str(existing[8]),
                created_at=existing[9],
            ),
            False,
        )

    def list_for_run(self, tenant_id: str, run_id: str) -> list[AcceptanceDecision]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tenant_id, run_id, decision_id, decision, reason, idempotency_key,
                           decided_by, decided_by_role, structural_verdict, created_at
                    FROM workbench_run_acceptance_decisions
                    WHERE tenant_id = %s AND run_id = %s
                    ORDER BY created_at DESC, decision_id DESC
                    """,
                    (tenant_id, run_id),
                )
                rows = cursor.fetchall()
        return [
            AcceptanceDecision(
                tenant_id=str(row[0]),
                run_id=str(row[1]),
                decision_id=str(row[2]),
                decision=str(row[3]),
                reason=str(row[4]),
                idempotency_key=str(row[5]),
                decided_by=str(row[6]),
                decided_by_role=str(row[7]),
                structural_verdict=str(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]