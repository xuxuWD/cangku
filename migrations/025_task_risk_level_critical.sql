-- 025：任务风险刻度扩为四档（D21）
--
-- 背景：段一规格 §2.1。`RiskLevel` 扩为 `low / medium / high / critical` 四档
--   （`app/domain.py`），任务表的原 `CHECK` 只允许三档，会把 `critical` 任务挡在库外。
--
-- 说明：001 里该列是列级 `CHECK`，PG 自动命名为 <表名>_<列名>_check。
--   与 024 同写法：先 `DROP ... IF EXISTS` 再 `ADD`，可重复执行。

ALTER TABLE workbench_tasks
    DROP CONSTRAINT IF EXISTS workbench_tasks_risk_level_check;

ALTER TABLE workbench_tasks
    ADD CONSTRAINT workbench_tasks_risk_level_check
    CHECK (risk_level IN ('low', 'medium', 'high', 'critical'));
