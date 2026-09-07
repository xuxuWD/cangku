CREATE TABLE IF NOT EXISTS workbench_tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('trial', 'active', 'suspended', 'exporting', 'deleting', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workbench_workspaces (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS workbench_customer_admins (
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    user_id TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS workbench_plan_versions (
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    plan_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    limits JSONB NOT NULL,
    overage_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, plan_key, version)
);

CREATE TABLE IF NOT EXISTS workbench_usage_ledger (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    idempotency_key TEXT NOT NULL,
    units BIGINT NOT NULL,
    cost_cents BIGINT NOT NULL,
    reversal_of TEXT,
    reason TEXT,
    actor_id TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS workbench_lifecycle_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    kind TEXT NOT NULL CHECK (kind IN ('export', 'delete')),
    status TEXT NOT NULL,
    execute_after TIMESTAMPTZ,
    requested_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workbench_tenants_status ON workbench_tenants (status);
CREATE INDEX IF NOT EXISTS idx_workbench_usage_tenant_time ON workbench_usage_ledger (tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_workbench_lifecycle_tenant_status ON workbench_lifecycle_jobs (tenant_id, status);
