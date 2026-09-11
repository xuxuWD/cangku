-- 运行时状态持久化：让运行审批待办、暂停/恢复/取消与事件查询跨重启与多进程可用。
-- 事件与状态同存一行（当前事件量受计划步数约束）；事件 payload 在写入前已按同一套敏感键规则脱敏。
CREATE TABLE IF NOT EXISTS workbench_runtime_states (
    run_id          TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    status          TEXT NOT NULL,
    context         JSONB NOT NULL,
    plan            JSONB NOT NULL,
    events          JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    approvals       JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage           JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_runtime_states_tenant
    ON workbench_runtime_states (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_runtime_states_task
    ON workbench_runtime_states (tenant_id, task_id);
