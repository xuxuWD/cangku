CREATE TABLE IF NOT EXISTS workbench_knowledge_access_audits (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    binding_type TEXT NOT NULL CHECK (binding_type IN ('role', 'agent')),
    binding_key TEXT NOT NULL,
    old_knowledge_base_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    new_knowledge_base_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    actor_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_knowledge_access_audits_lookup
    ON workbench_knowledge_access_audits (tenant_id, occurred_at DESC);
