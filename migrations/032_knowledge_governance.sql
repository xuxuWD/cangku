-- 032_knowledge_governance.sql
-- 知识治理层（知识文档生命周期 + 检索谓词守卫）。依据：
-- docs/superpowers/specs/2026-09-15-knowledge-governance-design.md §2.1-§2.4。
--
-- 约定：
--   * 租户隔离写进约束：复合主键一律以 (tenant_id, ...) 打头（与 004/022/023/029/030 同一手法）。
--   * WeKnora 检索仍是唯一事实源（D1）；本表是**文档级元数据守卫**：owner / status / 复核时间戳，
--     不复制正文、不重建索引。
--   * 状态机（§2.2）：draft → published → needs_review → archived（published → under_review →
--     needs_review → published/archived；审核由人工事件触发，到期扫描只置 needs_review 不自动归档）。
--   * owner 是发布闸门（§6.3 强制）：published 行 owner_id 必须非空（服务端校验，DB 用 NOT NULL 兜底）。
--   * 归档 = status='archived' 物理保留（重要数据软删口径延续，不物理删除）。
--   * 与 004 绑定表不建外键（文档可能尚未绑定到任何岗位/员工，解耦，同 022 手法）。

CREATE TABLE IF NOT EXISTS workbench_knowledge_documents (
    tenant_id        TEXT NOT NULL,
    document_id      TEXT NOT NULL,             -- WeKnora 侧文档 id（唯一事实源引用）
    title            TEXT NOT NULL DEFAULT '',
    owner_id         TEXT NOT NULL DEFAULT '',  -- 负责人（账号 id）；发布闸门强制非空（§6.3）
    status           TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','published','under_review','needs_review','archived')),
    version          TEXT NOT NULL DEFAULT '1', -- WeKnora 侧版本或治理层登记版本
    source_key       TEXT NOT NULL DEFAULT 'manual',  -- 登记来源（manual / migration / api）
    last_reviewed_at TIMESTAMPTZ,
    review_due_at    TIMESTAMPTZ,               -- 复核到期（事件触发或显式设定）
    registered_by    TEXT NOT NULL,             -- 登记人（账号 id）
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_docs_status
    ON workbench_knowledge_documents (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_docs_review_due
    ON workbench_knowledge_documents (tenant_id, status, review_due_at);