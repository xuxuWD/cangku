-- 岗位与数字员工目录（口径见 docs/superpowers/specs/2026-09-12-agent-directory-design.md）
--
-- 约定：
--   * 标识创建后不可改（任务、知识绑定、运行记录都引用了它）；停用只改 status，不删除，
--     否则历史任务与知识绑定会解析不到标识。
--   * 租户隔离写进约束：复合外键 (tenant_id, role_key) 引用父表主键，而不是只靠 WHERE。
--   * 本迁移只新增表，不改动任何既有表结构，回滚 = 停止使用（无需删数据）。

CREATE TABLE IF NOT EXISTS workbench_job_roles (
    tenant_id TEXT NOT NULL,
    role_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_job_roles_status
    ON workbench_job_roles (tenant_id, status);

CREATE TABLE IF NOT EXISTS workbench_digital_employees (
    tenant_id TEXT NOT NULL,
    agent_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    role_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_key),
    FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles (tenant_id, role_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_digital_employees_role
    ON workbench_digital_employees (tenant_id, role_key);
