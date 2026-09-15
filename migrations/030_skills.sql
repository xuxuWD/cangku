-- 030_skills.sql
-- P4 技能层（技能包注册表 + 数字员工绑定）。依据：docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md §2.2。
--
-- 约定：
--   * 租户隔离写进约束：复合主键一律以 (tenant_id, ...) 打头（与 `workbench_conversations` / `workbench_memory_*` 同一手法）。
--   * 技能包 = 声明 + 版本：同 skill_key 多版本并存，只 `enabled` 版本参与会话工具面展开（§2.2）。
--   * 状态机：submitted → approved → enabled → disabled（enabled ⇄ disabled；approved ⇄ submitted；rejected 终态）。
--   * 来源白名单在**服务端**校验（部署注入 `WORKBENCH_SKILL_SOURCE_ALLOWLIST`），DB 只存 source_key，不做枚举约束
--     （白名单可随部署演进，硬编码 CHECK 会变成第二个真源）。
--   * 内容指纹 `content_sha256`：登记时计算，沙箱挂载前复核（防托管侧篡改）。
--   * 重要数据不物理删除：技能停用只改状态（disabled），不删除（历史绑定/审计仍可解析）。

-- 技能包注册表（版本多行）
CREATE TABLE IF NOT EXISTS workbench_skills (
    tenant_id       TEXT NOT NULL,
    skill_key       TEXT NOT NULL,
    version         TEXT NOT NULL,                -- 语义版本号 major.minor.patch（服务端校验 + 递增）
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    license         TEXT NOT NULL,                -- 白名单校验后的许可标识（Apache-2.0 / MIT / BSD-3）
    allowed_tools   JSONB NOT NULL,               -- allowed-tools 数组（服务端逐键校验后落库）
    status          TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted','approved','rejected','enabled','disabled')),
    source_key      TEXT NOT NULL,                -- 来源 key（须 ∈ 部署注入白名单，服务端校验）
    content_sha256  TEXT NOT NULL,                -- 包内容指纹（防篡改）
    owner_id        TEXT NOT NULL,                -- 提交人（账号 id）
    reviewed_by     TEXT,                         -- 审核人（super_admin；未审为 NULL）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, skill_key, version)
);

CREATE INDEX IF NOT EXISTS idx_workbench_skills_status
    ON workbench_skills (tenant_id, status);

-- 数字员工 ↔ 技能 绑定（租户隔离复合外键同 022 手法；agent_key 不受外键约束——员工可停用不删除，历史可解析）
CREATE TABLE IF NOT EXISTS workbench_skill_bindings (
    tenant_id   TEXT NOT NULL,
    agent_key   TEXT NOT NULL,
    skill_key   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','disabled')),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_key, skill_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_skill_bindings_skill
    ON workbench_skill_bindings (tenant_id, skill_key, status);