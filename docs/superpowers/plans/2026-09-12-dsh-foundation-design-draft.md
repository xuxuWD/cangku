# P2a 段二 地基设计草案（迁移 027 + 执行/授权/幂等落点）

> **性质**：**设计草案**，**不是阶段规格**。用途：满足宪法「铁律四（地基不随手翻）」「4.4 六步⑥（先出设计文件再建表）」与**三轮评审共同指出的根因——"把承诺写细了，却始终没有落点"**。
> **上位**：[段二规格](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-dsh-integration-design.md)（**已评审（附记录） · 2026-09-13**）、[评审记录](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md)（首轮 §2–§6、重审 §7、第三轮结论）。
> **状态**：**已归档（2026-09-13）**。**§1–§5 已按用户裁决 R5 并入段二规格 §4.1「迁移 `027` 设计（附录）」**（含两张新表 DDL、对既有表 `workbench_run_records` 的 `UNIQUE (run_id, tenant_id)` 增补、参数规范化算法、主从/事务/回退、装配与失败语义）。**本文件自即日起转为归档**，**不再作为评审或实现依据**；后续修订一律在段二规格 §4.1 与 `migrations/027_*.sql` 上进行（宪法 2.2「一份文档一个职责」）。裁决与依据见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md) §8.7 / §8.9。
> **日期**：2026-09-12

## 0. 本草案要补的"落点"（三轮评审收敛的根因清单）

| 编号 | 三轮一致的诊断 | 本草案给的落点 |
| --- | --- | --- |
| **B5** | `Idempotency-Key` 改对了载体，但"返回既有结果"**无存储可依** | §3 幂等表 + 取回顺序 |
| **B2** | ⑦ 要"参数摘要"，但**参数无承载**、**规范化算法未定义** | §2 冻结动作 + §4 算法（含单测判据） |
| **B4** | 审批决议端点**拿不到**工具目录/容器执行器/工作卷，装配方式未写 | §5 装配点与调用链 + 失败语义表 |
| **027** | 只有"一句话职责"，**无 schema**（地基变更评审信息不足） | §1 完整 DDL |
| **新增（评审 C/F5）** | `workbench_run_records` 只有 `PK(run_id)`，**无 `UNIQUE(run_id, tenant_id)`** → 复合外键不可成立，单列外键会丢租户维度 | §1.2 显式增补唯一约束 |
| **新增（评审 C/F2）** | 027 与 026 形成**两个授权事实源** | §1.4 主从关系与事务边界 |

---

## 1. 迁移 `027`：DDL 草案

**文件命名**：`migrations/027_dsh_tool_execution.sql`（迁移机制按 `sorted(glob)` 顺序执行并记账于 `workbench_schema_migrations`，**无自动回滚**，故顺序必须在 `026` 之后）。

### 1.1 新增表 `workbench_tool_actions`（待批动作 = 授权项，同行同表）

**设计取舍（为什么是一张表）**：一个"待执行的工具动作"的生命周期是 `pending → approved / rejected / expired`。**待批动作与授权项不是两种东西，而是同一行的两个状态**。合成一行后：
- 「批准的是哪个动作」无需跨表关联，**语义上不存在"另一行可比对"** → 从结构上消除"批准 A、执行 B"；
- 不产生第二事实源（规格 §3.4 用它作为否决"工具调用记录表"的理由，本设计同样适用）。

```sql
-- 027：工具执行的「待批动作 + 逐项授权」落点（段二规格 §3.2 ⑥⑦）
--
-- 背景：段一 026 只在 workbench_run_records 上记「运行级」的单一计划摘要，
--   无法表达「一个运行里有多个审批项、只批准其中一个」；而段二的工具执行必须在
--   「审批通过后从 ① 重跑」，因此必须把**被批准的具体动作与其规范化参数**冻结下来。
--
-- 设计取舍：
--   * 待批动作与授权项**同行**（status 由 pending 变为 approved/rejected，决议信息写同行
--     的 decision_* 列）：从结构上消除「批准 A 执行 B」，也不需要第二事实源。
--   * 只落参数的**规范化摘要**（args_digest），不落参数原文（与规格 §3.4「只落摘要」一致）。
--   * 租户隔离写进约束：复合外键 (tenant_id, run_id) 引用父表（父表侧唯一约束见 §1.2）。
--   * 决策留痕 append-only：重新审批 = 新行，不改写既有行。
--   * 可重复执行：与 024/025/026 同写法（IF NOT EXISTS / DROP ... IF EXISTS + ADD）。

CREATE TABLE IF NOT EXISTS workbench_tool_actions (
    tenant_id         TEXT NOT NULL,
    action_id         TEXT NOT NULL,      -- 服务端生成（宪法：唯一标识由服务端生成）
    run_id            TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    step_id           TEXT NOT NULL,
    tool_key          TEXT NOT NULL,      -- 必须仍在工具组装面内，执行前复查
    args_digest       TEXT NOT NULL,      -- 规范化参数摘要（算法见 §4）
    plan_digest       TEXT NOT NULL,      -- 该动作所属计划的摘要
    risk_level        TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
    requires_approval BOOLEAN NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired')),
    requested_by      TEXT NOT NULL,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by        TEXT,
    decided_at        TIMESTAMPTZ,
    decision_source   TEXT,               -- 决议来源（服务端判定并在白名单内校验，不来自请求体）
    reason_code       TEXT,               -- 受控枚举码；自由文本一律不落（§3.4）
    PRIMARY KEY (tenant_id, action_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id),
    -- 决议字段全有或全无（与 026 的 CHECK 同一思路）
    CONSTRAINT workbench_tool_actions_decision_check CHECK (
        (status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    )
);

-- 同一运行同一计划步只允许一个待批动作（防重复落库；已决议的历史行不受限）
CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_pending_unique
    ON workbench_tool_actions (tenant_id, run_id, step_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_workbench_tool_actions_run
    ON workbench_tool_actions (tenant_id, run_id, requested_at DESC);
```

**`reason_code` 取值**（受控枚举，与规格 §3.4 同源）：`path_denied` / `blacklisted` / `param_invalid` / `not_in_catalog` / `not_authorized` / `timeout` / `runtime_error` / `approval_denied` / `approval_expired`。

### 1.2 对既有表的必要增补（**属本迁移，须一并评审**）

```sql
-- 复合外键需要父表侧的唯一约束。013 只建了 PRIMARY KEY (run_id)，
-- 因此这里补 UNIQUE (run_id, tenant_id)：否则只能用单列外键，丢租户维度（跨租户可达）。
-- 与 024/025/026 同写法：先 DROP IF EXISTS 再 ADD，可重复执行。

ALTER TABLE workbench_run_records
    DROP CONSTRAINT IF EXISTS workbench_run_records_run_tenant_unique;

ALTER TABLE workbench_run_records
    ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id);
```

> 这是**对既有表的结构变更**，必须显式登记在本迁移里（不得"偷偷用单列外键"）。它不影响既有查询，只新增一个唯一约束。

### 1.3 新增表 `workbench_execution_idempotency`（B5 的落点）

**为什么需要它**：原方案以服务端生成的 `message_id` 作幂等键，而该值每次 `append` 都新建（`app/conversation/store.py`），重放拿不到相同值 → 改为客户端可重放的请求头 `Idempotency-Key` 后，**必须有一个地方记录"这个键对应哪一次执行的哪个结果"**，否则"重放返回既有结果"无法兑现。

**只存指针、不存正文**：首次响应可由 `message_id` 反查 append-only 消息表重建，**不复制内容**（避免与消息表形成第二份副本）。

```sql
CREATE TABLE IF NOT EXISTS workbench_execution_idempotency (
    tenant_id       TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    message_id      TEXT NOT NULL,   -- 首次生成的助手消息（响应由此重建）
    run_id          TEXT,            -- 首次派生的运行；未派生（如被拒）时为空
    outcome         TEXT NOT NULL CHECK (outcome IN ('executed','pending_approval','rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 复合主键即去重机制：并发重放由 INSERT ... ON CONFLICT DO NOTHING 收敛为一行
    PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, message_id)
        REFERENCES workbench_conversation_messages (tenant_id, message_id),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES workbench_run_records (tenant_id, run_id)
);
```

### 1.4 `027` 与 `026` 的主从关系（消除双事实源）

| 项 | 结论 |
| --- | --- |
| **授权权威** | **`027`（逐项）是工具执行的唯一授权权威**；执行器放行只看 027 |
| **`026` 三列的处置** | **保留、不删、不回填**；语义**降级为"运行级授权快照"**——由同一次事务写入，仅用于兼容段一既有读路径与「该运行是否曾被授权过」的粗判 |
| **判定顺序（⑦）** | 先按 027 逐项判放行；`authorization is None` 的 fail-closed 分支保留（用于"应当审批却查不到授权"） |
| **事务边界** | `decide_approval` 的「写 027 状态 + 写 026 快照 + 适配器决议」**必须在同一事务**内，任一失败全部回滚 |
| **明确不做** | 不删除 026 的列（历史数据与段一读路径依赖）、不做数据回填、不建第二个"授权"来源 |

### 1.5 回退与兼容

- **回退**（须先停真实执行）：`DROP TABLE workbench_tool_actions;` → `DROP TABLE workbench_execution_idempotency;` → `DROP CONSTRAINT workbench_run_records_run_tenant_unique;` → 删除 `workbench_schema_migrations` 中 027 的记账行。
- **旧数据兼容**：两张新表**不回填、无需回填**，既有行不受影响（唯一约束为纯增补）。
- **可重复执行**：全部 DDL 采用 `IF NOT EXISTS` / `DROP ... IF EXISTS` + `ADD`（与 024/025/026 一致）。

---

## 2. 待批动作的冻结与读取（B2 / B4 的落点）

- **⑥ 落库（需审批时）**：把 `{tool_key, 规范化参数, plan_digest, risk_level, requires_approval}` 冻结为一行 `workbench_tool_actions(status='pending')`；**同事务**完成。落库失败 → 返回 `503`，**不进入等待**。
- **审计归属**：⑥ 落库本身**不写 `tool.*` 审计**（避免新增动作码）；只有 ⑨ 成功写 `tool.executed`、被拒写 `tool.blocked`。
- **执行对象唯一**：执行器**只执行 027 中 `status='approved'` 且 `plan_digest` 与运行当前计划一致的行**，参数直接取该行的冻结值 → **不存在"批准 A 执行 B"的通道**（B ≠ A 就没有对应的 approved 行）。
- **⑦ 逐项校验**：逐行核 `status='approved'` + `plan_digest` 一致 + `tool_key` 仍在组装面内 + ③④ 在重跑中通过。任一行不满足 → `409`，不执行该行。
- **函数签名变更（回填规格时必须写清）**：

  | 现签名 | 新签名 |
  | --- | --- |
  | `RuntimeService.ensure_execution_authorized(actor, run_id, plan)` | `ensure_execution_authorized(actor, run_id, plan, actions: Sequence[ToolAction])` —— 新增待判动作序列；**缺省保持旧行为**（无 027 装配时退化为运行级摘要比对，保证段一测试不破） |

  调用点（已定位）：`app/runtime/service.py:105`（resume 传 `state.plan`）与段二新增的工具执行入口。**新增调用点必须显式传入 actions**，不得留空。

---

## 3. `Idempotency-Key` 的落点与取回（B5）

- **入口**：`POST /api/v1/conversations/{conversation_id}/messages` 增加**可选**请求头 `Idempotency-Key`（`Header(default=None, alias="Idempotency-Key")`）。**缺省 = 幂等关闭**，保持既有语义（不改变现网行为）。
- **处理顺序（先查后做）**：
  1. `agent_key` 校验（存在且启用）→ 否则 `422`（**在创建任何东西之前**）
  2. 若带键：查 `workbench_execution_idempotency`；**命中 → 直接返回既有结果**（`message_id` 反查消息重建响应；`pending_approval` 返回 `202` + `run_id`）
  3. 未命中 → 正常执行；结束前**同事务**插入幂等行（`ON CONFLICT (…) DO NOTHING`）；若并发冲突，则以库中已存在的行为准并返回首次结果 → **并发重放只执行一次**
- **作用域**：`(tenant_id, actor_id, conversation_id, idempotency_key)` —— 跨租户、跨会话、跨发起人互不影响。
- **保留**：本段**不做清理**（`created_at` 留存，交给后续保留策略）；**不设 TTL**，避免"过期后可重放"的新语义。
- **响应一致性**：`201`（`executed`）/ `202`（`pending_approval`）/ 拒绝码（`rejected`，同时落幂等行以便重放返回同一拒绝）三态都写幂等行，保证重放**与首次完全一致**。

---

## 4. 参数规范化算法（`args_digest`）

**原则：只做"表示层归一"，不做任何"看起来一样就折叠"的模糊处理。**

| # | 规则 |
| --- | --- |
| 1 | 输入为 schema 校验通过后的 JSON 值（`null`/bool/数字/字符串/数组/对象） |
| 2 | **对象**：键按 Unicode 码点升序排序；**保留 `null` 值**；**"缺键"与"键=null"视为不同**（不省略键） |
| 3 | **数组**：**保持原顺序**（顺序敏感，不排序） |
| 4 | **字符串**：先做 NFC 归一；**仅对 schema 声明为"路径"的参数**再做：`/` 分隔归一、折叠 `.`/`..`、去尾部 `/`（根除外）、**不做大小写折叠**（执行环境为 Linux，大小写敏感） |
| 5 | **数字**：整数按十进制；小数去尾随 0；**禁止浮点近似参与**（金额类参数必须由 schema 声明为整数分或字符串） |
| 6 | **布尔**：输出 `true`/`false`（小写） |
| 7 | **序列化**：`json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))`（排序已在规则 2 完成） |
| 8 | **摘要**：`args_digest = "sha256:" + sha256(utf8(序列化结果)).hexdigest()` |

**等价性口径**：规范化后字节相同 ⇒ 摘要相同；字节不同 ⇒ 摘要不同（除哈希碰撞外）。**不允许存在"语义相同但摘要不同"的可利用差异**。

**单测判据（对应 §5 用例 13）**：

| 输入对 | 期望 |
| --- | --- |
| `{"a":1,"b":2}` vs `{"b":2,"a":1}` | 摘要**相同** |
| `{"a":1}` vs `{"a":1.0}` | 摘要**不同**（类型不同） |
| `{"a":null}` vs `{}` | 摘要**不同**（缺键 ≠ null） |
| 路径参数 `a//b` vs `a/b` | 摘要**相同** |
| 路径参数 `A` vs `a` | 摘要**不同**（容器内大小写敏感） |
| 同一输入重复调用 | 摘要**稳定** |

---

## 5. 装配与调用链（B4）

**现状（已核对）**：`decide_approval`（`app/runtime/service.py:116-134`）只写 026 授权位并转调适配器；决议端点（`app/main.py:1834-1877`）只持有 `runtime_service`，**没有任何执行依赖**；仓库内目前**不存在** dsh 适配器/工具目录/容器执行器。

**设计**：

1. **新增 `ToolExecutionService`**，构造依赖：`ToolCatalog`、`ContainerExecutor`、`WorkspaceManager`、`ToolActionStore`(027)、`RunRecords`、`Audit`。
2. **装配点**：应用启动装配处（与 `runtime_service` 同处）创建；`WORKBENCH_AGENT_RUNTIME_BACKEND=mock` 时**必须为 `None`**。
3. **注入与启动期断言（fail-closed）**：`RuntimeService` 增加**可选**协作者 `tool_execution`；`backend=dsh` 时断言 `tool_execution`、`run_records`、`tool_actions` **三者非 None**，否则**拒绝启用真实执行并告警**（不拒绝整个服务进程启动）。
4. **调用链**：

```
POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval
  → runtime_service.decide_approval(...)
      → 【事务 A】写 027 决议状态 + 写 026 快照 + adapter.decide_approval
      → 若 approved：tool_execution.resume(run_id, approval_id)
            → 取 027 中 approved 行（冻结动作与参数）
            → 从 ① 重跑 ①–⑨（含 ②③④；禁止跳过）
```

5. **重跑失败语义（定死）**：

| 失败步 | 状态码 | 026 授权位 | 027 行 | 审计 |
| --- | --- | --- | --- | --- |
| ① 工具已不在组装面 | `409` | 保留 | 保持 `approved`，`reason_code=not_in_catalog` | `tool.blocked` |
| ② 参数校验失败 | `422` | 保留 | 同左，`param_invalid` | `tool.blocked` |
| ③ 路径越界 | `403` | 保留 | 同左，`path_denied` | `tool.blocked` |
| ④ 黑名单命中 | `403` | 保留 | **置 `rejected`**，`blacklisted`（不允许审批放行） | `tool.blocked` |
| ⑧ 超时 | `504` | 保留 | 保持 `approved`（可重试），`timeout` | `tool.blocked` |
| ⑧ 其它失败 | `502` | 保留 | 保持 `approved`（可重试），`runtime_error` | `tool.blocked` |
| ⑨ 成功 | `200` | 保留 | 保持 `approved` | `tool.executed` |

   - **授权位不回滚的理由**：失败原因（超时/运行时错误/参数校验）与"批准意图"无关，回滚会把"批准一次、执行失败"变成"还要再批一次"；但**④ 黑名单例外**——必须在 027 上留不可执行痕迹。
   - **审批记录最终状态**：`approved` 不变（决议事实已发生）；执行结果只由审计与 `reason_code` 表达，**不新增"执行成功/失败"审批状态**（避免混淆语义）。

6. **决议端点响应体（定死，须同轮回改契约）**：在既有 `{run_id, approval_id, status, run_status}` 之上**新增可选字段** `execution: {outcome, code?, message_id?}`（`outcome ∈ executed / pending_approval / rejected / failed`）。**加字段不改既有字段**；**回改前须确认 `admin-web` / `companion-pwa` 对未知字段不报错**（前端解析为 strict 时需同步改）。

---

## 6. 真源三件套：功能清单（宪法 2.1 硬门槛）

> **⚠️ 本节口径已作废（2026-09-13 裁决 R8）**：原「以立项 §14.1 充当、不另建文档」的方案**已被推翻**——功能清单已另建独立文档 [`docs/feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)（宪法 2.1 六要素），规格头部与门禁清单已同步显式引用。**以下原文保留仅作留痕，不得据以实施**（本文件整体已转归档，见头部）。

**已裁决（2026-09-12）**：**显式以立项文档 §14.1（P0–P6 交付表）充当「功能清单」**，不另建文档。待写入的确切措辞：

- 规格头部「上位真源」行补：**「功能清单 = 立项文档 §14.1 交付表（P0–P6），本项目不另建独立功能清单文档」**；
- 门禁清单相应位置同步该引用。

---

## 7. 回填顺序与验收判据

| # | 步骤 | 判据 |
| --- | --- | --- |
| 1 | **本草案评审通过** | 三个独立视角复核 §1–§5 是否"可评审、可实现"，无阻断项 |
| 2 | 草案 §1–§5 **回填规格**（§3.2/§3.4/§3.7/§4）与契约 | 旧口径残留清零（"零新迁移"、`message_id` 派生、§3.4"本段不新建表"） |
| 3 | 迁移 027 落地 | **可重复执行**；升级路径（既有库 → 027）通过；对既有段一测试零破坏 |
| 4 | 段二-2 离线验收 | 闸门用例全绿 + 反假全红；**参数规范化 6 条单测**；`Idempotency-Key` 重放只产生一条消息；"批准 A 无法执行 B"构造性用例 |
| 5 | 段二-3 装配与真实执行 | 启动期断言生效；027×026 **事务一致性**（注入失败必全回滚） |

---

## 8. 本草案**未覆盖**（如实登记）

1. **容器侧配置落点**（dsh 剖面文件、镜像 digest、`WORKBENCH_EXEC_TRUSTED_ROOTS` 的具体装配位置）→ 属段二-3。
2. **`WORKBENCH_EXEC_TIMEOUT_SECONDS` 的具体数值** → 需定数值（当前 U11）。
3. **幂等记录的保留/清理策略** → 本段明确不做。
4. **前端 `202` 分支与 `Idempotency-Key` 的接入**（属段二-4；含"前端是否 strict 解析响应"的确认）。
5. **`workbench_runtime_states.approvals`（021，JSONB）与新表的关系** → 本草案选择"027 为权威、021 那列维持既有用途"；若实现时发现二者语义重叠，须回到本草案先改设计，不得两处并存。
