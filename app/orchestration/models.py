from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class OrchestrationProposalKind(StrEnum):
    RUNTIME_DEFAULT = "runtime_default"


class OrchestrationProposalStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class OrchestrationProposalNotFound(LookupError):
    """优化提案不存在或不属于当前租户。"""


class OrchestrationProposalStateConflict(ValueError):
    """提案当前状态不允许该操作。"""


# 指标快照只允许暴露运行时的公开评估字段，避免把内部结构写进提案。
_SNAPSHOT_KEYS = frozenset(
    {
        "runtime_key",
        "run_count",
        "task_completion_rate",
        "tool_success_rate",
        "knowledge_hit_rate",
        "latency_p95_ms",
    }
)


def filter_snapshot(entry: dict[str, object]) -> dict[str, object]:
    """按白名单裁剪单条运行时指标，未知字段一律丢弃。"""
    return {key: entry[key] for key in sorted(_SNAPSHOT_KEYS) if key in entry}


@dataclass
class OrchestrationProposal:
    tenant_id: str
    kind: OrchestrationProposalKind
    current_value: str
    proposed_value: str
    rationale: str
    metrics_snapshot: dict[str, object]
    created_by: str
    proposal_id: str = field(default_factory=lambda: f"orch-{uuid4().hex[:12]}")
    status: OrchestrationProposalStatus = OrchestrationProposalStatus.PENDING_REVIEW
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        self.metrics_snapshot = {
            key: filter_snapshot(value) if isinstance(value, dict) else value
            for key, value in self.metrics_snapshot.items()
        }
