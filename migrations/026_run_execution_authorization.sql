-- 026：运行执行授权位（段一规格 §2.3）
--
-- 背景：审批通过之后、真正执行之前，计划若被改动，原审批就应当失效。
--   这里记下「谁在何时批准了哪个计划摘要」，执行前方可比对；不依赖任何人记得发撤销事件。
--
-- 三列刻意**可空且不带默认值**：「未授权」必须是显式的 NULL，不能用默认值伪装成已授权。
-- 并由 CHECK 强制**全有或全无**——只填一半的授权位是不可表示的非法状态。

ALTER TABLE workbench_run_records
    ADD COLUMN IF NOT EXISTS execution_authorized_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_authorized_by  TEXT,
    ADD COLUMN IF NOT EXISTS authorized_plan_digest   TEXT;

ALTER TABLE workbench_run_records
    DROP CONSTRAINT IF EXISTS workbench_run_records_execution_authorization_check;

ALTER TABLE workbench_run_records
    ADD CONSTRAINT workbench_run_records_execution_authorization_check
    CHECK (
        (execution_authorized_at IS NULL) = (execution_authorized_by IS NULL)
        AND (execution_authorized_at IS NULL) = (authorized_plan_digest IS NULL)
    );
