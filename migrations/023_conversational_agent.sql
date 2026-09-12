-- 对话式 AI 员工平台（口径见 docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md §7）
--
-- 约定：
--   * 会话表是租户语义的唯一落点（D6）；dsh_session_id 只做映射，不承载任何租户语义。
--   * 租户隔离写进约束：复合外键 (tenant_id, conversation_id) 引用父表主键，而不是只靠 WHERE
--     （与 workbench_job_roles / workbench_tasks 同一手法）。
--   * 消息表 append-only：不建 updated_at、不提供 update 路径（与审计表同构）。
--   * agent_key 刻意不加外键：数字员工可停用（停用不删除），历史会话必须永远可解析。
--   * D12：本迁移**不建任何 vector 列，也不建占位列**。记忆（含向量）是 P3 才建的表，
--     届时 embedding 模型已定，可在记忆表上一次性建 vector 列与索引。
--     理由：向量列一旦写死维度，改维度就要重建索引；而 023 里没有任何表是记忆向量的落点，
--     在此预留占位列属于为假想需求设计。

CREATE TABLE IF NOT EXISTS workbench_conversations (
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    agent_key       TEXT,                 -- 路由到的数字员工（目录可停用，故不加外键）
    operator_id     TEXT NOT NULL,        -- 发起人（账号 id）
    title           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    dsh_session_id  TEXT,                 -- 外部 Harness 的会话 id（映射用，可为空）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_workbench_conversations_operator
    ON workbench_conversations (tenant_id, operator_id, status);

CREATE TABLE IF NOT EXISTS workbench_conversation_messages (
    tenant_id       TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content         TEXT NOT NULL,
    tool_name       TEXT,
    tool_call_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, message_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_workbench_conversation_messages_conversation
    ON workbench_conversation_messages (tenant_id, conversation_id, created_at);

-- 数字员工配置（§7.2）：存量行因全部带 DEFAULT，自动获得空配置
-- （= 用默认模型、无提示词、无工具），不回填、不改写。
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS system_prompt     TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model_key         TEXT NOT NULL DEFAULT '',
    -- temperature 的 CHECK 是必须的：NUMERIC(3,2) 只把范围限到 ±9.99，不拦 9.99 / -1.00。
    -- 应用层已校验 0.00–2.00，这里是第二道防线（防止绕过接口的直接 SQL 写入）。
    ADD COLUMN IF NOT EXISTS temperature       NUMERIC(3,2) NOT NULL DEFAULT 0.20
        CHECK (temperature >= 0.00 AND temperature <= 2.00),
    ADD COLUMN IF NOT EXISTS tool_allowlist    JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS memory_policy     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- 治理字段：参照 EvovexAI EvoFlow 的员工级治理设计（§2.4），金额按宪法用整数分
    ADD COLUMN IF NOT EXISTS autonomy_level    TEXT NOT NULL DEFAULT 'approval_for_risky'
        CHECK (autonomy_level IN ('approval_for_all', 'approval_for_risky', 'full_auto')),
    ADD COLUMN IF NOT EXISTS risk_threshold    TEXT NOT NULL DEFAULT 'high'
        CHECK (risk_threshold IN ('low', 'medium', 'high')),
    ADD COLUMN IF NOT EXISTS approval_timeout_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (approval_timeout_minutes BETWEEN 5 AND 10080),
    ADD COLUMN IF NOT EXISTS daily_budget_cents BIGINT NOT NULL DEFAULT 0
        CHECK (daily_budget_cents >= 0);
