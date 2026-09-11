CREATE TABLE IF NOT EXISTS workbench_run_records (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    proposal_id TEXT,
    runtime_key TEXT NOT NULL,
    status TEXT NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    completed_step_count INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    successful_tools INTEGER NOT NULL DEFAULT 0,
    knowledge_hits INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workbench_run_records_task
    ON workbench_run_records (tenant_id, task_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_run_records_runtime
    ON workbench_run_records (tenant_id, runtime_key);

ALTER TABLE workbench_plan_proposals ADD COLUMN IF NOT EXISTS run_id TEXT;
