CREATE TABLE IF NOT EXISTS workbench_plan_proposals (
    proposal_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    generator_key TEXT NOT NULL,
    generator_model TEXT,
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_review', 'approved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    UNIQUE (tenant_id, task_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_plan_proposals_task
    ON workbench_plan_proposals (tenant_id, task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_plan_proposals_status
    ON workbench_plan_proposals (tenant_id, status);
