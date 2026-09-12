# P2a 段一：治理收口段 设计

> **性质**：**阶段规格（唯一真源）**。本文定义「P2a 段一」做什么、怎么做、怎么验收。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §4 决策 D18–D23、§14.1 分期、§15 已知风险。
> **依据**：[EvoFlow 完整源码研读报告与修改方案](file:///d:/徐徐AI学习/公司工作台/docs/evoflow-source-study-and-adaptation-plan.md) §2.1 / §2.2。
> **日期**：2026-09-12
> **状态**：**待评审**（未评审通过前不得写实现代码）。
> **前置**：P1 已交付（后端子 1313 用例 / 管理台 143 / 伴侣端 37 / 桌面端 19 全绿）。

---

## 1. 范围

### 1.1 做什么（四项）

| # | 事项 | 一句话 |
| --- | --- | --- |
| A | **`RiskLevel` 扩四档** | 领域风险刻度加 `critical`，全系统**单一刻度**；DB、后端判定、前端同步 |
| B | **`risk_threshold` 首次接入真实判定** | 任务是否进「待审批」不再写死 `== high`，改由治理判定函数决定 |
| C | **授权位机制** | 运行行上记录「谁在何时批准了哪个计划摘要」；执行前校验摘要一致，否则拒绝 |
| D | **前端常驻外壳（D19）** | `AppShell` 只挂一次，视图用 `hidden` 切换，切页不再丢草稿与轮询状态 |

### 1.2 不做什么（明确排除）

1. **不接 dsh**：不装 `@deepseek-ai/dsh`、不引入任何 dsh 类型（§15 #1 的隔离要求不变）。
2. **不新增任何真实工具**，**文件与命令一律不开启**（D23；§15 #9 的硬门禁）。
3. **不做实时流与过程事件**（D15/D16 属 P2b）。
4. **不做右侧舞台、不做侧栏信息架构重组**（D14 属 P2c）；本段的 D 项只做「外壳常驻」这一件物理前提。
5. **不改 `daily_budget_cents` 的「0 = 用租户默认」语义**（调研报告 §2.1 第 7 条）。
6. **不引入**调研报告 §3「明确不采纳清单」中的任何一条。
7. **不扩技能、不做记忆层**（P3/P4）。

### 1.3 影响什么（改动面）

| 层 | 影响 |
| --- | --- |
| 数据库 | 两个新迁移：任务表 `risk_level` 的 `CHECK` 放宽；运行表加 3 个授权位列 |
| 后端 | `domain.py` 风险刻度与判定口径；任务创建路径；`planner/classification.py`；`runtime/service.py` 执行前闸门；`workforce` 增一个只读治理字段方法 |
| 前端 | 首页风险下拉多一档；`App.tsx` 由「整页替换」改为「常驻外壳 + `hidden`」 |
| 契约文档 | `docs/api-contract.md`：任务创建的风险档取值、`critical` 的权限口径、运行授权字段 |
| 既有行为 | **任务创建在「带 `employee_key` 且员工存在且启用」时行为会变**（见 §2.2）；其余路径刻意保持与今天一致 |

---

## 2. 设计

### 2.1 事项 A：`RiskLevel` 扩四档

`RiskLevel` 取值收敛为 `low | medium | high | critical`。

**逐处改动（这是地基变更的核心，一处都不能漏）**

| # | 位置 | 现状 | 改为 | 不改的后果 |
| --- | --- | --- | --- | --- |
| 1 | `migrations/025_task_risk_level_critical.sql`（新） | `CHECK (risk_level IN ('low','medium','high'))` | 加 `'critical'` | 接口放行了但 DB 写入被拒（500），且绕过接口的直连写入无第二道防线 |
| 2 | [domain.py](file:///d:/徐徐AI学习/公司工作台/app/domain.py#L10-L13) `RiskLevel` | 三档 | 加 `CRITICAL` | — |
| 3 | [domain.py](file:///d:/徐徐AI学习/公司工作台/app/domain.py#L145) `ensure_can_create` | `risk_level == RiskLevel.HIGH and role == "employee" and budget > 1000` | 改为「**不低于** `high`」 | 🔴 **fail-open**：`critical` 反而不受这条预算闸门约束，比 `high` 更松 |
| 4 | [main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py#L1600-L1604) 任务创建 | `PENDING_APPROVAL if risk_level == HIGH` | 改由 §2.2 的统一判定函数决定 | 🔴 **fail-open**：`critical` 任务直接进 `QUEUED`，绕过审批 |
| 5 | [classification.py](file:///d:/徐徐AI学习/公司工作台/app/planner/classification.py#L8-L12) | 三档映射，未知档 `ValueError` | 加 `CRITICAL → RESTRICTED` | 功能不可用：`critical` 任务被拒规划 |
| 6 | [types.ts](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/home/types.ts#L5) `HomeRiskLevel` | 三档 | 加 `critical` | 前后端取值不一致 |
| 7 | [HomePage.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/home/HomePage.tsx#L10) `RISK_OPTIONS` | 三档 | 加 `critical` | 同上 |

**风险序的「单一可信来源」**：项目已有一份序 [models.py](file:///d:/徐徐AI学习/公司工作台/app/workforce/models.py#L31) `RISK_ORDER`。`domain.py` **不得反向依赖** `workforce`（层次颠倒）。做法：把风险序**下沉到 `app/domain.py`**，`workforce/models.py` 改为从 `domain` 导入。导入方向恒为 `workforce → domain`。

> 这是本段唯一一处重构既有代码的地方，理由是「避免两处各写一份风险序」——两份序就是第二个真相，迟早漂移。改动本身不改变任何行为。

**措辞口径**：`critical` 一律按「不低于 `high`」处理。代码里**禁止**再出现 `== RiskLevel.HIGH` 这类等值判断用于安全闸门。

### 2.2 事项 B：`risk_threshold` 首次接入真实判定

**唯一判定入口**：`app/workforce/models.py::needs_approval(autonomy_level, risk_level, risk_threshold)`。**禁止**在业务代码里另写一份判定。

**判定口径（X1 的最终落法，2026-09-12 定）**：`autonomy_level` 决定**判定模式**，`risk_threshold` 在「按阈值」模式下生效。这修正了 X1 的字面写法（「阈值是唯一输入」会让 `full_auto + 阈值=high` 变成「high 也要批」，`full_auto` 的「免批」语义就漂移了），也因此与 §7.2 早已写下的口径一致（「`risk_threshold` … `approval_for_risky` 时生效」）：

| 自治等级 | 结论 |
| --- | --- |
| `approval_for_all` | **一律审批**（阈值不参与） |
| `approval_for_risky` | `risk >= risk_threshold`（阈值来自该员工配置，**默认 `medium`**） |
| `full_auto` | **除 `critical` 外免批**（`critical` 由 D18 兜底强制审批，阈值不参与） |

**fail-closed 三则**（与 D18 一致，均有测试守护）：未知自治等级 → 审批；未知风险档 → 审批；未知阈值 → 按最低档 `low` 处理（= 一律审批，宁严不松）。

**唯一消费点（段一）**：`POST /api/v1/tasks` 创建任务时决定 `status`。

| 情形 | 取用依据 | 结果 |
| --- | --- | --- |
| 任务带 `employee_key`，且该员工在本租户**存在且启用** | 该员工的治理配置（自治等级 + 风险阈值） | `needs_approval(...)` 为真 → `PENDING_APPROVAL`，否则 `QUEUED` |
| 任务带 `employee_key`，但员工**不存在或已停用** | 回落既有口径（`risk_level` 不低于 `high` 即待审批） | **与今天完全一致**，不放宽 |
| 任务不带 `employee_key` | 同上回落 | **与今天完全一致** |

**为什么「员工不存在/已停用」要回落到既有口径而不是 fail-closed 全要批**：因为 §15 #11 已登记「创建任务时不校验 `employee_key` 是否存在」，今天 typo 的 `employee_key` 是完全合法的输入。若此处改成一律待审批，就变成**顺带收紧既有已稳定行为**。本段只做「把字段接上」，不夹带权限口径变更；收紧 `employee_key` 校验的时机仍是 §15 #11 登记的 P2。

**读取通道（安全要求）**：`WorkforceDirectoryStore.read_agent_config` 要求 `_ensure_admin`（[store.py](file:///d:/徐徐AI学习/公司工作台/app/workforce/store.py#L231-L232)），**不能**用于任务创建路径。本段新增一个**只读治理字段**的仓储方法，例如：

```
read_agent_governance(context, agent_key) -> tuple[str, str] | None
    # 返回 (autonomy_level, risk_threshold)；本租户不存在则 None
```

要求：
- **只返回这两个治理字段**，不返回 `system_prompt`（提示词属敏感信息，最小必要）；
- 不对调用者做角色限制（任务创建者在业务上可以是任意可创建任务的角色），但**强制租户隔离**（`context.tenant_id`）；
- 内存与 PG 两个仓储都实现，并有仓储契约测试覆盖。

**语义变化（必须写进文档与汇报）**：这是 `autonomy_level` **第一次真正参与判定**。此前它只被存储与校验（[conversation/service.py](file:///d:/徐徐AI学习/公司工作台/app/conversation/service.py#L34-L37) 明确写了「刻意不参与权限判定」）。

### 2.3 事项 C：授权位机制

**要解决的问题**：审批通过之后、真正执行之前，计划或参数若被改动，原审批就失效了——不能靠「有人记得发撤销事件」。

**数据**：`migrations/026_run_execution_authorization.sql`（新），给 `workbench_run_records` 加三列：

| 列 | 类型 | 语义 |
| --- | --- | --- |
| `execution_authorized_at` | `TIMESTAMPTZ`（可空） | 授权时刻；`NULL` = 从未授权 |
| `execution_authorized_by` | `TEXT`（可空） | **由服务端从认证态推导**的批准人标识 |
| `authorized_plan_digest` | `TEXT`（可空） | 被批准那一刻的**计划摘要**（SHA-256 十六进制） |

**写入**：审批决议为「通过」时写入三列（同一事务内）。摘要口径与既有 `request_fingerprint` 一致（`json.dumps(..., sort_keys=True, separators=(",", ":"))` 后 SHA-256）。

**校验（闸门）**：新增 `ensure_execution_authorized(run, current_plan)`，在**推进执行的唯一入口**调用：

| 情形 | 结果 |
| --- | --- |
| 三列任一为 `NULL` | **拒绝执行**（`未授权`） |
| `authorized_plan_digest` ≠ 当前计划摘要 | **拒绝执行**（`授权已失效：计划已变更`） |
| 摘要一致 | 放行 |

**授权 actor 白名单**：`{user, system, api, ui, automation}`。

- 审批接口**不接受请求体里的 `authorized_by`**，一律由服务端从认证态推导；
- **显式拒绝** `agent` 作为授权来源（数字员工不能自己批准自己）；
- 非法来源 → 拒绝并写审计。

**段一的诚实边界（必须登记）**：段一没有真实工具，这道闸门今天**拦不到真实副作用**，它的价值是「把机制与测试先建好，段二接 dsh 时它就是硬门禁」。**不得**对外表述为「已阻止文件/命令滥用」。

### 2.4 事项 D：前端常驻外壳（D19）

**现状**：[App.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/app/App.tsx#L79-L90) 一个 `if` 链 `return <XxxPage/>`，每次导航整页卸载；12 个页面各自在内部包一层 `AppShell`（如 [HomePage.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/home/HomePage.tsx#L97)），所以整页卸载 = 状态全丢（对话草稿、轮询、滚动位置）。

**目标**：
1. `App` 只挂一次 `AppShell`，导航时只切换 `activeView`（并 `pushState` 保持 URL 语义与刷新直达不变）；
2. 视图在 `AppShell` 的内容区内切换，用 `hidden` 隐藏而非卸载；
3. 12 个页面**移除各自内部的 `AppShell` 包裹**（改为纯内容组件），`AppShell` 由 `App` 统一提供。

**关键约束（否则会退化）**：

| 约束 | 理由 |
| --- | --- |
| **首次访问才挂载**（`visited` 集合：访问过就常驻，没访问过不挂载） | 若 12 个视图一上来全部挂载，启动瞬间会打出 12 组并发请求 |
| `hidden` 用 `display: none` 语义（`.view-slot[hidden]`），且**隐藏视图不得继续轮询** | 否则后台标签页行为不可控。**落地时实测：前端目前没有任何 `setInterval`/`setTimeout` 轮询**（侧栏角标是事件驱动），故这条当前**无实现对象**；一旦将来引入轮询，必须以「是否 active」为开关 |
| 现有 URL 契约不变（`?view=` / `?task=` / `?run=` / `?conversation=`） | 刷新直达与深链是既有行为 |
| 每个页面原有的空/错/加载/无权限四态**不得因为常驻而改变** | 外壳重构不是功能重构 |

**测试要求**：① 导航后返回，前一页的输入草稿仍在（这是 D19 的目的，必须有测试证明）；② 未访问过的视图不发起请求；③ 非 active 视图不轮询；④ 四个 URL 直达用例仍通过。

---

## 3. 迁移

| 版本 | 内容 |
| --- | --- |
| `025_task_risk_level_critical.sql` | 替换 `workbench_tasks.risk_level` 的 `CHECK` 为四档（`DROP CONSTRAINT IF EXISTS` + `ADD`，与 `024` 同写法） |
| `026_run_execution_authorization.sql` | `workbench_run_records` 加 3 列（`ADD COLUMN IF NOT EXISTS`，均**可空、不带默认值**——「未授权」必须是显式的 `NULL`，不能用默认值伪装成已授权） |

两个版本都要登记进 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS`（`tests/test_staging_assets.py` 守护）。

---

## 4. 测试计划（先写失败测试，后写实现）

| # | 用例 | 类型 | 必须红的方式 |
| --- | --- | --- | --- |
| 1 | `needs_approval('full_auto','critical') is True` 等 3×4 矩阵 | 正常 | 已交付（21 用例） |
| 2 | 创建任务：`full_auto` 员工 + `critical` 风险 → `PENDING_APPROVAL` | 正常 | 把判定写回 `== HIGH` → 必须红（**这是 D18 兜底第一次真正生效**） |
| 3 | 创建任务：`full_auto` 员工 + `high` 风险 → `QUEUED`（免批确实生效） | 正常 | — |
| 4 | 创建任务：`employee_key` 不存在 → 与既有口径一致 | 边界 | — |
| 5 | `critical` 任务被 `ensure_can_create` 按「不低于 high」处理 | 边界 | 改回 `== HIGH` → 必须红 |
| 6 | `planner` 对 `critical` 任务不抛 `ValueError` | 边界 | 删映射 → 必须红 |
| 7 | 授权位：未授权推进执行 → 拒绝 | 异常 | 删闸门 → 必须红 |
| 8 | 授权位：审批后计划变更 → 拒绝（摘要不一致） | 异常 | 只比「是否授权过」不比摘要 → 必须红 |
| 9 | 授权位：请求体伪造 `authorized_by` → 被忽略；来源 `agent` → 拒绝 | 异常 | — |
| 10 | 跨租户：用 A 租户身份读 B 租户员工治理字段 → 查不到 | 异常 | — |
| 11 | 前端：切页返回草稿仍在 | 正常 | 改回整页卸载 → 必须红 |
| 12 | 前端：未访问视图不请求、非 active 不轮询 | 边界 | — |

**反假测试纪律**：上表标「必须红」的每一条，实施时都要**真的把代码改坏跑一遍确认变红**，再还原转绿，并把结果写进汇报。

---

## 5. 验收标准（三类用例 + 证据）

| 类别 | 要求 |
| --- | --- |
| **正常流程** | 必须**查库验证**，不只看接口返回：任务行的 `status` 与 `risk_level`、运行行的三列授权字段 |
| **临界值** | 四档风险 × 三档自治的组合；`budget` 边界（0 / 1000 / 1001）；`employee_key` 空/不存在/已停用 |
| **异常与非法输入** | 非法 `risk_level`（含 `CRITICAL` 大小写不符）→ 422/`CheckViolation`；伪造 `authorized_by`；`agent` 来源；跨租户读取；摘要不一致 |

**报告要求**：五类现象实例（正常 / 参数错误 / 未登录 / 无权限 / 访问他人数据）+ 数据前后变化 + 审计记录；**没验证的必须写「未验证」**。

**端到端**：迁移 `025`/`026` 需在**真实 PostgreSQL**（一次性容器，跑完即删）上验证：从零应用、幂等、约束真的拦人（四档允许、非法值 `CheckViolation`）、存量行三列为 `NULL`。

**全量回归**：`pytest` + `compileall` + 管理台 vitest/build + 伴侣端 vitest/build + 桌面端 `node --test`，并跟 CI 四个 job。

---

## 6. 待决策（**已于 2026-09-12 全部答复**）

| # | 问题 | 答复 | 落法 |
| --- | --- | --- | --- |
| **X1** | `autonomy_level` 与 `risk_threshold` 谁是判定的输入？ | **b**（用户，2026-09-12） | **精化后落地**：`autonomy_level` 决定判定模式、`risk_threshold` 在「按阈值」模式生效 —— 详见 §2.2 判定口径表。**为什么不是字面 b**：字面 b（阈值是唯一输入）会让 `full_auto + 阈值=high` 变成「high 也要批」，`full_auto` 的「免批」语义漂移；精化后的形式同时与立项文档 §7.2 早已写下的「`risk_threshold` … `approval_for_risky` 时生效」一致，两个字段都有真实语义、不删列不改列 |
| **X2** | 授权位机制留段一还是移到段二？ | **a**（用户，2026-09-12） | 留段一：先把机制与测试建好，段二接 dsh 时直接成为硬门禁。**它在段一拦不到真实副作用**，已在 §2.3 登记 |
| **X3** | `critical` 任务的创建权限口径 | **a**（用户，2026-09-12） | 普通员工与部门负责人**不得**创建 `critical`（`PolicyError` → `403`），只有 `ceo`/`super_admin` 可创建，创建后仍一律待审批。**已核实的连带事实**：任务审批端点（`POST /api/v1/tasks/{id}/approve`）**不禁止自审**（`store.approve` 无发起人校验），故 `ceo`/`super_admin` 发起的 `critical` 任务可由本人审过 —— 这是**既有行为**，本段不改（改自审规则属权限模型变更）；已在 §7 登记 |

---

## 7. 风险与未覆盖（如实登记）

1. **本段不降低 dsh 的风险**：段一完全不碰 dsh，§15 #1 / #2 / #9 的结论与门禁不变。
2. **授权位在段一「拦不到真实副作用」**（§2.3 诚实边界）。
3. **`employee_key` 仍不校验存在性**（§15 #11）；本段刻意不动，只保证「不存在时与今天行为一致」。
4. **D18 的兜底只在「任务创建」这一个消费点生效**：工具层、记忆层的判定要段二/P3 才接。
5. **前端常驻外壳会改变内存占用特征**：访问过的视图常驻内存。段一不引入 12 个视图全量挂载，但长期驻留多个视图的内存影响**未做测量**。
6. **staging / 生产未验收**（无独立主机、TLS、独立密钥、回滚演练）。
7. **本文件不构成任何实现完成的声明**：段一**尚未开始编码**。
8. **任务审批允许自审**（既有行为，本次核实）：`POST /api/v1/tasks/{id}/approve` 只校验角色（`ensure_can_approve`）与租户，**不校验发起人**。因此 X3=a 下由 `ceo`/`super_admin` 发起的 `critical` 任务，**「一律待审批」可由本人审过**——它挡的是「无审批直接入队」，不是「换一个人来审」。**改自审规则属权限模型变更（地基），不在本段范围**；需专项评审。运行内审批（`runtime_service.decide_approval`）已有自审禁令，两者口径不一致这一点本段不解决、只登记。
9. **X1 的精化是对已批准选项的收窄**：字面 X1=b 会让 `full_auto` 的「免批」语义随阈值漂移。本段按 §2.2 判定口径表落地，已在 §6 显式说明理由；若用户不同意此精化，须先改判据再动代码。

---

## 8. 实施与验证记录（2026-09-12）

> 本节是**证据**，不改变上面的口径。所有数字均为本机实测。

### 8.1 落地时对规格的三处如实调整

| # | 规格原写法 | 实际落地 | 原因 |
| --- | --- | --- | --- |
| 1 | §2.4「非 active 视图不轮询」 | **该约束当前无实现对象** | 实测全仓**无 `setInterval`/`setTimeout` 轮询**；角标与列表都是事件/请求驱动。已把约束保留为「将来引入轮询时的硬要求」 |
| 2 | §2.2 读取通道要求「精确匹配」 | 改为**归一后匹配**（转小写，复用 `_safe_key`） | 目录自身口径是「大小写不同**不是**两个标识」（`KEY_PATTERN` 收紧到小写）；归一匹配与此一致，且非法标识仍安全返回 `None` 回落既有口径 |
| 3 | §2.1 第 3 项把 `ensure_can_create` 的等值判断记为 🔴 fail-open | 该处已改为「不低于 high」，但**在 X3 生效后对 `critical` 已不可达**（员工发起 critical 会先被 X3 子句拒掉） | 因此这处改动是**防御性**的（防将来新增更高档、或 X3 口径被调整），不是当前唯一的拦截点；测试仍保留 |

### 8.2 反假测试实测（每一处都真的改坏过）

| # | 注入的退化 | 结果 |
| --- | --- | --- |
| 1 | `needs_approval` 删掉「`critical` 不豁免」兜底 | **红**：审批矩阵 4 例 + `test_critical_is_never_exempt_for_full_auto` + `test_no_autonomy_level_exempts_critical` |
| 2 | 任务创建退回 `risk_level == HIGH`（旧逻辑） | **红**：`test_task_status_follows_employee_governance` 多例（`full_auto + critical` 变 `queued`） |
| 3 | `ensure_can_create` 退回「等于 high」且删掉 critical 创建限制 | **红**：`test_critical_creation_is_limited_to_leadership` ×2 + `test_ensure_can_create_rejects` ×2（**员工可以创建 critical**，即 fail-open 复现） |
| 4 | `classification_for_risk` 删掉 `CRITICAL` 映射 | **红**：`test_every_declared_risk_level_has_a_classification`（`ValueError: 未知的任务风险等级`） |
| 5 | 授权闸门去掉计划摘要比对（只比「是否授权过」） | **红**：`test_resume_is_refused_when_plan_changed_after_approval` |

还原后全部转绿；全仓已确认无残留（`grep ANTIFAKE` 零命中）。

### 8.3 迁移 `025` / `026` 真实 PostgreSQL 回归（本机一次性容器，跑完即删）

> **环境**：`pgvector/pgvector:pg16`（PostgreSQL 16.15），端口 55436，容器 `workbench-pg-025`。**不是 staging**。

| # | 检查 | 结果 |
| --- | --- | --- |
| 1 | 从零应用迁移 | **26 条**，末条 `026_run_execution_authorization` |
| 2 | 幂等 | 重复应用 **0** 条 |
| 3 | `tasks.risk_level` 约束 | 唯一一条，定义含 `low/medium/high/critical` |
| 4 | `run_records` 授权约束 | `workbench_run_records_execution_authorization_check` 存在 |
| 5 | 授权三列 | 齐备、`is_nullable=YES`、**无默认值** |
| 6 | **四档风险全部允许** | `low` / `medium` / `high` / `critical` 写入成功 |
| 7 | 非法风险档被拦 | `extreme` / `CRITICAL` / 空串 → `CheckViolation` |
| 8 | **授权位「只填一半」被拦** | 4 种半填组合全部 `CheckViolation` |
| 9 | 授权位三列全填 | 允许 |
| 10 | **状态回写不抹掉授权位（真实 PG）** | `PostgresRunRecordStore` 写入授权 → 再 upsert 状态为 `completed` → 授权仍在且摘要不变 |
| 11 | 撤销授权位 | 三列回 `NULL` |
| 12 | 跨租户写授权位 | `RunRecordNotFound` |
| 13 | 未授权的运行三列 | `NULL` |

**仍未覆盖**：staging / 生产未验收（无独立主机、TLS、独立密钥、回滚演练）。

### 8.4 全量回归（本机，与 CI 逐字同口径）

| 端 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `python -m pytest -o addopts=""` | **1417 passed**（P1 基线 1313 → 段一 +104） |
| 后端 | `python -m compileall -q app tests extract_pdf.py scripts` | 通过 |
| 管理台 | `npx vitest run` / `npm run build` | **147 passed** / 构建通过 |
| 伴侣端 | `npx vitest run` / `npm run build` | 37 passed / 构建通过 |
| 桌面端 | `node --test` | 19 passed |

### 8.5 本段仍未验证（如实登记）

1. **未跑 CI**：`push` 触发的四个 job 需提交后才能实跑；本机已按 CI 的**逐字命令**跑过同一组检查。
2. **staging / 生产未验收**（同 §8.3 末条）。
3. **浏览器人工闭环未做**：常驻外壳只做了自动化测试（草稿保留、只切显隐、未访问不挂载、四个 URL 直达），**没有真人点过 12 个页面的视觉与滚动表现**；`.view-slot` 的布局等价性是按 CSS 推导的，存在未观测到的视觉回归风险。
4. **授权闸门拦不到真实副作用**（段一没有真实工具，§2.3 已登记）。
5. **只登录一个消费点**：`needs_approval` 目前只在「任务创建」被调用；对话入口、工具层、记忆层的判定分别在 P2b / 段二 / P3。

