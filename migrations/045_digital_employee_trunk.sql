-- 045_digital_employee_trunk.sql
-- B2「数字员工干线」—— 归属 + 共享 + 岗位模板 + `soul_md` + 值班时段。
--
-- 依据：
--   · 数据模型真源 = B1 规格 §3.3（`docs/superpowers/specs/2026-09-22-desktop-execution-and-client-merge-design.md`）
--   · 施工材料 = `docs/contracts/b2-construction-plan-2026-09-24.md` §1
--   · 裁决：D-057（B2 立项；V1=做主动值班 / V2=允许租户自定义岗位 / V4=加 `soul_md`）
--           D-058④（N-a 模板落法 / N-b 要 `is_builtin` / N-c `duty_window` = 时段 + 动作白名单）
--   · 已有实例：`workbench_digital_employees` 由 022 建、023/024 增列；本文件是它的第 4 次结构变更。
--
-- ⚠️ 为什么 `owner_user_id` 要加「非空串」约束（本迁移最关键的一处）：
--   022 把 `created_by` 定为 **`TEXT NOT NULL`** —— 它**允许空字符串**。
--   ⇒ 若存量行 `created_by = ''`，下面第 ② 步的回填会把空串搬进 `owner_user_id`，
--     而 `ALTER COLUMN ... SET NOT NULL` **拦不住空串** ⇒ **迁移"成功"了，数据是垃圾的**，
--     要等线上"某个员工看不见自己的数字员工"才会被发现。
--   ⇒ 本迁移用**声明式守卫**（`CHECK (owner_user_id <> '')`）把它变成 **fail-closed**：
--     一旦存在空串归属人，回填/加约束即撞约束 ⇒ **整个迁移事务回滚**（`app/migrations.py`
--     把整个文件包在一个事务里），不会留下半成品。
--   ⇒ **因此不再需要"先跑一条只读 SQL"作为人工前置** —— 数据库自己会挡住。
--     报错形如：`check constraint "workbench_digital_employees_owner_not_blank" of relation
--     "workbench_digital_employees" is violated by some row`
--     **看到该报错 ⇒ 说明存量 `created_by` 有空串，须先决定兜底归属或清脏数据，再重跑本迁移。**
--
-- 回退（按 change-record 口径，不用 CASCADE）：
--   DROP TABLE IF EXISTS workbench_role_templates;
--   DROP TABLE IF EXISTS workbench_employee_shares;
--   DROP INDEX IF EXISTS idx_wde_owner;
--   ALTER TABLE workbench_digital_employees DROP CONSTRAINT IF EXISTS workbench_digital_employees_owner_not_blank;
--   ALTER TABLE workbench_digital_employees DROP CONSTRAINT IF EXISTS workbench_digital_employees_visibility_valid;
--   ALTER TABLE workbench_digital_employees DROP COLUMN IF EXISTS duty_window;
--   ALTER TABLE workbench_digital_employees DROP COLUMN IF EXISTS soul_md;
--   ALTER TABLE workbench_digital_employees DROP COLUMN IF EXISTS owner_user_id;
--   ALTER TABLE workbench_digital_employees DROP COLUMN IF EXISTS visibility;
--   DELETE FROM workbench_schema_migrations WHERE version = '045_digital_employee_trunk';
--
-- ⚠️ 租户模板链：新表与新增列**均属 A 组（租户表）** ⇒ 平台链（本文件）与租户模板链
--   （`migrations/tenant_template/0001_tenant_baseline.sql` + `classification.json`）**必须同步**，
--   改完跑 `py scripts/tenant_schema.py verify --apply`。详见 `migrations/tenant_template/README.md`。

-- ① `workbench_digital_employees` 加 4 列 -----------------------------------------------------

-- ①-1 可见性档位。**默认 `private`** —— 最保守，不因迁移而扩大任何行的可见范围。
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE workbench_digital_employees
    DROP CONSTRAINT IF EXISTS workbench_digital_employees_visibility_valid;
ALTER TABLE workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_visibility_valid
    CHECK (visibility IN ('private', 'shared'));

-- ①-2 归属人。先加可空列 → ② 回填 → 再加两道守卫。
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT;

-- ①-3 `soul_md`（D-057 V4=A）：与 `system_prompt`（"怎么做"）分工，承载"是谁"（气质 / 价值观）。
--      ⚠️ 默认空串而非 NULL —— 与规格 §4.3 的模板字段结构一致（那边也是 `NOT NULL DEFAULT ''`）。
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS soul_md TEXT NOT NULL DEFAULT '';

-- ①-4 `duty_window`（D-057 V1=B + D-058④ N-c）：主动值班的**时段 + 动作白名单**。
--      ⚠️ 必须是 JSONB 而不是两个时间列 —— V1 的口径是「**只做不需审批的动作**」，
--      所以它必须能表达"哪些动作"，不只是"几点到几点"。只写时段则该口径**落不了地**。
--      具体形状（键名）以 B2 规格 §4 定稿为准；本迁移只保证它是**对象**。
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS duty_window JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE workbench_digital_employees
    DROP CONSTRAINT IF EXISTS workbench_digital_employees_duty_window_is_object;
ALTER TABLE workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_duty_window_is_object
    CHECK (jsonb_typeof(duty_window) = 'object');

-- ② 回填 `owner_user_id` 并加守卫 ------------------------------------------------------------
--    回填口径：存量行的归属人 = 创建人（B1 §3.3 原样，无条件、可重跑）。
UPDATE workbench_digital_employees
SET owner_user_id = created_by
WHERE owner_user_id IS NULL;

-- ⚠️ 守卫：空串不是合法归属人。**这一条就是 fail-closed 的全部机制**（理由见文件头）。
--    放在回填之后 ⇒ 报错文案是「is violated by some row」，比「new row violates」更明确。
ALTER TABLE workbench_digital_employees
    DROP CONSTRAINT IF EXISTS workbench_digital_employees_owner_not_blank;
ALTER TABLE workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_owner_not_blank
    CHECK (owner_user_id <> '');

ALTER TABLE workbench_digital_employees
    ALTER COLUMN owner_user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wde_owner
    ON workbench_digital_employees (tenant_id, owner_user_id);

-- 注意：`role_key`（复合外键 → `workbench_job_roles`）**保留不动** —— 岗位与 owner **正交**。

-- ③ 新增 `workbench_employee_shares`（共享层，两档 `read` / `use`）-----------------------------
--    两档语义（B1 §3.3②）：`read` = 能看配置、看它干过的活，**不能派活**；
--                          `use`  = 能派活，**不能改配置、不能停用**。
--    ⚠️ **刻意复用** P2c-6 会话成员表（迁移 039）的两档心智模型，不引入第二套。
CREATE TABLE IF NOT EXISTS workbench_employee_shares (
    tenant_id       TEXT NOT NULL,
    agent_key       TEXT NOT NULL,
    grantee_user_id TEXT NOT NULL,
    permission      TEXT NOT NULL CHECK (permission IN ('read', 'use')),
    granted_by      TEXT NOT NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_key, grantee_user_id),
    FOREIGN KEY (tenant_id, agent_key)
        REFERENCES workbench_digital_employees (tenant_id, agent_key)
);

-- 授权人不得是空串（与 ② 的归属人守卫同一理由：空串不是身份）。
ALTER TABLE workbench_employee_shares
    DROP CONSTRAINT IF EXISTS workbench_employee_shares_no_blank_users;
ALTER TABLE workbench_employee_shares
    ADD CONSTRAINT workbench_employee_shares_no_blank_users
    CHECK (grantee_user_id <> '' AND granted_by <> '');

CREATE INDEX IF NOT EXISTS idx_workbench_employee_shares_grantee
    ON workbench_employee_shares (tenant_id, grantee_user_id);

-- ④ 新增 `workbench_role_templates`（**因 D-057 V2=B 而新增**）--------------------------------
--    ⚠️ 此前建议是「代码内常量、不建表」；**用户裁 V2=允许租户自定义岗位 ⇒ 必须建表**，
--       且「模板是产品预设，改它该走代码评审」这个理由**随之不成立**（改模板从此是 DB 操作，
--       须另设治理口径）。见 B2 规格 §3.2 的就地标注。
--    字段名**逐字取自 B2 规格 §4.3 的模板字段结构**，不是本迁移自造。
CREATE TABLE IF NOT EXISTS workbench_role_templates (
    tenant_id              TEXT NOT NULL,
    role_key               TEXT NOT NULL,                       -- 规格 §4.3 的键名
    display_name           TEXT NOT NULL,
    soul_md                TEXT NOT NULL DEFAULT '',            -- 「是谁」
    system_prompt          TEXT NOT NULL DEFAULT '',            -- 「怎么做」
    default_tool_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_skills         JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_autonomy_level TEXT NOT NULL DEFAULT 'approval_for_risky',
    -- D-058④ N-b：区分**平台预置**与**租户自建**。
    -- ⚠️ 没有它，租户改预置模板会改到**所有租户看到的基线**。
    is_builtin             BOOLEAN NOT NULL DEFAULT false,
    created_by             TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_key)
);

ALTER TABLE workbench_role_templates
    DROP CONSTRAINT IF EXISTS workbench_role_templates_json_shapes;
ALTER TABLE workbench_role_templates
    ADD CONSTRAINT workbench_role_templates_json_shapes
    CHECK (
        jsonb_typeof(default_tool_allowlist) = 'array'
        AND jsonb_typeof(default_skills) = 'array'
    );

CREATE INDEX IF NOT EXISTS idx_workbench_role_templates_builtin
    ON workbench_role_templates (tenant_id, is_builtin);

-- ⑤ **种子数据：本迁移不写**（如实登记，勿读成遗漏）-----------------------------------------
--    D-058④ N-a 裁定「**平台级一份 + 租户可覆盖**」，但**"一份"落在哪张表、怎么覆盖，
--    规格与施工方案都未给到可执行的形态**：
--      · 读法甲：预置定义只有一份（平台级），租户行按需物化 —— 需定**物化时机**与**哨兵租户**问题；
--      · 读法乙：预置在每个租户各存一份 `is_builtin=true` 的行，靠 `is_builtin` 区分并支持覆盖
--                —— 需定**平台升级时如何统一更新各租户的预置行**。
--    两条读法在**覆盖语义**与**升级路径**上并不等价，**本迁移不替规格预判**（宪法：不臆造）。
--    ⇒ 种子作为**独立后续迁移** `046_*` 落地，前置 = 上述读法定案。
--    ⇒ 在此之前 `workbench_role_templates` 为空表；`is_builtin` 列已就位，不阻塞定案。
