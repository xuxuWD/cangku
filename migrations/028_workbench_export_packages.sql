-- 028_workbench_export_packages.sql
-- 导出载荷落点：承载租户导出的脱敏载荷与过期时刻。
-- 依据：docs/superpowers/specs/2026-09-06-commercial-g0-design.md §6.1
--   （「导出任务异步执行，生成带过期时间的下载包」）与 docs/api-contract.md:144
--   （「导出内容经过脱敏，不包含密码、Cookie、验证码、令牌、原始 API 密钥或客户原文」）。
-- 口径：保留策略以 DB 表 workbench_retention_policies（服务侧）为准；
--   env WORKBENCH_RETENTION_POLICY 仅由 scripts/commercial_g0_preflight.py 的部署预检读取，
--   不被服务侧消费（两者之间无写入方，预检 pass ≠ 服务侧生效）。
CREATE TABLE IF NOT EXISTS workbench_export_packages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES workbench_tenants(id),
    job_id TEXT REFERENCES workbench_lifecycle_jobs(id),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workbench_export_packages_tenant ON workbench_export_packages (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workbench_export_packages_expires ON workbench_export_packages (expires_at);
