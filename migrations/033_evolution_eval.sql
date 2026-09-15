-- 033_evolution_eval.sql
-- P6a 自进化·评测集基础设施（用例库 + 评测运行 + 逐例结果）。依据：
-- docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md §2.7（A2 裁决：P6a 先行）。
--
-- 约定：
--   * 租户隔离写进约束：复合主键一律以 (tenant_id, ...) 打头；结果表对运行/用例建**复合外键**
--     ⇒ 跨租户引用在 DB 层直接失败（与 023/030/032 同一手法）。
--   * 用例**软删**：status='archived' + superseded_by 链到新条目（不物理删除；§2.3）。
--   * 评测明细**不落正文**：结果表只落判定与计数（detail JSONB 由服务端限定为受控短值）。
--   * 指针表（workbench_skill_pointers）与效用表（workbench_skill_outcomes）属 **P6b**
--     （候选生成 / 灰度 / 回滚，须 D13 判据达标后开工）——**本迁移不建**，避免为未开工能力预先落库。

CREATE TABLE IF NOT EXISTS workbench_eval_cases (
    tenant_id      TEXT NOT NULL,
    case_id        TEXT NOT NULL,             -- 服务端生成（case-<hex>）或固定回归基线 id
    suite_key      TEXT NOT NULL,             -- 套件（如 runtime-safety / gate-blocked）
    source         TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('run_trace','manual','regression')),
    status         TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','published','archived')),
    input_snapshot JSONB NOT NULL,            -- 脱敏快照（服务端拒绝敏感键；不落正文以外的东西）
    input_digest   TEXT NOT NULL,             -- 快照指纹（去重与套件指纹）
    expectation    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 期望（发布闸门要求可执行）
    superseded_by  TEXT,                      -- 被替代链（软删指向新条目）
    created_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_eval_cases_suite
    ON workbench_eval_cases (tenant_id, suite_key, status);

CREATE INDEX IF NOT EXISTS idx_eval_cases_digest
    ON workbench_eval_cases (tenant_id, suite_key, input_digest);

CREATE TABLE IF NOT EXISTS workbench_eval_runs (
    tenant_id    TEXT NOT NULL,
    eval_run_id  TEXT NOT NULL,
    subject      TEXT NOT NULL,               -- 受评对象（v1：runtime-safety-probe；P6b：候选技能引用）
    suite_key    TEXT NOT NULL,
    suite_digest TEXT NOT NULL,               -- 当次所用用例集指纹（事后可验证「考了什么」）
    status       TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('completed','aborted')),
    case_count   INTEGER NOT NULL DEFAULT 0 CHECK (case_count >= 0),
    pass_count   INTEGER NOT NULL DEFAULT 0 CHECK (pass_count >= 0),
    cost_cents   INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),  -- 整数分（不用浮点）
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, eval_run_id),
    CHECK (pass_count <= case_count)
);

CREATE TABLE IF NOT EXISTS workbench_eval_case_results (
    tenant_id    TEXT NOT NULL,
    eval_run_id  TEXT NOT NULL,
    case_id      TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    detail       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 只落判定与计数，不落正文
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, eval_run_id, case_id),
    FOREIGN KEY (tenant_id, eval_run_id)
        REFERENCES workbench_eval_runs (tenant_id, eval_run_id),
    FOREIGN KEY (tenant_id, case_id)
        REFERENCES workbench_eval_cases (tenant_id, case_id)
);