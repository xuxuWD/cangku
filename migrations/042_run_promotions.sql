-- 042_run_promotions.sql
-- S2 沉淀入口：`workbench_run_promotions` —— 「把这次运行存成一个可再跑的任务」的**沉淀链接**。
-- 依据：docs/api-contract.md「运行沉淀（S2 · 存成任务）」；
--       docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md §3 接缝 S2
--       （「确认后出现「存成任务 / 设为自动化」（B5 的轻量入口，完整画布见 C3）」）。
--
-- 约定：
--   * **沉淀是链接，任务是产物**：本表只记「哪个运行沉淀成了哪个任务」（+ 当时的标题快照），
--     任务本身落既有任务仓储；`ON DELETE CASCADE` ⇒ 运行记录被删只解除链接，不动任务。
--   * **一个运行只能沉淀一次**：主键 `(tenant_id, run_id)` —— 重复提交由服务端读回既有行返回，
--     并发提交由主键拒绝（不会出现同一运行指向两条任务）。
--   * 租户隔离写进约束（与 027 / 037 / 040 同一手法）：复合外键 `(tenant_id, run_id)` 引用运行记录表；
--     父表侧唯一约束 `workbench_run_records_run_tenant_unique` 由迁移 027 增补 ⇒ 跨租户写直接拒。
--   * **不设保留期**：与运行记录同寿命（运行记录被删即随链接一起清掉）。
--   * 标题只落本表快照：**不进审计明细**（审计只记 `task_id`），避免把用户文本复制进审计与日志。

CREATE TABLE IF NOT EXISTS workbench_run_promotions (
    tenant_id   TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    title       TEXT NOT NULL,          -- 沉淀时的任务标题快照（供追溯；任务本身以任务表为准）
    promoted_by TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id)
        ON DELETE CASCADE
);