-- 037_run_artifacts.sql
-- P2c-3 产物登记（事项 K）：`workbench_run_artifacts` —— **运行级元数据**（虚拟路径 / 变更类型 / 字节 / sha256 / 时间）。
-- 依据：docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md §2.7 及「实现期裁定 3–4」；
--       契约 docs/api-contract.md「产物登记与只读端点」。
--
-- 约定：
--   * **只登记元数据**：不含文件内容、不含宿主真实路径（只用虚拟路径）、不含凭据；
--     **不进审计、不进消息表**（与帧回传同为「视图」通道）。
--   * 租户隔离写进约束（与 027 同一手法）：复合外键 (tenant_id, run_id) 引用运行记录表；
--     父表侧唯一约束 `workbench_run_records_run_tenant_unique` 由迁移 027 增补 ⇒ 跨租户写直接拒。
--   * 保留期：登记时置 `expires_at = created_at + WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS`（默认 30 天）；
--     到期行由 worker 周期任务 `run-artifacts-purge` **逐租户**清理（只清本表，不写审计）。
--   * 只读端点 `GET /api/v1/runs/{run_id}/artifacts` 不返回已过期行（保留期外如实降级）。

CREATE TABLE IF NOT EXISTS workbench_run_artifacts (
    tenant_id    TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    artifact_id  TEXT NOT NULL,                  -- 服务端生成（客户端不可指定）
    virtual_path TEXT NOT NULL,                  -- **虚拟路径**（宿主真实路径不得入库 / 不得外泄）
    change_kind  TEXT NOT NULL CHECK (change_kind IN ('created', 'overwritten', 'deleted')),
    bytes        BIGINT NOT NULL DEFAULT 0 CHECK (bytes >= 0),
    sha256       TEXT NOT NULL,                  -- "sha256:<hex>"（**只存摘要**，不存内容）
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ,                    -- 保留期到期时刻（NULL = 不清理，仅历史兼容；新行恒非空）
    PRIMARY KEY (tenant_id, run_id, artifact_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id)
);

-- 只读端点的回放路径（(租户, 运行) 前缀 + 时间序）
CREATE INDEX IF NOT EXISTS idx_wb_run_artifacts_run
    ON workbench_run_artifacts (tenant_id, run_id, created_at, artifact_id);

-- 清理任务扫描路径
CREATE INDEX IF NOT EXISTS idx_wb_run_artifacts_expires
    ON workbench_run_artifacts (expires_at);