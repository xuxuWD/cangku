-- 044_task_budget_cents.sql
-- 组 10.5（任务预算改整数分）——**加法式**：新增权威列 `budget_cents`，旧列 `budget` 保留（弃用），
-- 两列**恰好一个有值**（互斥），新写入一律只写 `budget_cents`。用户裁决 2026-09-19 选项 A。
--
-- 依据：宪法 §3 数据红线「金额不用浮点（整数分或 Decimal）」；`app/runtime/contracts.py:70` 的
-- `budget_cents: int` 早已是整数分（运行层先用整数分的既有先例），本迁移把**任务层**对齐到同一口径。
--
-- 兼容与回退（务必按序执行）：
--   前滚：本文件（含回填与不变量）。
--   回退（按 change-record 口径，**不用 CASCADE**）：
--     ALTER TABLE workbench_tasks DROP CONSTRAINT IF EXISTS workbench_tasks_budget_at_least_one;
--     ALTER TABLE workbench_tasks DROP CONSTRAINT IF EXISTS workbench_tasks_budget_cents_non_negative;
--     UPDATE workbench_tasks SET budget = ROUND(budget_cents / 100.0, 6) WHERE budget IS NULL AND budget_cents IS NOT NULL;
--     ALTER TABLE workbench_tasks ALTER COLUMN budget SET NOT NULL;
--     ALTER TABLE workbench_tasks DROP COLUMN IF EXISTS budget_cents;
--     DELETE FROM workbench_schema_migrations WHERE version = '044_task_budget_cents';
--   本迁移的**前滚 / 回退 / 再前滚**演练脚本：`tmp/drill-044-rollback.py`（一次性容器，2026-09-19）。
--
-- ⚠️ 不变量为什么是「**至少一列有值**」而不是「恰好一列」（2026-09-19 演练发现）：
--   若要求「恰好一列」，则**回退会把两列都填上值**（回退第 3 步给新行补 `budget`），而再前滚时
--   回填又会给这些行补 `budget_cents` ⇒ 撞 CHECK、迁移失败 —— 「部署 → 回退 → 再部署」是真实序列，
--   不能被自己的不变量挡住。取「至少一列」后：历史行两列都有（回退**无损**：其 `budget` 从未被改写），
--   新行只有 `budget_cents`；**读路径以 `budget_cents` 为权威**（`Task.budget_in_cents()`），
--   「两列同时给」的互斥在**接口层**强制（`POST /tasks` 两字段同传 ⇒ `422`）。

-- ① 新增权威列（可空：既有行先为空，随后由 ② 回填）。
ALTER TABLE workbench_tasks ADD COLUMN IF NOT EXISTS budget_cents BIGINT;

-- ② 回填：既有行按「元 → 分」四舍五入（ROUND 到整数分，避免浮点尾差落库）。
UPDATE workbench_tasks
SET budget_cents = ROUND(budget * 100)::BIGINT
WHERE budget_cents IS NULL AND budget IS NOT NULL;

-- ③ 旧列放开 NOT NULL（新行只写 `budget_cents` ⇒ `budget` 必须允许为空）。
ALTER TABLE workbench_tasks ALTER COLUMN budget DROP NOT NULL;

-- ④ 不变量：**至少一列有值**（口径与理由见文件头「不变量为什么是至少一列」段）。
ALTER TABLE workbench_tasks
    DROP CONSTRAINT IF EXISTS workbench_tasks_budget_exactly_one;
ALTER TABLE workbench_tasks
    DROP CONSTRAINT IF EXISTS workbench_tasks_budget_at_least_one;
ALTER TABLE workbench_tasks
    ADD CONSTRAINT workbench_tasks_budget_at_least_one
    CHECK (budget IS NOT NULL OR budget_cents IS NOT NULL);

ALTER TABLE workbench_tasks
    DROP CONSTRAINT IF EXISTS workbench_tasks_budget_cents_non_negative;
ALTER TABLE workbench_tasks
    ADD CONSTRAINT workbench_tasks_budget_cents_non_negative
    CHECK (budget_cents IS NULL OR budget_cents >= 0);

-- ⑤ 索引：保留策略（B-4 选项 C）与导出按租户读取都按 `(tenant_id, created_at)` 走既有索引
--    `idx_workbench_tasks_tenant_created`（001）⇒ 本迁移不新增索引。