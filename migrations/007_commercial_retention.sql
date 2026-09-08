ALTER TABLE workbench_lifecycle_jobs ADD COLUMN IF NOT EXISTS final_exported BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS workbench_retention_policies (tenant_id TEXT PRIMARY KEY REFERENCES workbench_tenants(id), policy JSONB NOT NULL, updated_by TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
