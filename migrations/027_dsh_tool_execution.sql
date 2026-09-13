-- 027_dsh_tool_execution.sql
-- 段二（dsh 接入段）工具执行的数据模型：待批动作/逐项授权（workbench_tool_actions）
-- 与执行幂等（workbench_execution_idempotency）。
--
-- 设计文件：docs/superpowers/specs/2026-09-12-dsh-integration-design.md §4.1（2026-09-13 已评审通过）。
-- 本文件为落地实现，与 §4.1 互为对照；若两者不一致，以本节为准并回改设计文件。
-- 执行器：app/migrations.py —— 按 sorted(glob) 顺序执行，记账于 workbench_schema_migrations，
--        已记账的跳过，**无自动回滚**。
-- 可重复执行：全部 DDL 使用 IF NOT EXISTS / DROP ... IF EXISTS + ADD（与 024/025/026 同写法），
--            故失败重试或手工重跑安全。
--
-- 🔴 语句顺序（§4.1 第四轮修订 R4-1，必须遵守）：
--    必须先补父表唯一约束（第 1 段），再建两张新表（第 2、3 段）。
--    否则复合外键 (tenant_id, run_id) 引用不到父表唯一约束，PostgreSQL 直接报
--    "there is no unique constraint matching given keys for referenced table"
--    ——因为 migrations/013 只建了 PRIMARY KEY (run_id)。

-- ============================================================================
-- 1) 对既有表 workbench_run_records 的约束增补（§4.1.2）
-- ============================================================================
-- 复合外键需要父表侧唯一约束。013 只建了 PRIMARY KEY (run_id)，
-- 故补 UNIQUE (run_id, tenant_id)：否则只能用单列外键，丢租户维度（跨租户可达）。
--
-- 🔴 此处**刻意不用** 024/025/026 的「DROP IF EXISTS + ADD」写法（2026-09-13 真库演练发现）：
--    027 的两张新表持有指向该唯一约束的复合外键（…_tenant_id_run_id_fkey），
--    重跑时 DROP CONSTRAINT 会因依赖对象存在而失败：
--      ERROR: cannot drop constraint workbench_run_records_run_tenant_unique
--             because other objects depend on it
--    PostgreSQL 无 ADD CONSTRAINT IF NOT EXISTS，故改用 DO 块按目录判定后增补：
--    存在即跳过、缺失才 ADD —— 既幂等，又不会误删依赖该约束的外键（不用 CASCADE）。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workbench_run_records_run_tenant_unique'
          AND conrelid = 'workbench_run_records'::regclass
    ) THEN
        ALTER TABLE workbench_run_records
            ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id);
    END IF;
END
$$;

-- ============================================================================
-- 2) 表 workbench_tool_actions —— 待批动作 = 授权项（同行同表；§4.1.1）
-- ============================================================================
-- 设计取舍：一个工具动作的生命周期是 pending → approved / rejected / expired，
-- 待批动作与授权项是**同一行的两个状态**。合成一行后不存在"另一行可比对"，
-- 从结构上消除「批准 A、执行 B」。
CREATE TABLE IF NOT EXISTS workbench_tool_actions (
    tenant_id         TEXT NOT NULL,
    action_id         TEXT NOT NULL,      -- 服务端生成（唯一标识不由客户端决定）
    approval_id       TEXT,               -- 决议入口键（R4-6）：决议端点按 (tenant_id, run_id, approval_id) 定位该行
    run_id            TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    step_id           TEXT NOT NULL,
    tool_key          TEXT NOT NULL,      -- 必须仍在工具组装面内，执行前复查
    args_digest       TEXT NOT NULL,      -- 规范化参数摘要（§4.1.4）；**覆盖完整参数**（含正文类参数）
    args_json         JSONB NOT NULL,     -- 规范化参数的受控落库副本（R5-1）：**仅**承载控制参数；
                                         -- 正文类参数一律以占位常量 "«body»" 替代 → 正文不落本表
    body_ciphertext   BYTEA,              -- 受控正文密文列（J7 = 丙案）：仅「需审批且含 body 类参数」时非空；
                                         -- AEAD 密文、密钥不落库（§3.4 唯一受控例外五条约束）
    body_expires_at   TIMESTAMPTZ,        -- 正文密文到期时刻 = 该动作的审批超时时刻；与 body_ciphertext 同有同无
    plan_digest       TEXT NOT NULL,
    risk_level        TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
    requires_approval BOOLEAN NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired')),
    requested_by      TEXT NOT NULL,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by        TEXT,
    decided_at        TIMESTAMPTZ,
    decision_source   TEXT,               -- 决议来源：服务端判定并在白名单内校验，不来自请求体
    reason_code       TEXT,               -- 受控枚举码（9 值，与 §3.4 的 reason 同一集合）；自由文本一律不落
    PRIMARY KEY (tenant_id, action_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id),
    -- 决议字段全有或全无（与 026 的 CHECK 同一思路）
    CONSTRAINT workbench_tool_actions_decision_check CHECK (
        (status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    ),
    -- 正文密文与到期时刻「同有同无」：防「有密文无 TTL」（永不过期）与「有 TTL 无密文」（空清理）
    CONSTRAINT workbench_tool_actions_body_check CHECK (
        (body_ciphertext IS NULL AND body_expires_at IS NULL)
        OR (body_ciphertext IS NOT NULL AND body_expires_at IS NOT NULL)
    )
);

-- 同一运行同一计划步只允许一个待批动作（防重复落库；已决议的历史行不受限）
CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_pending_unique
    ON workbench_tool_actions (tenant_id, run_id, step_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_workbench_tool_actions_run
    ON workbench_tool_actions (tenant_id, run_id, requested_at DESC);

-- 决议入口键的唯一映射（R4-6）：同一运行内 approval_id 不得指向两行
CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_approval
    ON workbench_tool_actions (tenant_id, run_id, approval_id)
    WHERE approval_id IS NOT NULL;

-- ============================================================================
-- 3) 表 workbench_execution_idempotency —— 执行幂等（§4.1.3）
-- ============================================================================
-- 幂等键改为客户端可重放的请求头 Idempotency-Key 后，必须有一处记录
-- 「该键对应哪一次执行的哪个结果」，否则「重放返回既有结果」无法兑现。
-- 只存指针、不存正文：首次响应由 message_id 反查 append-only 消息表重建。
CREATE TABLE IF NOT EXISTS workbench_execution_idempotency (
    tenant_id       TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    message_id      TEXT,            -- 首次生成的助手消息（响应由此重建）；可空（R4-5）
    run_id          TEXT,            -- 首次派生的运行；未派生（如被拒）时为空
    approval_id     TEXT,            -- J-4 新增：首次返回 202 时的决议入口键（重放须原样重建 202 响应体）
    outcome         TEXT NOT NULL CHECK (outcome IN ('executed','pending_approval','rejected','failed')),
    http_status     INTEGER NOT NULL,  -- R5-2 新增：首次响应的 HTTP 状态码（唯一结果码来源）；重放原样复用
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 复合主键即去重机制：并发重放由 INSERT ... ON CONFLICT DO NOTHING 收敛为一行
    PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, message_id)
        REFERENCES workbench_conversation_messages (tenant_id, message_id),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES workbench_run_records (tenant_id, run_id),
    -- 结果码与 outcome 的合法组合（J-5 新增）：防「executed + 409」这类无法重建的非法组合入库
    CONSTRAINT workbench_execution_idempotency_result_check CHECK (
        (outcome = 'executed'            AND http_status = 201)
        OR (outcome = 'pending_approval' AND http_status = 202)
        OR (outcome = 'rejected'         AND http_status IN (403, 404, 409, 422))
        OR (outcome = 'failed'           AND http_status IN (502, 504))
    )
);

CREATE INDEX IF NOT EXISTS idx_workbench_execution_idempotency_run
    ON workbench_execution_idempotency (tenant_id, run_id)
    WHERE run_id IS NOT NULL;
