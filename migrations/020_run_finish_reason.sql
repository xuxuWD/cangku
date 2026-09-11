-- 运行结束原因：只存受控枚举（run_completed / cancelled_by_user / step_failed），
-- 非终态为 NULL；失败与取消的细节仍由运行事件接口暴露，不落自由文本。
ALTER TABLE workbench_run_records ADD COLUMN IF NOT EXISTS finish_reason TEXT;
