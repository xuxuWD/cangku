# 租户清场扩围（专项方案 · 待拍板）

> 状态：**方案（未实施）**。依据 = 用户 2026-09-19 裁决「清场扩围：先出专项方案再定」。
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
| **B1 会话层** | ① 契约补面名 `conversations`（层级定义：会话 / 成员 / 消息 / 流帧 / 流态）；② `PostgresConversationStore` 等既有 store 加 `delete_all_for_tenant`（**子先父后**：流帧 → 消息 → 成员 → 会话；流态按 run 关联一并清）；③ 内存实现同步；④ `main.py` + `worker.py` 双进程注入；⑤ 逐表取证脚本（`tmp/`）；⑥ 真机删一轮 + 逐表计数 + 他租户零影响；⑦ 反假（漏删任一子表必真库外键/计数红）；⑧ 全量回归 |
| **B2 任务域** | 同上 8 步；面名 `tasks`；表 = `tasks` / `plan_proposals` / `plan_versions` / `orchestration_proposals`；**先跑 B-4 的运行域原语**避免孤儿运行；审计口径按 §4 裁决写进契约 |
| **B3 运行域** | 同上 8 步；面名 `runs`；**复用 B-4 的 `purge_expired_for_tenant` 原语**（把「按龄」参数换成「全龄」）；销毁面清单进契约与手册 |
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

- 本方案的批次划分与风险判断来自**静态核查 + 测试库实测**，**未**在真库上实跑任何一批的删除（按纪律不先动破坏性代码）；
- 各批的**耗时 / 锁影响**未评估（大租户下逐表 DELETE 的时长与对在线请求的影响）；
- 跨批的**跨域外键**（如 `run_records.task_id` 指向已删任务、`inbox_items` 引用运行 / 审批）未逐条列出隐含顺序依赖
  ⇒ 实施每批前需再跑一次「该批表的外键入边清单」核对；
- 对象存储 / 向量索引 / 缓存**不在本方案**；用户级（非租户级）导出 / 删除沿用 P2c-4 已交付路径。