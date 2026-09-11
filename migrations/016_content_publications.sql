CREATE TABLE IF NOT EXISTS workbench_content_publications (
    publication_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    target TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'manual_takeover', 'pending')),
    receipt_id TEXT,
    error TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ,
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_content_publications_task
    ON workbench_content_publications (tenant_id, task_id, created_at DESC);
