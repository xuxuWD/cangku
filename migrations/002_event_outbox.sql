CREATE TABLE IF NOT EXISTS workbench_event_outbox (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    sequence BIGINT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbench_event_outbox_pending
    ON workbench_event_outbox (published_at, occurred_at)
    WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS workbench_event_consumers (
    consumer_name TEXT PRIMARY KEY,
    last_sequence BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
