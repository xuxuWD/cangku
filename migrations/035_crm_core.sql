-- 035_crm_core.sql
-- P5a 企业级智能化 CRM（客户主数据 + 商务主线 + 智能化打底，12 表）。
-- 依据：docs/superpowers/specs/2026-09-17-crm-p5a-design.md §2.1（已评审，2026-09-17）。
--
-- 约定：
--   * 租户隔离写进约束：业务表一律复合主键 (tenant_id, ...) 打头，跨租户引用由复合外键在库层直接拒绝
--     （与 workbench_conversations / workbench_memory_facts 同一手法）。
--   * owner_id 存账号 id 但**不加外键**（同 agent_key —— 历史数据必须永远可解析）。
--   * 软删除：业务表带 deleted_at；append-only 表（阶段事件 / 智能化记录）与明细表（报价行）不带。
--   * 金额一律 BIGINT 整数分（宪法：禁用浮点）；数量 NUMERIC(12,3) 精确；税率万分比整数（13% = 1300）。
--   * 敏感字段（contacts.phone/email、leads.phone/email）为**字段级密级**：默认掩码、不进 AI 输入、
--     不经工具输出、不落日志与审计（§2.2）；本迁移只建列，密级在应用层强制。
--   * 状态一致性由 CHECK 兜底（写入路径只有状态机）：closed_at / confirmed_at / signed_at / paid_cents。
--   * 健康度未计算 = NULL（不伪造分数）；(health_score IS NULL) = (health_band IS NULL) 锁死配对。

-- ① 客户（公司）
CREATE TABLE IF NOT EXISTS workbench_crm_accounts (
    tenant_id     TEXT NOT NULL,
    account_id    TEXT NOT NULL,
    name          TEXT NOT NULL,
    industry      TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'lead_converted', 'api')),
    owner_id      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    health_score       INTEGER CHECK (health_score BETWEEN 0 AND 100),
    health_band        TEXT CHECK (health_band IN ('green', 'yellow', 'red')),
    health_computed_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, account_id),
    CHECK ((health_score IS NULL) = (health_band IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_wb_crm_accounts_owner
    ON workbench_crm_accounts (tenant_id, owner_id, status) WHERE deleted_at IS NULL;

-- ② 联系人（敏感字段 phone / email：字段级密级）
CREATE TABLE IF NOT EXISTS workbench_crm_contacts (
    tenant_id     TEXT NOT NULL,
    contact_id    TEXT NOT NULL,
    account_id    TEXT,
    name          TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    is_primary    BOOLEAN NOT NULL DEFAULT false,
    birthday      DATE,
    owner_id      TEXT NOT NULL,
    custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, contact_id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES workbench_crm_accounts (tenant_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_wb_crm_contacts_account
    ON workbench_crm_contacts (tenant_id, account_id) WHERE deleted_at IS NULL;

-- ③ 线索（敏感字段 phone / email）
CREATE TABLE IF NOT EXISTS workbench_crm_leads (
    tenant_id       TEXT NOT NULL,
    lead_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    company         TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'manual',
    owner_id        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'converted', 'dropped')),
    converted_account_id     TEXT,
    converted_contact_id     TEXT,
    converted_opportunity_id TEXT,
    custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, lead_id)
);

-- ④ 商机（金额整数分；stage_entered_at = 账龄事实源）
CREATE TABLE IF NOT EXISTS workbench_crm_opportunities (
    tenant_id         TEXT NOT NULL,
    opportunity_id    TEXT NOT NULL,
    account_id        TEXT NOT NULL,
    name              TEXT NOT NULL,
    stage             TEXT NOT NULL DEFAULT 'qualification'
        CHECK (stage IN ('qualification', 'proposal', 'negotiation', 'won', 'lost')),
    amount_cents      BIGINT NOT NULL DEFAULT 0 CHECK (amount_cents >= 0),
    expected_close    DATE,
    owner_id          TEXT NOT NULL,
    stage_entered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at         TIMESTAMPTZ,
    custom_fields     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, opportunity_id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES workbench_crm_accounts (tenant_id, account_id),
    CHECK ((stage IN ('won', 'lost')) = (closed_at IS NOT NULL))
);

-- ⑤ 商机阶段事件（append-only：转化率 / 账龄 / 销售周期的事实源）
CREATE TABLE IF NOT EXISTS workbench_crm_opportunity_stage_events (
    tenant_id       TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    opportunity_id  TEXT NOT NULL,
    from_stage      TEXT,
    to_stage        TEXT NOT NULL,
    amount_cents    BIGINT NOT NULL DEFAULT 0,
    actor_id        TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id, opportunity_id)
        REFERENCES workbench_crm_opportunities (tenant_id, opportunity_id)
);
CREATE INDEX IF NOT EXISTS idx_wb_crm_stage_events_opportunity
    ON workbench_crm_opportunity_stage_events (tenant_id, opportunity_id, occurred_at);

-- ⑥ 跟进活动（时间线）
CREATE TABLE IF NOT EXISTS workbench_crm_activities (
    tenant_id      TEXT NOT NULL,
    activity_id    TEXT NOT NULL,
    kind           TEXT NOT NULL
        CHECK (kind IN ('call', 'meeting', 'email', 'note', 'task')),
    subject        TEXT NOT NULL DEFAULT '',
    content        TEXT NOT NULL DEFAULT '',
    account_id     TEXT,
    contact_id     TEXT,
    opportunity_id TEXT,
    owner_id       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'done'
        CHECK (status IN ('planned', 'done', 'cancelled')),
    due_at         TIMESTAMPTZ,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reminded_on    DATE,
    created_by_kind TEXT NOT NULL DEFAULT 'human'
        CHECK (created_by_kind IN ('human', 'agent')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at     TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, activity_id),
    FOREIGN KEY (tenant_id, account_id)     REFERENCES workbench_crm_accounts (tenant_id, account_id),
    FOREIGN KEY (tenant_id, contact_id)     REFERENCES workbench_crm_contacts (tenant_id, contact_id),
    FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities (tenant_id, opportunity_id)
);
CREATE INDEX IF NOT EXISTS idx_wb_crm_activities_timeline
    ON workbench_crm_activities (tenant_id, account_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_wb_crm_activities_due
    ON workbench_crm_activities (tenant_id, owner_id, due_at)
    WHERE status = 'planned' AND deleted_at IS NULL;

-- ⑦ 报价单
CREATE TABLE IF NOT EXISTS workbench_crm_quotes (
    tenant_id       TEXT NOT NULL,
    quote_id        TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    opportunity_id  TEXT,
    quote_no        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'confirmed', 'converted', 'voided')),
    subtotal_cents  BIGINT NOT NULL DEFAULT 0 CHECK (subtotal_cents >= 0),
    tax_cents       BIGINT NOT NULL DEFAULT 0 CHECK (tax_cents >= 0),
    total_cents     BIGINT NOT NULL DEFAULT 0 CHECK (total_cents >= 0),
    valid_until     DATE,
    confirmed_at    TIMESTAMPTZ,
    converted_contract_id TEXT,
    owner_id        TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, quote_id),
    UNIQUE (tenant_id, quote_no),
    FOREIGN KEY (tenant_id, account_id)     REFERENCES workbench_crm_accounts (tenant_id, account_id),
    FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities (tenant_id, opportunity_id),
    CHECK ((status IN ('confirmed', 'converted')) = (confirmed_at IS NOT NULL))
);

-- ⑧ 报价行（draft 态整单全量替换，金额由服务端重算）
CREATE TABLE IF NOT EXISTS workbench_crm_quote_lines (
    tenant_id           TEXT NOT NULL,
    quote_id            TEXT NOT NULL,
    line_no             INTEGER NOT NULL CHECK (line_no >= 1),
    description         TEXT NOT NULL,
    qty                 NUMERIC(12, 3) NOT NULL CHECK (qty > 0),
    unit_price_cents    BIGINT NOT NULL CHECK (unit_price_cents >= 0),
    tax_rate_bp         INTEGER NOT NULL DEFAULT 0 CHECK (tax_rate_bp BETWEEN 0 AND 10000),
    line_subtotal_cents BIGINT NOT NULL CHECK (line_subtotal_cents >= 0),
    line_tax_cents      BIGINT NOT NULL CHECK (line_tax_cents >= 0),
    PRIMARY KEY (tenant_id, quote_id, line_no),
    FOREIGN KEY (tenant_id, quote_id) REFERENCES workbench_crm_quotes (tenant_id, quote_id)
);

-- ⑨ 合同（签署与进度人工化：合同 / 签署件走对象存储引用；回款人工登记；二期接签署 provider）
CREATE TABLE IF NOT EXISTS workbench_crm_contracts (
    tenant_id       TEXT NOT NULL,
    contract_id     TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    quote_id        TEXT,
    opportunity_id  TEXT,
    contract_no     TEXT NOT NULL,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'pending_sign', 'signed', 'voided', 'expired')),
    amount_cents    BIGINT NOT NULL DEFAULT 0 CHECK (amount_cents >= 0),
    paid_cents      BIGINT NOT NULL DEFAULT 0 CHECK (paid_cents >= 0),
    starts_on       DATE,
    ends_on         DATE,
    document_object_key TEXT NOT NULL DEFAULT '',
    signed_at       TIMESTAMPTZ,
    owner_id        TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, contract_id),
    UNIQUE (tenant_id, contract_no),
    FOREIGN KEY (tenant_id, account_id)     REFERENCES workbench_crm_accounts (tenant_id, account_id),
    FOREIGN KEY (tenant_id, quote_id)       REFERENCES workbench_crm_quotes (tenant_id, quote_id),
    FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities (tenant_id, opportunity_id),
    CHECK (paid_cents <= amount_cents),
    CHECK ((status = 'signed') = (signed_at IS NOT NULL))
);

-- ⑩ 智能化生成记录（append-only：跟进计划等；只存结果与引用，不存模型输入原文）
CREATE TABLE IF NOT EXISTS workbench_crm_insights (
    tenant_id      TEXT NOT NULL,
    insight_id     TEXT NOT NULL,
    account_id     TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'followup_plan'
        CHECK (kind IN ('followup_plan', 'account_review')),
    input_digest   TEXT NOT NULL,
    content        JSONB NOT NULL,
    evidence_refs  JSONB NOT NULL DEFAULT '[]'::jsonb,
    dropped_refs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_key      TEXT NOT NULL,
    generated_by   TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, insight_id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts (tenant_id, account_id)
);

-- ⑪ 目标（月粒度；目标达成度的事实源）
CREATE TABLE IF NOT EXISTS workbench_crm_targets (
    tenant_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    owner_id            TEXT NOT NULL,
    period_month        DATE NOT NULL,
    amount_target_cents BIGINT NOT NULL DEFAULT 0 CHECK (amount_target_cents >= 0),
    count_target        INTEGER NOT NULL DEFAULT 0 CHECK (count_target >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, target_id),
    UNIQUE (tenant_id, owner_id, period_month)
);

-- ⑫ 自定义字段元数据（元数据表 + 各对象 custom_fields JSONB）
CREATE TABLE IF NOT EXISTS workbench_crm_field_defs (
    tenant_id   TEXT NOT NULL,
    object_key  TEXT NOT NULL
        CHECK (object_key IN ('account', 'contact', 'lead', 'opportunity', 'activity')),
    field_key   TEXT NOT NULL CHECK (field_key ~ '^[a-z][a-z0-9_]{0,63}$'),
    label       TEXT NOT NULL,
    field_type  TEXT NOT NULL CHECK (field_type IN ('text', 'number', 'date', 'select', 'bool')),
    required    BOOLEAN NOT NULL DEFAULT false,
    options     JSONB NOT NULL DEFAULT '[]'::jsonb,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, object_key, field_key)
);