-- 040_run_acceptance_decisions.sql
-- S2 运行验收决议（人工验收）：`workbench_run_acceptance_decisions` —— **append-only** 决议历史。
-- 依据：docs/api-contract.md「运行验收决议（S2 · 人工验收 · 2026-09-18）」；
--       docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md §3 接缝 S2（M3 范围）。
--
-- 约定：
--   * **人的结论与机器的结论分开存**：机器结论（结构判定）是**只读纯函数**，不落库；
--     本表只存「谁在什么时候判的」（`decision` / `reason` / `decided_by` / `structural_verdict` 供追溯）。
--   * **不改运行状态、不触发重跑、不发通知**：本表是记录，不是状态机。
--   * 租户隔离写进约束（与 027 / 037 同一手法）：复合外键 `(tenant_id, run_id)` 引用运行记录表；
--     父表侧唯一约束 `workbench_run_records_run_tenant_unique` 由迁移 027 增补 ⇒ 跨租户写直接拒。
--   * **幂等**：唯一约束 `(tenant_id, idempotency_key)` —— 同键重放由服务端返回既有行，不重复写审计。
--   * **不设保留期**：验收决议是合规记录，与运行记录同寿命（不做保留期清理任务）。
--   * 理由正文只落本表：**不进审计明细**（审计只记 `reason_present`），避免把可能含敏感内容的长文本
--     复制到审计与日志里。

CREATE TABLE IF NOT EXISTS workbench_run_acceptance_decisions (
    tenant_id          TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    decision_id        TEXT NOT NULL,                    -- 服务端生成（客户端不可指定）
    decision           TEXT NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
    reason             TEXT NOT NULL DEFAULT '',
    idempotency_key    TEXT NOT NULL,
    decided_by         TEXT NOT NULL,
    decided_by_role    TEXT NOT NULL,
    structural_verdict TEXT NOT NULL CHECK (structural_verdict IN ('met', 'unmet')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, decision_id),
    CONSTRAINT workbench_run_acceptance_reason_required
        CHECK (decision <> 'rejected' OR length(reason) > 0),
    CONSTRAINT workbench_run_acceptance_idem_unique UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id)
);

-- 回放路径（(租户, 运行) 前缀 + 时间倒序：最新决议在前）
CREATE INDEX IF NOT EXISTS idx_wb_run_acceptance_run
    ON workbench_run_acceptance_decisions (tenant_id, run_id, created_at DESC, decision_id);