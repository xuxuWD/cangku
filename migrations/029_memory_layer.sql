-- 029_memory_layer.sql
-- P3 记忆层（记忆 / 画像）。依据：docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §2。
--
-- 约定：
--   * 前置：001 已 `CREATE EXTENSION vector`（0.8.6 在容器回归已验证），本迁移直接使用 vector 类型与 HNSW 索引。
--   * 三类记忆（身份 / 规则 / 事实）互不合并，各自独立表；公共档案表 `workbench_memory_profile_keys` 承载身份类 KV。
--   * 租户隔离写进约束：复合主键一律以 (tenant_id, ...) 打头（与 `workbench_conversations` 同一手法）。
--   * 作用域（scope）为域内枚举，**由服务端解析**，客户端不得直传（§2.3）；此处同样以 CHECK 枚举约束兜底。
--   * 软删口径：作废用 `status='superseded' + superseded_by`（宪法：重要数据软删除 `deleted_at`），
--     不物理删除；`deleted_at` 与 `superseded` 二选一，本规采用 supersede 链（§2.2）。
--   * 向量维度固定 1024（D12 一次性建列）：Qwen3-Embedding-0.6B 一锤定音；
--     换高维模型经 MRL 同维度截断，无重建之需（§1.2.1）。embedding 列允许 NULL（=无向量，HNSW 索引可含 NULL）。
--   * 重要数据不物理删除：仅 `list_all_for_tenant` / `delete_all_for_tenant` 属生命周期整体删除可用。

-- ---------------------------------------------------------------- 事实类记忆（可向量检索）
CREATE TABLE IF NOT EXISTS workbench_memory_facts (
    tenant_id        TEXT NOT NULL,
    memory_id        TEXT NOT NULL,
    owner_kind       TEXT NOT NULL CHECK (owner_kind IN ('user','agent')),  -- 归属方类别
    owner_id         TEXT NOT NULL,                 -- 归属方标识（账号 / 数字员工）
    scope            TEXT NOT NULL
        CHECK (scope IN ('user','role','project','organization')),  -- 域内枚举，服务端解析
    content          TEXT NOT NULL,
    embedding        VECTOR(1024),                  -- 维度固定 1024；NULL = 无向量（不参与语义检索）
    status           TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','superseded')),
    superseded_by    TEXT,                          -- supersede 链：指向作废后继条目 id
    idempotency_key  TEXT NOT NULL,                 -- 幂等键（同一 owner 下重复提交不重复落库）
    created_by       TEXT NOT NULL,                 -- 写入操作者
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, memory_id)
);

-- 向量（余弦近似最近邻）检索索引入口（§2.2）；NULL embedding 不参与检索，查询需 `WHERE embedding IS NOT NULL`。
CREATE INDEX IF NOT EXISTS idx_memory_facts_hnsw
    ON workbench_memory_facts USING hnsw (embedding vector_cosine_ops);

-- 租户 + 归属 + 作用域 + 状态的常规过滤索引（事实类列表 / 生命周期按租户导出的快速路径）。
CREATE INDEX IF NOT EXISTS idx_memory_facts_owner
    ON workbench_memory_facts (tenant_id, owner_kind, owner_id, scope, status);

-- ---------------------------------------------------------------- 规则类记忆（整段准则 + 版本快照）
CREATE TABLE IF NOT EXISTS workbench_memory_rules (
    tenant_id       TEXT NOT NULL,
    memory_id       TEXT NOT NULL,
    owner_kind      TEXT NOT NULL CHECK (owner_kind IN ('user','agent')),
    owner_id        TEXT NOT NULL,
    scope           TEXT NOT NULL
        CHECK (scope IN ('user','role','project','organization')),
    content         TEXT NOT NULL,
    rule_key        TEXT NOT NULL,                  -- superse 链锚点；同一 owner 下用作幂等（无独立 idempotency_key）
    version         INTEGER NOT NULL DEFAULT 1,     -- 版本快照号：同 rule_key 再次写入时旧版 superseded、新版 version+1（§2.4）
    status          TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','superseded')),
    superseded_by   TEXT,                           -- supersede 链：指向作废后继条目 id
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, memory_id)
);

-- 部分唯一索引：保证同一 (tenant, owner_kind, owner_id, rule_key) 下**只有一个 active 版本**。
-- 再次写入同 rule_key 时，事务内先把旧 active 置 superseded 再插入新版（§2.4 版本快照）。
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_rules_active_by_key
    ON workbench_memory_rules (tenant_id, owner_kind, owner_id, rule_key)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_memory_rules_owner
    ON workbench_memory_rules (tenant_id, owner_kind, owner_id, scope, status);

-- ---------------------------------------------------------------- 身份类画像（KV，同键覆盖）
CREATE TABLE IF NOT EXISTS workbench_memory_profile_keys (
    tenant_id    TEXT NOT NULL,
    owner_kind   TEXT NOT NULL CHECK (owner_kind IN ('user','agent')),
    owner_id     TEXT NOT NULL,
    profile_key  TEXT NOT NULL,                     -- 画像键（服务端声明，非自由文本）
    value        TEXT NOT NULL,                     -- 画像值（受长度上限校验）
    created_by   TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_kind, owner_id, profile_key)
);

-- 按 owner 列出画像的快速路径。
CREATE INDEX IF NOT EXISTS idx_memory_profile_keys_owner
    ON workbench_memory_profile_keys (tenant_id, owner_kind, owner_id);