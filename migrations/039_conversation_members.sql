-- 039_conversation_members.sql
-- P2c-6：会话协作（分享与多端协同）——成员表 + 消息 `sender_id` 列
-- 真源：docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md §2.16（已评审 2026-09-17）；
--       契约 docs/api-contract.md「会话协作：分享与多端协同（P2c-6 · 2026-09-17）」。
--
-- 约定：
--   * `permission` 受控两档 `read` / `write`，表级 CHECK 与实现层 `PERMISSION_READ/WRITE` 一字不差：
--     绕过接口的直接 SQL 写入同样被拒（「一切输入默认不可信」）。
--   * 主键 `(tenant_id, conversation_id, member_id)`：同一成员在同一会话只有一行；重复添加走
--     `ON CONFLICT DO UPDATE` 覆盖权限档（权限变更由服务层写审计）。
--   * 复合外键引用 `workbench_conversations (tenant_id, conversation_id)`：悬空 / 跨租户引用都被库拒绝；
--     `ON DELETE CASCADE`：会话行**真删**时成员行随之清理（清场 / 运维删行都不被分享名单挡路；
--     生产路径的「物理删除」只软删会话行，不触发本级联）。
--   * **不做实时在线态**：成员表**不**建活动时间列，「最近活动时间」取会话 `updated_at`（裁定 ③）。
--   * 成员必须同租户 / 已审批 / 非 `customer_admin`——该判定在服务层（需读账号仓储），不在库层。
--   * 消息 `sender_id` 可空（**只增**）：发言账号 id；助手 / 工具 / 系统消息恒 `NULL`，
--     存量行 `NULL` ⇒ 展示回退为「发起人」（零破坏，不回填）。

CREATE TABLE IF NOT EXISTS workbench_conversation_members (
    tenant_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('read', 'write')),
    added_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id, member_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
        ON DELETE CASCADE
);

-- 反向查询：按「我参与过哪些会话」过滤列表（`member_id` + 租户即可命中）。
CREATE INDEX IF NOT EXISTS idx_workbench_conversation_members_member
    ON workbench_conversation_members (tenant_id, member_id);

ALTER TABLE workbench_conversation_messages
    ADD COLUMN IF NOT EXISTS sender_id TEXT;