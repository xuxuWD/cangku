from pathlib import Path

from app.orchestration.models import (
    OrchestrationProposal,
    OrchestrationProposalKind,
    OrchestrationProposalStatus,
)


def test_migration_014_defines_table_and_indexes() -> None:
    migration = Path("migrations/014_orchestration_proposals.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_orchestration_proposals" in migration
    assert "proposal_id TEXT PRIMARY KEY" in migration
    assert "tenant_id TEXT NOT NULL" in migration
    assert "kind TEXT NOT NULL" in migration
    assert "current_value TEXT NOT NULL" in migration
    assert "proposed_value TEXT NOT NULL" in migration
    assert "rationale TEXT NOT NULL" in migration
    assert "metrics_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb" in migration
    assert "CHECK (status IN ('pending_review', 'approved', 'rejected'))" in migration
    assert "created_by TEXT NOT NULL" in migration
    assert "created_at TIMESTAMPTZ NOT NULL DEFAULT now()" in migration
    assert "reviewed_by TEXT" in migration
    assert "reviewed_at TIMESTAMPTZ" in migration
    assert "rejection_reason TEXT" in migration

    assert migration.count("CREATE INDEX IF NOT EXISTS") == 2
    assert "(tenant_id, status)" in migration
    assert "(tenant_id, created_at DESC)" in migration

    # 被驳回后允许重新生成，因此不加唯一约束（幂等由服务层实现）。
    assert "UNIQUE" not in migration
    assert "ON CONFLICT" not in migration


def test_kind_and_status_values() -> None:
    assert OrchestrationProposalKind.RUNTIME_DEFAULT.value == "runtime_default"
    assert [status.value for status in OrchestrationProposalStatus] == [
        "pending_review",
        "approved",
        "rejected",
    ]


def test_proposal_defaults_and_identifier_prefix() -> None:
    proposal = OrchestrationProposal(
        tenant_id="t-1",
        kind=OrchestrationProposalKind.RUNTIME_DEFAULT,
        current_value="mock",
        proposed_value="agentscope",
        rationale="理由",
        metrics_snapshot={},
        created_by="ceo-1",
    )

    assert proposal.proposal_id.startswith("orch-")
    assert proposal.status is OrchestrationProposalStatus.PENDING_REVIEW
    assert proposal.created_at.tzinfo is not None
    assert proposal.reviewed_by is None
    assert proposal.reviewed_at is None
    assert proposal.rejection_reason is None
