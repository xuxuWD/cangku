-- 会话令牌的服务端撤销名单（登出立即生效）。
-- 只记录令牌标识与令牌自身的过期时间；判定按 expires_at > now() 过滤，
-- 因此条目无需额外清理任务即可自然失效（写入时顺带删除过期行）。
CREATE TABLE IF NOT EXISTS workbench_session_revocations (
    token_id TEXT PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_session_revocations_expires_at
    ON workbench_session_revocations (expires_at);
