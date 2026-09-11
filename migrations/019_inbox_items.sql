-- 站内通知（收件箱）：把「等待结果的人」需要知道的结果落到可查询的列表。
-- 只承载「发生了什么 + 去哪看」：不存事件正文、detail、手机号等敏感内容，
-- 文案由服务端按固定模板生成（见 app/inbox.py）。
CREATE TABLE IF NOT EXISTS workbench_inbox_items (
    inbox_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    target_type  TEXT,
    target_id    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at      TIMESTAMPTZ
);

-- 按接收人读取（列表默认排序：最新在前）。
CREATE INDEX IF NOT EXISTS idx_workbench_inbox_items_recipient
    ON workbench_inbox_items (tenant_id, recipient_id, created_at DESC);

-- 未读过滤与「全部标记已读」。
CREATE INDEX IF NOT EXISTS idx_workbench_inbox_items_unread
    ON workbench_inbox_items (tenant_id, recipient_id, read_at);

-- 惰性清理使用（按过期时间删除）。
CREATE INDEX IF NOT EXISTS idx_workbench_inbox_items_created_at
    ON workbench_inbox_items (created_at);
