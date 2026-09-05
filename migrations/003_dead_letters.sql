CREATE TABLE IF NOT EXISTS workbench_dead_letters (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts > 0),
    last_error TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at TIMESTAMPTZ,
    replayed_by TEXT,
    UNIQUE (tenant_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_dead_letters_pending
    ON workbench_dead_letters (tenant_id, recorded_at)
    WHERE replayed_at IS NULL;
