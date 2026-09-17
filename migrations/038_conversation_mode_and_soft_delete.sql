-- 038_conversation_mode_and_soft_delete.sql
-- P2c-4：每会话模式 + 会话软删列（真源 docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md
-- §2.9 / §2.11，已评审 2026-09-17；契约 docs/api-contract.md「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」）。
--
-- 约定：
--   * `mode` 带 DEFAULT 'craft' ⇒ **存量会话零行为变化**（＝现状），不回填其它值。
--   * 受控取值 check 与实现层 `ConversationMode` 一字不差；绕过接口的直接 SQL 写入同样被拒。
--   * `deleted_at` 是**软删标记**（本人物理删除内容行后置位）：置位后会话在全部读写路径按
--     「不存在」处理（404），行本身保留以维持运行 / 审计引用链与软删语义；
--     消息行 / 帧行 / 流状态行 / 该会话幂等行由应用层真删（无墓碑列、无墓碑表）。
--   * 不建部分索引：现有 `idx_workbench_conversations_operator (tenant_id, operator_id, status)`
--     仍被列表 / 导出查询使用，`deleted_at IS NULL` 为附加过滤，本表量级与查询形态不需要新索引。

ALTER TABLE workbench_conversations
    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'craft'
        CHECK (mode IN ('ask', 'plan', 'goal', 'craft')),
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;