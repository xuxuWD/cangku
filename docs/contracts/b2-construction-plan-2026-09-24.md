# B2 施工方案（2026-09-24 · 按 D-057 裁决后的口径）

> **性质**：**施工材料，不是真源**。权威仍在 B2 规格（已按 D-057 回写）与 **B1 规格 §3.3**（数据模型定义在**那里**）。
> **前置**：用户 2026-09-24 裁决 —— **立项**；V1=**做**主动值班（**仅限不需审批的动作**）；V2=**允许**租户自定义岗位；V4=**加** `soul_md`。
> **与 [`b2-review-2026-09-23.md`](b2-review-2026-09-23.md) 的差异**：那份写的时候三项都还没裁；**裁决落地后迁移面变大**（+1 张表、+2 处字段）。本文以本文为准。

---

## 0. 一句话

**B2 的迁移从"加 2 列 + 建 1 表"变成"加 4 列 + 建 2 表"**，且**建表是新增的**（V2 选"允许" ⇒ 岗位模板不能再走代码常量）。
**动手前必须先跑一条只读 SQL**（见 §5），否则回填会把空串当归属人**静默写坏**。

---

## 1. 迁移 045 要做什么（5 块）

### ① 改 `workbench_digital_employees` —— 加 4 列（其中 2 列来自 B1 §3.3，2 列来自 D-057）

```sql
-- 来自 B1 §3.3（原样）
ALTER TABLE workbench_digital_employees
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
    CHECK (visibility IN ('private', 'shared'));
ALTER TABLE workbench_digital_employees ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
UPDATE workbench_digital_employees SET owner_user_id = created_by WHERE owner_user_id IS NULL;
ALTER TABLE workbench_digital_employees ALTER COLUMN owner_user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wde_owner ON workbench_digital_employees (tenant_id, owner_user_id);

-- 来自 D-057 V4=A（新）——"是谁"那一层，与 system_prompt（"怎么做"）分工
ALTER TABLE workbench_digital_employees
  ADD COLUMN IF NOT EXISTS soul_md TEXT NOT NULL DEFAULT '';

-- 来自 D-057 V1=B（新）—— 主动值班的"上班时段"（口径受限，见 §3）
ALTER TABLE workbench_digital_employees
  ADD COLUMN IF NOT EXISTS duty_window JSONB NOT NULL DEFAULT '{}'::jsonb;
```

> `duty_window` 设计为 JSONB，承载**上班时段 + 允许的动作白名单**（因为 V1 的口径是"只做不需审批的动作"，
> 所以它必须能表达"哪些动作"而不只是"几点到几点"）。**具体形状待规格 §4 定稿**（本文不预造字段名）。
> `role_key`（复合外键指向 `workbench_job_roles`）**保留不动** —— 岗位与 owner **正交**。

### ② 新增 `workbench_employee_shares`（共享层，来自 B1 §3.3，两档 `read` / `use`）

```sql
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
```

### ③ 新增 `workbench_role_templates`（**因 V2=B 而新增**，此前建议走代码常量）

```sql
CREATE TABLE IF NOT EXISTS workbench_role_templates (
  tenant_id     TEXT NOT NULL,
  template_key  TEXT NOT NULL,
  name          TEXT NOT NULL,
  soul_md       TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL DEFAULT '',
  tool_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_threshold TEXT NOT NULL DEFAULT 'high' CHECK (risk_threshold IN ('low','medium','high')),
  is_builtin    BOOLEAN NOT NULL DEFAULT false,   -- 6 类预置 = true；租户自建 = false
  created_by    TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, template_key)
);
```

> ⚠️ **字段名本文是"按现有表对齐推的"，不是规格原文**（规格 §3.2 只写了"须建表"，没给 DDL）。
> **落地前必须与 B1 §3.3 / 规格 §4 对一遍**。
> ⚠️ `is_builtin` 是**本文新增的**：6 类预置与租户自建**必须能区分**（否则租户改预置模板会污染所有租户的基线）。
> 规格对这一点**未表态** ⇒ **需补裁决**。

### ④ 6 类预置模板的种子数据

**⚠️ 这里有个未决问题**：模板建表后，预置是**每个租户各写一份**（迁移时为已有租户插入）
还是**只留平台级一份**？规格与 B1 §3.3 **都未表态**。⇒ **需补裁决**（见 §6）。

### ⑤ 租户模板链同步（**最容易漏**）

`workbench_digital_employees` 在 `migrations/tenant_template/0001_tenant_baseline.sql` 里出现 **12 次**，
`workbench_employee_shares` / `workbench_role_templates` 是**新表**。⇒ 三处都要改：

| # | 文件 | 改什么 |
| --- | --- | --- |
| 1 | **新增** `migrations/045_*.sql` | 上面 ①–④（当前最大编号 = **044**，已实测） |
| 2 | `migrations/tenant_template/0001_tenant_baseline.sql` | 同步加 4 列 + 2 新表 |
| 3 | `migrations/tenant_template/classification.json` | **两张新表必须登记**（否则归类清单与实际不符） |

改完**必须跑** `scripts/tenant_schema.py verify --apply`（S0 期就是靠它抓出"模板漏自增序列"的）。

---

## 2. 闸门：**拆成三档**（这是 B2 最硬的一块）

### 现状（实测）

```python
# app/main.py:1362
def _require_workforce_directory_admin(context):
    if context.role != "super_admin":
        raise HTTPException(403, "只有超级管理员可以管理岗位与数字员工目录")
```

**一个函数守着 10 个端点**（实测调用点：`roles` 的 GET/POST/PATCH、`agents` 的 GET/POST/PATCH、
`candidates` GET、`agents/{key}/config` GET，及另 2 处未定位）。

### ⚠️ 不能"放宽它"

只把 `role != "super_admin"` 改宽，会**同时放开**：建/改岗位、改/停用**别人的**员工、
读**任意**员工的 `config`（提示词 / 模型 / 日预算 / 审批档）。
而 B2 给 `use` 档定的语义明确写着「**能派活；不能改配置、不能停用**」—— **直接冲突**。

### 拆法（建议）

| 新闸门 | 覆盖 | 口径 |
| --- | --- | --- |
| ① `_require_directory_reader` | `roster` / `agents` 列表 | 四档角色 + **按 `owner_user_id` / `visibility` / shares 过滤**（**过滤在仓储层做，不是在路由层**） |
| ② `_require_employee_creator`（新） | 员工侧创建 | 四档 + **owner 只能是自己** + **只能从模板创建** |
| ③ `_require_workforce_directory_admin`（**原函数不动**） | `roles` 增改 / `agents` 改停用 / **config 读写** | **保持仅 `super_admin`** |

**⚠️ 按宪法这是「地基级」（权限模型）变更 ⇒ 应单列评审**，不要混在"补接口"里过。

---

## 3. V1 的口径：主动值班**只做不需审批的动作**

用户 2026-09-24 裁决：做主动值班，但**只做不需审批的动作**（生成草案 / 整理类），**不碰高风险工具**
⇒ **无人值守时无需人工审批** ⇒ **与九步闸门不冲突**。

**⚠️ 这条口径的实现要求（本文提出，规格未写）**：
1. `duty_window` 必须能表达**动作白名单**（不只是一段时间），否则无法保证"只做不需审批的动作"
2. **服务端必须二次判定**动作是否需审批 —— **不能只靠前端/配置**（宪法：一切输入默认不可信）
3. 值班产出应落在**审批前的产物**（草案），**不得直接产生副作用**

**⇒ 这三条建议补进 B2 规格 §4 或 §7**（现在还没写）。

---

## 4. 接口变更（C1–C5，按 `api-contract.md` 核对后的真实归类）

| # | 原话 | **真实结论** |
| --- | --- | --- |
| **C1** | 新增员工侧创建 | 🔴 **不是新增** —— `POST /workforce/agents` **早已存在**（契约 597 行、实现 `app/main.py:1566`，调 `workforce_directory_service.create_employee`）⇒ 实为**拆闸门 + 复用 + 加"从模板填默认"** |
| **C2** | 新增读岗位模板列表 | 🟠 与既有 `GET /workforce/roles`（契约 577 行）**关系待划清**；**V2=B 后模板落库** ⇒ 两者更像，边界更须写明 |
| **C3** | 变更目录可见性 | ✅ 改 `GET /workforce/agents` 的**过滤**；响应体加 `owner_user_id` / `visibility`（现响应含 `created_by` 但没有这两个） |
| **C4** | 新增共享管理 | ✅ **真·新增**（对齐 P2c-6 成员表三端点形态） |
| **C5** | 变更 `autonomy_level` 文案 | ✅ 落点 = 契约 767/768 行（`/config` 那节）。⚠️ **V1=C 口径之后，这一档要能表达"值班只做不需审批的动作"**，措辞需重想 |

**⚠️ 铁律（规格 §5 自述）：五项全部先落 `api-contract.md`，评审通过后才写实现。**

---

## 5. 🔴 动手前的**第一件事**：跑那条只读 SQL

```sql
-- ① 空串/空值各多少
SELECT count(*) FROM workbench_digital_employees WHERE created_by IS NULL OR created_by = '';
```

**为什么必须**：实测 `migrations/022_workforce_directory.sql:15` 是 `created_by TEXT NOT NULL`
⇒ 那句 `SET NOT NULL` **永远不会因 NULL 而失败**；
但若存量行是**空字符串**，回填后 `owner_user_id` 就是**空串**，`SET NOT NULL` **拦不住空串**
⇒ **迁移"成功"了，数据是垃圾的**，要等线上"某个员工看不见自己的员工"才发现。

**若 ① > 0** ⇒ **不能照抄 B1 §3.3 的 UPDATE**，要先决定兜底归属或清脏数据。

---

## 6. ⚠️ 落地前**还需要裁决**的三点（本文提出的新问题）

| # | 问题 | 为什么必须定 |
| --- | --- | --- |
| **N-a** | **6 类预置模板怎么落**：每租户各写一份，还是平台级一份 + 租户覆盖？ | 决定迁移 045 的种子写法；也决定"租户改预置"会不会污染基线 |
| **N-b** | **`is_builtin` 要不要**（区分预置与租户自建） | 没有它，租户改预置模板会改到所有租户看到的基线 |
| **N-c** | **`duty_window` 的形状** —— 只是时段，还是"时段 + 动作白名单"？ | V1=C 的口径**要求它必须能表达动作范围**，否则"只做不需审批的动作"落不了地 |

---

## 7. 施工顺序（建议）

```
①  跑只读 SQL（§5）                     ← 只能在你的真库上跑
②  补裁决 N-a / N-b / N-c（§6）          ← 否则迁移写法定不下来
③  改 api-contract.md（C1–C5）           ← 铁律：先契约后代码
④  拆闸门（§2 的三档）                    ← 地基级，单列评审
⑤  写迁移 045（§1 的五块）
⑥  同步租户模板 0001 + classification.json
⑦  scripts/tenant_schema.py verify --apply
⑧  实现（接口 → 服务 → 前端）
⑨  验收
```

**前端侧**：F2（补路由）**已完成**（换壳时落地）；F1 卡 C3；F3 待 `owner_user_id` 落地；F4 依赖 C1+C2。

---

## 8. 未验证（不得读成已验）

1. **本文的三张表 DDL 中，只有 `workbench_employee_shares` 来自规格原文**（B1 §3.3）；
   `workbench_role_templates` 与两个新列（`soul_md` / `duty_window`）是**本文按现有表对齐推的**，
   **规格没有给 DDL**。⇒ **落地前必须与规格 §4 / B1 §3.3 对齐**。
2. **B2 规格 §2.2 / §4 / §7 / §8 本文作者仍未读** ⇒ 创建流程五步、验收标准、与既有能力的关系均未纳入。
3. **`workforce_directory_service.create_employee` 未读** ⇒ "可复用于模板创建"是推断。
4. **闸门 10 处调用点只逐行定位了 8 处**。
5. **`GET /workforce/roles` 响应形状未读** ⇒ C2 与它的边界只能说"待划清"。
6. **`created_by` 空串实际条数未查**（需真库）。
7. **未运行任何测试**；本文**未改动任何文件**。
