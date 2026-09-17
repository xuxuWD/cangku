-- 036_conversation_stream.sql
-- P2b 实时流与过程事件（SSE + PG 流帧 + 过程事件）。
-- 依据：docs/superpowers/specs/2026-09-17-realtime-stream-p2b-design.md（已评审 2026-09-17）§2.1。
--
-- 约定：
--   * 两表拆分：**明细表只追加**（append-only 帧序列，不建 updated_at，与消息表 / 审计表同构）；
--     **状态表每 run 一行**（`last_seq` / 计数 / 终态 / 过期时刻 / 水位），避免对大表频繁 COUNT/SUM。
--   * 租户隔离写进约束：复合外键 (tenant_id, conversation_id) 引用会话表主键（与 023 同一手法）。
--   * 帧 `payload` 在**写入前**已过 `redact_payload`（默认只落摘要：工具结果不含 stdout 全文 / 文件正文 /
--     宿主真实路径 / 凭据；`message.*` 帧不落正文，只落 message_id）。
--   * 序号分配：状态行原子递增（`last_seq = last_seq + 1 ... RETURNING`），与写帧同事务 ⇒ 不重复不跳号。
--   * 保留期：终态时置 `expires_at = now() + WORKBENCH_STREAM_RETENTION_DAYS`（默认 7 天）；
--     未终态且超 `WORKBENCH_STREAM_STALLED_HOURS`（默认 6h）由清理任务兜底置 `unavailable('stalled')`。
--   * 清理只删本两表（**不动**消息表 / 审计 / 运行事件）。

-- 帧明细表（append-only；主键即回放路径）
CREATE TABLE IF NOT EXISTS workbench_conversation_stream_frames (
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    seq             INTEGER NOT NULL,            -- 从 1 开始，同一 (conversation, run) 内单调递增且唯一
    kind            TEXT NOT NULL,               -- §2.5 冻结取值域（message.* / RuntimeEventType 十种 / stream.unavailable）
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_terminal     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id, run_id, seq),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_stream_frames_replay
    ON workbench_conversation_stream_frames (tenant_id, conversation_id, run_id, seq);

CREATE INDEX IF NOT EXISTS idx_wb_stream_frames_created_at
    ON workbench_conversation_stream_frames (created_at);

-- 流状态表（每 (conversation, run) 一行）
CREATE TABLE IF NOT EXISTS workbench_conversation_stream_state (
    tenant_id               TEXT NOT NULL,
    conversation_id         TEXT NOT NULL,
    run_id                  TEXT NOT NULL,
    last_seq                INTEGER NOT NULL DEFAULT 0,
    frame_count             INTEGER NOT NULL DEFAULT 0,
    byte_count              BIGINT  NOT NULL DEFAULT 0,
    is_terminal             BOOLEAN NOT NULL DEFAULT false,
    status                  TEXT NOT NULL DEFAULT 'streaming'
        CHECK (status IN ('streaming', 'completed', 'failed', 'unavailable')),
    persisted_to_message_id TEXT,
    expires_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id, run_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_stream_state_expires
    ON workbench_conversation_stream_state (expires_at);

CREATE INDEX IF NOT EXISTS idx_wb_stream_state_stalled
    ON workbench_conversation_stream_state (status, updated_at);