# 租户清场扩围（专项方案 · B1 已实施）

> 状态：**方案（B1 已实施，2026-09-19；B2→B5 待做）**。依据 = 用户 2026-09-19 裁决「清场扩围：先出专项方案再定」
> 与「三个阻塞点按方案建议全选」。B1 实施记录见 §9。
> 关联文档：真源 `docs/superpowers/specs/2026-09-06-commercial-g0-design.md`（§6.1 导出 / §6.2 删除 / §6.3 保留）、
> 差距台账 `docs/delivery-remaining-checklist.md`（组 10.7「清场 / 导出覆盖面普查」条）、
> 契约 `docs/api-contract.md`（删除清场口径段）。

## 1. 现状（实测，非估算）

| 口径 | 数字 | 依据 |
| --- | --- | --- |
| 全平台**租户级表**（含 `tenant_id`） | **55 张** | 测试库 `information_schema.columns` 实测（2026-09-19） |
| **租户删除**实际清场 | **6 张**（三面：记忆 3 + 技能 2 + 知识文档 1） | `app/commercial/lifecycle.py::execute_delete` 逐面 `delete_all_for_tenant` |
| 导出类别接线 | **11 / 15 类** | `app/commercial/export_readers.py` |

⇒ 真源 §6.2「**业务数据**、对象存储文件、向量索引和缓存按策略清理」中，**业务数据只覆盖了 6/55 张表**；
其余 49 张（会话与消息、任务与运行、CRM、账号、收件箱、用量、事件外发…）在租户删除后**仍然保留**。
这是当前交付的**已知且已登记**的最大合规缺口（对象存储 / 向量 / 缓存属另一专项，不在本方案内）。

## 2. 目标与判据

1. 租户删除（`execute_delete`）后，**该租户在这 55 张表里的业务数据全部物理清空**（除审计类，见 §4）。
2. 审计 `cleared_categories` 从「三面」扩展为**逐层 / 逐域面名**，且**只列真正清到的面**（沿用 B-3 口径）。
3. 每张表都要有**逐表计数取证**（删除前有值、删除后为 0、他租户不受影响），不允许「面名齐全但表未清」
   —— 该缺陷类别已在 2026-09-19 抓到过两次（见台账「第三个生产向真缺陷」条）。
4. 契约 / 手册 / 审计动作码同步更新；**每批都要有反假**（改坏一处 ⇒ 对应用例必红）。

## 3. 分批方案（按依赖与被牵连面从小到大）

| 批 | 面名（拟） | 表 | 主要依赖 / 风险 |
| --- | --- | --- | --- |
| **B1** | `conversations` | `conversations` / `conversation_members` / `conversation_messages` / `conversation_stream_frames` / `conversation_stream_state` | 会话层已有按会话删除 / 导出能力（P2c-4），**改成按租户整层**即可；注意流帧是 append-only（有独立清理任务），删除顺序子 → 父 |
| **B2** | `tasks`（任务域） | `tasks` / `plan_proposals` / `plan_versions` / `orchestration_proposals` | `workbench_audit_events.task_id` 是 **`ON DELETE CASCADE`**（001）⇒ 删任务会**连带删任务域审计**。与「审计不删」的既有判据冲突 ⇒ **需裁决**（见 §4） |
| **B3** | `runs`（运行域） | `run_records` / `run_artifacts` / `run_acceptance_decisions` / `run_promotions` / `runtime_states` / `runtime_events` / `tool_actions` / `execution_idempotency` | `run_records` 被 5 处**无级联**外键引用（027/037/040/042）⇒ 必须**先子后父**显式删（与 B-4 选项 C 同一手法，可复用同一删除原语）；删运行 = **销毁验收决议与工具执行证据**（用户已就「保留策略」接受该语义，但**租户删除是另一条触发路径**，需在同一裁决里确认覆盖） |
| **B4** | `crm` | `crm_accounts` / `crm_contacts` / `crm_opportunities` / `crm_opportunity_stage_events` / `crm_quotes` / `crm_quote_lines` / `crm_contracts` / `crm_activities` / `crm_field_defs` / `crm_insights` / `crm_leads` / `crm_targets` / `crm_*`（13 张） | CRM 已有租户级 store；子表（报价行 / 阶段事件）先删 |
| **B5** | `accounts` 与其余小表 | `accounts` / `customer_admins` / `workspaces` / `job_roles` / `digital_employees` / `inbox_items` / `content_publications` / `knowledge_access_bindings` | 账号删除涉及登录态（`login_attempts` / `session_revocations` / `sso_states` 是**全局表**不含 `tenant_id` ⇒ 另议）；`knowledge_access_bindings` 是**授权配置**（004），与本批一并清 |
| **B6** | 基础设施类（**需裁决**） | `event_outbox` / `dead_letters` / `execution_idempotency` / `usage_ledger` / `export_packages` / `retention_policies` / `lifecycle_jobs` | ① `usage_ledger` 由 **B-4 结转执行器**负责（资金语义，不重复实现）；② `export_packages` / `lifecycle_jobs` 是**删除流程自身的记录** ⇒ 删除当刻不能清（否则审计与追溯断链），建议**保留**并单独登记；③ 事件外发 / 死信 / 幂等：建议清（属租户数据），但需确认「已发布事件是否保留最小元数据」 |

**建议顺序：B1 → B2 → B3 → B4 → B5**，B6 与本方案同期裁决。每批独立可交付、可回退（先加面名与 store 方法，
再切到执行器；回退 = 去掉该面名即可，不动 schema）。

## 4. 三个阻塞点 —— ✅ **已裁决（用户 2026-09-19：「按方案建议全选」）**

1. **审计类（`audit_log` / `audit_events` / `knowledge_access_audits`）**：真源 §6.2 要求「审计记录**保留最小必要
   元数据**，标记租户已删除，不保留客户原文」⇒ **不物理删**。而 `workbench_audit_events` 现为 **级联随任务删除**
   （001:26/32）⇒ 清 `tasks` 会**顺带把它删掉**。
   ⇒ **裁决：接受现状**（任务域事件随任务消失），并把它**写进契约与手册**（「任务域事件流不保留」）；
   **不改** 001 的外键语义。
2. **运行域证据销毁范围**：B-4 选 C 已接受「按龄销毁验收决议与工具执行证据」；本方案 B3 是**租户删除**触发
   （该租户整体消失）⇒ ⇒ **裁决：确认「租户删除时运行域证据不保留」**（与 B-4 同一销毁面清单：027 工具执行 /
   040 验收决议 / 042 沉淀 / 037 产物登记）。
3. **对象存储 / 向量索引 / 缓存**（真源同句要求）：⇒ **裁决：另立专项**，本方案不包含、不假装覆盖
   （对象存储里是客户原文 = 敏感度最高的一类；向量索引在 WeKnora 侧）。

## 4.1 实施计划（批次级，步骤化）

> 前置：**先做 B-4（选项 C）**（`2026-09-19-retention-executor-design.md`）——它产出的「先子后父删除原语」
> 与「按龄删除谓词」正是本方案各批要复用的东西（不写第二套 SQL）。

| 批次 | 步骤（每批 8 步，缺一不算完成） |
| --- | --- |
| **B1 会话层** ✅ | ① 契约补面名 `conversations`（层级定义：会话 / 成员 / 消息 / 流帧 / 流态）——**已落**（契约「删除清场口径」段，口径为**六张表**：`execution_idempotency` → 流帧 → 流态 → 成员 → 消息 → 会话）；② ~`PostgresConversationStore` 等既有 store 加 `delete_all_for_tenant`~ ⇒ 实施期改为**四个 store 各加 `delete_all_for_tenant`（各删自己的表）+ 组合仓储 `app/conversation/purge.py` 固定顺序调用**（比「一个 store 删四张表」更贴模块边界：六张表全在 `app/conversation/` 包内）；③ 内存实现同步（四个内存 store 各加方法 + 内存组合实现，供单测直接构造）；④ 装配：`build_commercial_components` 的 PG 分支按同一连接自建并注入（**API 与 worker 两进程都经该函数** ⇒ 同源，无需在两处各写一遍）；⑤ 逐表取证脚本 `tmp/b1-seed.py` / `tmp/b1-verify.py`；⑥ 真机删一轮 + 逐表计数 + 他租户零影响——**已做**（见 §9）；⑦ 反假——**已做**（三轮：顺序颠倒 ⇒ 真库外键错；漏删成员表 ⇒ 返回行数 5≠6 且顺序单测 3≠4；面脱钩 ⇒ 逐表未清 + 面名缺失）；⑧ 全量回归 2612 passed |
| **B2 任务域** ✅（与 B3 合并为一面） | 同上 8 步；面名 **`tasks_and_runs`**；表 = `tasks` / `plan_proposals` / `orchestration_proposals` + **整个运行域**（B3，见下行）；**复用 B-4 的删除原语**（新增 `purge_all_for_tenant`：全龄调用同一套 SQL）；审计口径按 §4 裁决写进契约。⚠️ **实施期勘误**：本行初稿把 `workbench_plan_versions` 列入任务域——它是**商业化套餐版本目录**（`006`），**永不清理**（守护用例已钉）。 |
| **B3 运行域** ✅（并入 B2 的同一面） | 表 = `run_records` / `run_artifacts` / `run_acceptance_decisions` / `run_promotions` / `runtime_states` / `runtime_events` / `tool_actions` / `execution_idempotency`；**复用 B-4 的 `purge_expired_for_tenant`**（截止取 `ALL_AGES_CUTOFF` ⇒ 不分年龄），**并额外清 `runtime_events`**（按龄清理不碰它；租户销毁时它属租户数据）。**为什么与 B2 合为一面**：任务删除以「其运行已全部删除」为前提（`run_records.task_id` 无外键）——拆成两面会留下「面名齐全、任务却按谓词被跳过」的假清场空间。 |
| **B4 CRM** | 同上 8 步；面名 `crm`；13 张表子先父后（报价行 → 报价；阶段事件 → 商机；其余按引用） |
| **B5 账号与小表** | 同上 8 步；面名 `accounts`（含 `customer_admins` / `workspaces` / `job_roles` / `digital_employees` / `inbox_items` / `content_publications` / `knowledge_access_bindings`）；全局登录态表（`login_attempts` / `session_revocations` / `sso_states`）**不含 `tenant_id`** ⇒ 单独评估（按 `user_id` 清？） |
| **B6 基础设施** | 需逐表裁决（`event_outbox` / `dead_letters` / `execution_idempotency` / `export_packages` / `retention_policies` / `lifecycle_jobs`）；**建议**：外发与死信清、幂等清、`export_packages` 与 `lifecycle_jobs` **保留**（删除流程自身的记录，清了会断审计链） |

**每批完成判据**（与 §7 一致）：逐表计数归零 + 他租户零影响 + 反假 + 全量回归 + 契约/手册/面名三处对齐。

## 5. 与 B-4（保留策略执行器）的关系

- B-4 选项 C 落地后会有「按龄删 `tasks` / `runs`（先子后父）/ `usage` 结转」的**删除原语**；
  本方案的 B2 / B3 / B6 应**复用同一批原语**（不写第二套删除 SQL），两条触发路径只是「选的哪些行」不同：
  保留策略选「龄 > N 天的行」，租户删除选「该租户的全部行」。
- **顺序建议：先做 B-4（C），再做本方案 B1–B5** —— 否则 B3 会写出第二套 runs 删除逻辑，日后必然漂移。

## 6. 每批的统一做法（与既有交付纪律一致）

1. **契约先行**：`docs/api-contract.md` 的「删除清场口径」段补该批面名与其层级含义；手册同步。
2. **store 层**：该域各 store 增 `delete_all_for_tenant`（**整层 = 该 store 在迁移里的全部租户级表**，
   非「主表」，见 2026-09-19 缺陷教训）；子表先删。
3. **双进程注入**：`app/main.py` 与 `app/worker.py` 都注入（worker 是执行删除的进程）。
4. **逐表取证**：`tmp/` 一次性脚本按表计数（删除前有值 → 删除后 0 → 他租户不受影响），真机跑 worker。
5. **反假**：改坏一处（去掉某张表的删除）⇒ 对应用例必红；不红即判据无效。
6. **回归**：后端全量 + 真库；面名变化同步 `AUDIT_ACTION_LABELS` 与前端（若有展示）。

## 7. 验收口径（本方案完成的定义）

- 55 张租户级表里，**除审计类与 B6 裁决为「保留」的表**外，逐表计数在删除后均为 0（**逐表取证留痕**）；
- `cleared_categories` 与契约面名一致；
- 真机（worker + 测试库）跑通一次完整删除，且**他租户数据零影响**；
- 手册明确「哪些面会被清、哪些不会」。

## 8. 未验证与边界（不得读成已验）

- 本方案的批次划分与风险判断来自**静态核查 + 测试库实测**；**B1 已在真库实跑并真机取证**（§9），
  B2→B5 仍**未**在真库上实跑（按纪律不先动破坏性代码）；
- 各批的**耗时 / 锁影响**未评估（大租户下逐表 DELETE 的时长与对在线请求的影响）；
- 跨批的**跨域外键**（如 `run_records.task_id` 指向已删任务、`inbox_items` 引用运行 / 审批）未逐条列出隐含顺序依赖
  ⇒ 实施每批前需再跑一次「该批表的外键入边清单」核对；
- 对象存储 / 向量索引 / 缓存**不在本方案**；用户级（非租户级）导出 / 删除沿用 P2c-4 已交付路径。

## 9. B1 实施记录（2026-09-19）

**落点**：

| 步骤 | 落点 |
| --- | --- |
| 契约 | `docs/api-contract.md`「删除清场口径（B-3 + B1）」：清场面从三面扩为**四面**，写明会话层六张表与顺序及其外键依据 |
| 各 store | `app/conversation/store.py`（消息 → 会话）、`members.py`（成员）、`stream.py`（帧 → 流态）、`idempotency.py`（幂等）各加 `delete_all_for_tenant`（**内存 + PG 双实现**；域 Protocol 同步声明） |
| 组合原语 | `app/conversation/purge.py`（新）：`PostgresConversationLayerPurgeStore` / `InMemoryConversationLayerPurgeStore` + `CONVERSATION_LAYER_ORDER` |
| 服务层 | `app/commercial/lifecycle.py`：`conversation_store` 注入 + 清场循环**新增会话面并置于首位**；未注入 ⇒ 面不清场且**如实不列** |
| 装配 | `app/bootstrap.py` 的 PG 分支：按同一连接自建并注入（流仓储带部署配置的帧上限）；内存分支不装配（内存会话仓储是 API 进程私有的，且生产删除流程在 worker / PG 强制） |
| 手册 | `docs/handbooks/customer-admin-handbook.md` §7：删除清场扩为四面 + 六张表口径 |
| 测试 | 单元 `tests/test_tenant_purge_conversations.py` **6 条**（顺序 ×2 实现 / 内存整层 + 他租户 + 幂等 / 面名只在注入时上报 / 注入即真清）；真库 `tests/test_tenant_purge_conversations_postgres.py` **3 条**（六表整层 + 他租户零影响 + 返回值 = 实际行数 / **「先删父行会被外键拒绝」可执行断言** / 服务端到端面名 + 逐表归零）；CI 真库 job 与 `tests/test_ci_assets.py` 同步钉住新模块 |

**反假三轮（真变红后还原）**：
① 组合顺序改成「先删会话行」⇒ 真库两条用例 `ForeignKeyViolation` + 顺序单测红（3 条）；
② 漏删成员表 ⇒ 返回行数 `5 != 6` + 顺序单测 `3 != 4` 红（**注意：成员表因 `ON DELETE CASCADE` 仍会归零 ⇒
   「只数行数」这一判据单独用会漏，返回值与顺序判据补住了该洞**）；
③ 服务循环去掉会话面 ⇒ 逐表未清 + `cleared_categories` 缺面 + 内存层未清（3 条红）。

**真机取证（2026-09-19，真实 worker 容器 + 真实 celery 派发 + 测试库）**：新镜像起一次性 worker（独立队列
`b1purge`，规避旧容器截胡），派发 `app.worker.run_lifecycle_jobs` 执行到期删除作业；日志
`{'exports': 0, 'deletions': 1}` + 审计 `commercial.deletion.executed` 的
`cleared_categories = ["conversations", "knowledge_governance", "memories", "skills"]`（**四面齐全**）。
逐表查库（before → after）：目标租户六张表 `1 → 0`、租户状态 `deleting → deleted`；
**他租户六张表全部原样 1**（零影响）。

**全量回归**：后端 `2612 passed`（基线 2603 ⇒ **＋9 恰为 B1 新用例**）。
**未验证（B1）**：① 大租户下逐表 DELETE 的耗时与锁影响未测；② 中断后重跑的收敛性只在设计上成立
（顺序幂等），**未做进程中途 kill 演练**；③ 内存模式不装配该面（dev-only，已在 `app/bootstrap.py` 与
`app/conversation/purge.py` 注明），其影响是「开发环境删除租户不清会话层」——**审计会如实少列该面**。

## 10. B2 + B3 实施记录（任务与运行层，2026-09-19）

**落点**：

| 步骤 | 落点 |
| --- | --- |
| 契约 | `docs/api-contract.md`「删除清场口径（B-3 + B1 + B2/B3）」：清场面从四面扩为**五面**，写明 `tasks_and_runs` 的覆盖表、共用 SQL、全龄语义与「合为一面的理由」 |
| 删除原语 | `app/commercial/retention.py`：新增 `ALL_AGES_CUTOFF`（`datetime.max` 带时区）与 `purge_all_for_tenant`（**分批循环**调用既有的按龄原语，直到一轮无删除；并额外清 `runtime_events`）+ `TenantPurgeStore` 口径别名 `delete_all_for_tenant` |
| 服务层 | `app/commercial/lifecycle.py`：清场循环新增 `tasks_and_runs` 面（复用已注入的 `retention_purge_store`，无需新注入点）；未注入 ⇒ 如实不列 |
| 手册 | `docs/handbooks/customer-admin-handbook.md` §7：删除清场扩为五面 + 任务与运行层的销毁面醒目提示 |
| 测试 | 单元 `tests/test_tenant_purge_tasks_runs.py` **2 条**（全龄截止时刻语义 / 面名只在注入时上报且与真实调用同步）；真库 `tests/test_tenant_purge_tasks_runs_postgres.py` **4 条**（整层逐表归零 + 他租户逐表对照 + 套餐版本目录留存 + 复清幂等 / `limit=1` 分批收敛 / 别名返回值 = 显式删除行数（**不含级联行**）/ 服务端到端面名与逐表归零）；CI 真库 job 与 `tests/test_ci_assets.py` 同步钉住新模块 |

**反假三轮（真变红后还原）**：
① 去掉分批循环（只跑一轮）⇒ `limit=1` 收敛用例红（`runs 1 != 2`）；
② 不删运行事件（SQL 加 `AND false`）⇒ 4 条红（运行事件残留 2 行 + 返回计数 16≠18）；
③ 不清任务/运行层（只清运行事件）⇒ 4 条红（任务 / 运行 / 子表逐表残留）。

**真机取证（2026-09-19，真实 worker + 真实 celery 派发 + 测试库）**：一次性 worker（独立队列 `b23purge`）
执行 `run_lifecycle_jobs`；审计 `cleared_categories = ["conversations", "knowledge_governance", "memories",
"skills", "tasks_and_runs"]`（**五面齐全**）。逐表查库（before → after）：目标租户**12 张表全部 `2/1 → 0`**
（含 `runtime_events` 与任务事件流 `audit_events`）、**`workbench_plan_versions` 留存 1**、
状态 `deleting → deleted`；**他租户 12 张表全部原样**（零影响）。

**全量回归**：后端 `2618 passed`（基线 2612 ⇒ **＋6 恰为 B2+B3 新用例**）。
**未验证（B2+B3）**：① 大租户（万级运行）下分批循环的总时长与锁影响未测；② 与 B1 同样**未做中断 kill 演练**；
③ CRM（B4）与账号小表（B5）仍未清场；④ 对象存储 / 向量 / 缓存不在本方案。