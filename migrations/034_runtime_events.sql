-- 034_runtime_events.sql
-- 「运行事件有界」结构性改造：把事件从状态行的行内 JSONB（`workbench_runtime_states.events`）
-- 迁到独立 append-only 表 `workbench_runtime_events`，并配合保留期清理限制总量。
--
-- 依据与取舍：
--   * 改造前：事件挂在状态行里且无界；写入是「整行 upsert」⇒ 每追加 1 条事件都要重写全部历史
--     事件（写放大 O(n²)），事件多则行大、行大则写更慢。
--   * 改造后：事件单行追加（主键 (run_id, sequence) 保证同 run 内序号唯一），
--     状态行只保留有界字段 + 事件计数 `event_count`（供生成下一条序号、且清理旧事件后不回退）。
--   * 保留期：由 worker 周期任务按 `occurred_at` 清理超期事件
--     （`WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`，默认 30 天）。
--   * **只清理运行事件**：审计表（`workbench_audit_log` / `workbench_audit_events`）不可删除。
--
-- 可重复执行：DDL 一律 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS；回填与删列包在 DO 块内按列存在性判定
--             （与 migrations/027 的 DO 块同手法），故失败重试或手工重跑安全。

CREATE TABLE IF NOT EXISTS workbench_runtime_events (
    run_id      TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    sequence    INTEGER NOT NULL,                       -- 从 1 开始，同一 run 内单调递增且唯一
    event_type  TEXT NOT NULL,                          -- RuntimeEventType 的取值
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,     -- 写入前已按同一套敏感键规则脱敏
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),     -- 写入时刻（保留期清理的判定列）
    PRIMARY KEY (run_id, sequence)
);

-- 读取路径：按 (run_id, sequence) 升序 / 断点读取；租户列随行落库以便运维按租户排查。
CREATE INDEX IF NOT EXISTS idx_workbench_runtime_events_tenant_run
    ON workbench_runtime_events (tenant_id, run_id, sequence);

-- 保留期清理路径：按发生时间扫描超期行。
CREATE INDEX IF NOT EXISTS idx_workbench_runtime_events_occurred_at
    ON workbench_runtime_events (occurred_at);

-- 状态行补事件计数列（新增列，默认 0；存量行在下面按事件数组长度回填）。
ALTER TABLE workbench_runtime_states
    ADD COLUMN IF NOT EXISTS event_count INTEGER NOT NULL DEFAULT 0;

-- 存量回填（幂等：只在状态行仍有 `events` 列时执行）：
--   1) `event_count` 取原数组长度；
--   2) 事件逐条展开进新表（`ON CONFLICT DO NOTHING` ⇒ 重跑不重复写）；
--   3) 回填完成后删掉行内 `events` 列（此后事件只有一个真源）。
--
-- ⚠️ **原始事件没有时间戳**：`occurred_at` 只能用状态行的 `created_at` **近似**填充
--    （既非事件真实发生时刻，也不是写入时刻）。影响面：仅「保留期清理的判定基准」——
--    存量运行的事件会整体按「状态行创建时间」计龄，可能被提前或延后清理；
--    改造后新增的事件一律用表默认值 `now()`，为精确值。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'workbench_runtime_states'
          AND column_name = 'events'
    ) THEN
        UPDATE workbench_runtime_states
        SET event_count = jsonb_array_length(events)
        WHERE jsonb_typeof(events) = 'array';

        INSERT INTO workbench_runtime_events (run_id, tenant_id, sequence, event_type, payload, occurred_at)
        SELECT
            s.run_id,
            s.tenant_id,
            (item ->> 'sequence')::integer,
            item ->> 'event_type',
            COALESCE(item -> 'payload', '{}'::jsonb),
            s.created_at
        -- 「是数组」的判定放在子查询里：`jsonb_array_elements` 遇到非数组会直接报错，
        -- 不能指望同级 WHERE 先把它过滤掉（执行顺序不保证）。
        FROM (
            SELECT run_id, tenant_id, created_at, events
            FROM workbench_runtime_states
            WHERE jsonb_typeof(events) = 'array'
        ) AS s
        CROSS JOIN LATERAL jsonb_array_elements(s.events) AS item
        WHERE jsonb_exists(item, 'sequence')
          AND jsonb_exists(item, 'event_type')
        ON CONFLICT (run_id, sequence) DO NOTHING;

        ALTER TABLE workbench_runtime_states DROP COLUMN events;
    END IF;
END
$$;
