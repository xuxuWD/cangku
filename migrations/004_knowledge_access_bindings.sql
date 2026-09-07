CREATE TABLE IF NOT EXISTS workbench_knowledge_access_bindings (
    tenant_id TEXT NOT NULL,
    binding_type TEXT NOT NULL CHECK (binding_type IN ('role', 'agent')),
    binding_key TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, binding_type, binding_key, knowledge_base_id),
    UNIQUE (tenant_id, binding_type, binding_key, knowledge_base_id)
);

CREATE INDEX IF NOT EXISTS idx_workbench_knowledge_access_lookup
    ON workbench_knowledge_access_bindings (tenant_id, binding_type, binding_key);
