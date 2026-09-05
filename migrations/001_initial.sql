CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS workbench_tasks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT,
    created_by TEXT NOT NULL,
    employee_key TEXT NOT NULL,
    title TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    budget NUMERIC(18, 6) NOT NULL CHECK (budget >= 0),
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'pending_approval', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, created_by, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_tasks_tenant_created
    ON workbench_tasks (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workbench_audit_events (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES workbench_tasks(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approval must be a single conditional update inside the caller's transaction.
-- The affected-row count is the source of truth for 200 vs 409.
-- UPDATE workbench_tasks
-- SET status = 'queued', updated_at = now()
-- WHERE id = $1 AND tenant_id = $2 AND status = 'pending_approval';
