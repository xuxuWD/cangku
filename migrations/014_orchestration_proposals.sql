CREATE TABLE IF NOT EXISTS workbench_orchestration_proposals (
    proposal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    current_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    rationale TEXT NOT NULL,
    metrics_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('pending_review', 'approved', 'rejected')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbench_orchestration_proposals_status
    ON workbench_orchestration_proposals (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_workbench_orchestration_proposals_created
    ON workbench_orchestration_proposals (tenant_id, created_at DESC);
