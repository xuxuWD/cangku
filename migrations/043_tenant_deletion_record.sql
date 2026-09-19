-- 043_tenant_deletion_record.sql
-- 租户删除的「记录确认人」落点（真源 commercial-g0-design.md:114）：
--   「租户删除采用两步流程……删除前必须生成最终导出包并记录确认人。」
-- 在既有生命周期作业表上**只增**两列（存量行两列均为 NULL，不影响既有流程）：
--   - `confirmed_by`：确认删除的管理员 user_id —— 由 `CommercialLifecycleService.confirm_deletion`
--     写入（admin-only，冷静期内、需已完成最终导出），是**独立于「申请」的显式确认动作**；
--   - `confirmed_at`：确认时刻（UTC）。
-- 确认动作与删除执行各自写审计：`commercial.deletion.confirmed` / `commercial.deletion.executed`
-- （明细只记受控值：`kind` / `status` / `confirmed_by` / `cleared_categories`，不含自由文本）。
ALTER TABLE workbench_lifecycle_jobs
    ADD COLUMN IF NOT EXISTS confirmed_by TEXT,
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;