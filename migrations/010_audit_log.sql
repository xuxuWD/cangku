CREATE TABLE IF NOT EXISTS workbench_audit_log (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    actor_id TEXT,
    tenant_id TEXT,
    target_type TEXT,
    target_id TEXT,
    phone_masked TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_tenant_time
    ON workbench_audit_log (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_action_time
    ON workbench_audit_log (action, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_target
    ON workbench_audit_log (target_id);
