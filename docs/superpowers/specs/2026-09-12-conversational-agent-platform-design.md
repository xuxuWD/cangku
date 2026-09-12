# 对话式 AI 员工平台立项文档 · 口径（含 DeepSeek Harness 集成可行性验证）

> **状态**：**口径已确认** —— §4 的 **D1–D17 全部已定**（2026-09-12 用户拍板 + 本文档依据验证结论推导并评审通过）。**立项阶段 —— 本文件不含任何已写代码**；§14.2 落地清单须经评审通过后才可动手（宪法：立项阶段禁止写代码；技术栈与架构改动必须专项评审）。
> **已交付**：**P1a（后端对话层与员工配置）+ P1b（前端对话层与配置区）已于 2026-09-12 完成并推送**（CI 四 job 全绿）；详见 §16 的真实 PostgreSQL 回归记录。
> **最高风险决策**：**D8（允许文件与命令）**，其代价与硬门禁见 §15 风险 9 —— **路线 A 未实现之前，这两项能力不得开启**。
> **最新修订**：D14–D17（界面交互模型并入 P2，并拆为 P2a/P2b/P2c），展开见 **§17**；该节有 4 个未决问题（Q7–Q10）需在 P2a 开工前答复。
> **日期**：2026-09-12　**基线**：`main` `f486de0`
> **前序**：本文件**首次**引入「对话层 / 数字员工配置 / 记忆 / 技能 / Harness / CRM / 自进化」七条线；此前所有立项文档均未覆盖。
> **配套材料**：
> - 开源平台调研（既有，2026-09-09）：[open-source-agent-platform-research.md](file:///d:/徐徐AI学习/公司工作台/docs/open-source-agent-platform-research.md)
> - 本轮三路联网调研（Agent 平台与 Harness / 记忆技能与自进化 / 开源 CRM）、仓库能力盘点、**「EvoFlow」命名冲突专项调研**，结论已摘入 §2.2、§2.3、§2.4

---

## 1. 背景与目标

### 1.1 现状

工作台今天是一个**任务控制台**，不是**人机协同平台**：员工只能在表单里提交结构化的任务、在固定页面上查固定字段；数字员工只是「标识 + 中文名 + 所属岗位 + 状态」四条字段的目录项；`runtime/adapters/*` 的设计前提是**把外部平台（AgentScope / RAGFlow）当执行器**，它自己不是 agent loop。

### 1.2 目标

让员工**用自然语言**布置任务与查资料；让每个**数字员工可独立配置**（提示词 / 模型 / 温度 / 技能 / 知识库 / 记忆策略）；让平台具备**记忆、技能、Harness**三层能力；并**新增客户管理**（分析客户、解读需求、维护关系、给出跟进计划）。终态是一个**可自主学习进化的 AI 自动化公司工作中台**。

### 1.3 非目标（明确不做）

| 不做 | 原因 |
| --- | --- |
| 把工作台做成对外售卖的通用 Agent 产品 | 商业化边界**已定：按可切换设计**（§4 D1）。本期只保证「不引入会阻断未来多租户化的依赖」，不实现计费、白标、配额售卖 |
| 组织 / 部门树、汇报线 | 独立领域建模，须单独立项（与 [`2026-09-12-agent-directory-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-agent-directory-design.md) §1 非目标一致） |
| CRM 的多币种 / 报价 / 合同 / 发票 / 营销自动化 / 工单门户 | 这些是 SuiteCRM/Odoo 级「企业复杂度」，不是本场景需求（§2.3 结论） |
| 训练 / 微调自有模型 | 自进化的正确形态是「沉淀技能与提示词 + 离线评测 + 人工批准」，不是改权重 |
| 对外宣称「自主进化」 | 宪法红线：不承诺未被真实数据证实的能力。可交付的只是**工程闸门**（§14 P5） |
| 让 Harness 触碰本项目的数据库 | 跨语言进程边界；Harness 只能通过 API 交互（§6） |

---

## 2. 事实核查（实际读码 / 实测确认，非印象）

### 2.1 仓库现状（逐文件核对）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | **全仓库不存在任何对话 / 会话消息模型或接口**（`conversation`/`message`/`chat` 检索零命中；`app/sessions.py` 是会话令牌撤销，不是对话记录） | 全仓检索 |
| 2 | `MemoryStore`（短期记忆）类**存在但从未接线**，仅被测试引用；无长期记忆表、无画像抽取 | [agent_services.py](file:///d:/徐徐AI学习/公司工作台/app/agent_services.py#L81-L110)、`tests/test_agent_services.py:44-52` |
| 3 | `DigitalEmployee` 只有 `tenant_id/agent_key/name/role_key/status/description/created_by/created_at/updated_at`，**无提示词 / 模型 / 温度 / 技能字段** | [models.py](file:///d:/徐徐AI学习/公司工作台/app/workforce/models.py#L74-L84)、[022_workforce_directory.sql](file:///d:/徐徐AI学习/公司工作台/migrations/022_workforce_directory.sql#L24-L36) |
| 4 | `ModelGateway.choose()` 入参只有 `capability / data_classification / preferred`，**没有 agent_key**；且只注册了**单个**来自 `planner_model_name` 的模型 | [agent_services.py](file:///d:/徐徐AI学习/公司工作台/app/agent_services.py#L42-L60)、[bootstrap.py](file:///d:/徐徐AI学习/公司工作台/app/bootstrap.py#L499-L507) |
| 5 | **无 agent 循环**：`MockRuntime` 是对 `plan.steps` 的一次线性遍历，没有「观察→再决策」回路 | [mock.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/mock.py#L33-L67) |
| 6 | **无沙箱**：仅健康摘要里透传一个 `sandbox` 字符串字段与一个高风险能力名 | [registry.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/registry.py#L72-L81)、[capabilities.py](file:///d:/徐徐AI学习/公司工作台/app/capabilities.py#L22-L31) |
| 7 | **无子 agent、无上下文压缩**：`evaluation.replay` 明确返回 `{"executed": false, "mode": "event_summary_only"}` | [evaluation.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/evaluation.py#L15-L16) |
| 8 | **无技能 / 插件模型**；`CapabilityPolicy` 权限类存在但**未在运行路径实例化**，仅测试使用 | [capabilities.py](file:///d:/徐徐AI学习/公司工作台/app/capabilities.py#L34-L56) |
| 9 | **无 MCP**：`app/` 中 MCP 零命中，仅文档提及 | 全仓检索 |
| 10 | **无 CRM**：`customer_admin` 只是账号角色名，无客户 / 联系人 / 商机 / 跟进实体 | [tenant.py](file:///d:/徐徐AI学习/公司工作台/app/commercial/tenant.py#L46-L54) |
| 11 | **无离线评测体系**：只有冒烟检查与内容安全二分类 | [staging.py](file:///d:/徐徐AI学习/公司工作台/app/runtime/staging.py#L87-L106) |
| 12 | `pgvector` **装了扩展但从未使用**：无 vector 列、无向量索引、无向量查询 | [001_initial.sql](file:///d:/徐徐AI学习/公司工作台/migrations/001_initial.sql#L1) |
| 13 | 自进化**只有状态机骨架**：`GrowthProposalStore` 有 `pending_review→approved→active/rejected`，但仅测试引用，无评测 / 灰度 / 回滚 | [agent_services.py](file:///d:/徐徐AI学习/公司工作台/app/agent_services.py#L132-L160) |
| 14 | **已有且质量不错的地基（不要动）**：多租户查询层过滤、5 处人工审批闸门、append-only 审计、Outbox/死信、站内通知、运行状态机与结束原因、工具白名单 `ToolCatalog`、**数字员工级知识范围绑定** | [repository.py](file:///d:/徐徐AI学习/公司工作台/app/repository.py#L118-L127)、[approvals.py](file:///d:/徐徐AI学习/公司工作台/app/approvals.py#L41-L90)、[store.py](file:///d:/徐徐AI学习/公司工作台/app/audit/store.py#L12-L27)、[models.py](file:///d:/徐徐AI学习/公司工作台/app/planner/models.py#L60-L119)、[knowledge_policy.py](file:///d:/徐徐AI学习/公司工作台/app/knowledge_policy.py#L42-L55) |
| 15 | 审计明细是**严格白名单**：新增动作若带新键必须同步扩 `ALLOWED_DETAIL_KEYS`，否则写审计直接抛错 | [models.py](file:///d:/徐徐AI学习/公司工作台/app/audit/models.py#L57-L86) |
| 16 | 迁移清单须同步 `.env.staging.example`，否则 staging 预检永久 `blocked` | [.env.staging.example](file:///d:/徐徐AI学习/公司工作台/.env.staging.example#L30) |

**结论**：地基（治理层）值得保留；**要建的七条线全部为空**，其中事实 2、8、13 是「有类未接线」——它们说明前几期已经预留了扩展点，但没有决定「谁来调用」。

### 2.2 开源调研结论（三路，2026-09-12）

**A. 对话式 Agent 平台与 Harness**

| 结论 | 依据要点 |
| --- | --- |
| **「多租户 + RBAC + 审计 + 审批」是开源生态的集体空白** | 所有 agent 框架（LangGraph / CrewAI / ADK / PydanticAI / Mastra）连「用户」概念都没有；Dify / FastGPT 锁在付费版 |
| **许可证雷区明确** | `n8n` = Sustainable Use License（**禁止**对外 SaaS 与白标）；`MaxKB` = GPL-3.0（强传染）；`Dify` / `FastGPT` = 修改版 Apache-2.0（**多租户运营需书面商业授权**）；`Twenty` / `EspoCRM` / `SuiteCRM` = AGPL-3.0 |
| **许可证干净的一档** | `BISHENG`（Apache-2.0，**唯一自带完整企业内控**）、`RAGFlow`、`Coze Studio`（但开源侧**近 90 天仅 1 名贡献者**）、`LibreChat`（MIT，内置 Skills/Subagents/MCP/RBAC）、`OpenHands`（MIT 核心 + Python SDK）、`DeepSeek Harness`（MIT） |
| **技能格式有事实标准** | `SKILL.md`（Agent Skills 开放标准）已被 **30+ 产品**采纳（Copilot / Cursor / Codex CLI / OpenHands / Letta…），渐进式披露，token 效率显著优于把整个 REST API 镜像成工具 |
| **MCP 已是事实标准，但不含治理** | 2026-07-28 规范已无状态化；**只解决「怎么连」，不解决「谁可以调什么、留什么审计」** |
| **`deepseek-harness` 真实存在** | 见 §2.3（已实测核验，非二手资料） |

**B. 记忆 / RAG / 技能 / 自进化**

| 结论 | 理由 |
| --- | --- |
| 短期记忆**自建** | 任何框架的 working memory 本质是「Redis 存一份 + TTL」，约 200 行 |
| 长期记忆**自建表 + 借鉴设计** | 抄 Graphiti 的**双时间轴**（`valid_from/valid_to/superseded_by`）；Mem0 每次 `add()` 触发一次 LLM 抽取且**无成本熔断** |
| 向量库**沿用 pgvector** | 已有扩展与镜像，< 50M 向量够用；省一个 stateful 服务 |
| 知识解析**旁路** | PDF / 表格 / 公式解析用 RAGFlow DeepDoc 级能力，不自建 |
| 技能层**用标准** | MCP 官方 Python SDK + `SKILL.md` 格式；**白名单 / 权限 / 审计自建** |
| 自进化**照搬成熟范式** | Microsoft **SkillOpt**（MIT）：`rollout → reflect → 受限编辑（有编辑预算）→ held-out 验证集严格提升才接受 → 导出`；**Langfuse labels**（MIT core）：`版本 → 校验 → 门禁 → 灰度 → 观测 → 回滚` |
| **硬约束：生成者 ≠ 评审者** | 有实证 LLM 自评准确率仅 46.4%，同模型又改又评必然失效 |

**C. CRM**

| 结论 | 理由 |
| --- | --- |
| **成熟开源 CRM 社区版都没有「健康度 / 流失预警 / NBA」** | Twenty / EspoCRM / SuiteCRM / Vtiger / Kortezа / Krayin 逐个核实：**均无**；Odoo 19 有但**大概率在付费版**（未核实） |
| **这部分必然自建** | 规则分（RFM + 互动活跃度 + 阶段停留时长）打底 + LLM 只做「解读 + 跟进建议」；**第一期不训模型** |
| 数据模型抄谁 | 骨架对齐 **Salesforce**（Lead → Account + Contact + Opportunity + Activity/Task）；自定义字段抄 **SuiteCRM `_cstm` 思路**（PG 用 JSONB + 元数据表）；关系维护抄 **Monica**（双向关系 + 重要日期 + 提醒） |

### 2.3 DeepSeek Harness 集成可行性验证（2026-09-12 实测）

> **方法**：`npm view` 核验存在性 → 安装 `@deepseek-ai/dsh@0.1.5-rc.1`（518 包）到**仓库之外**的隔离目录 `d:\徐徐AI学习\_dsh-verify\` → 逐个读 `.d.ts` / `lib/*.js` / `README.md`。**未做运行时验证**（未起服务、未接模型）。

**存在性与成熟度（已核验）**

| 项 | 事实 |
| --- | --- |
| 包 | `@deepseek-ai/dsh`，npm 上真实存在；仓库 `github.com/deepseek-ai/deepseek-harness` |
| 许可证 | **MIT**（与 D1「避开 AGPL / 商业授权依赖」不冲突） |
| 版本 | `dist-tags` = `{alpha: 0.1.5-alpha.2, next: 0.1.5-rc.2, latest: 0.1.5-rc.1}` → **`latest` 指向 RC，没有稳定版** |
| 节奏 | 首发 `0.0.1-rc.1`（2026-08-10）→ `0.1.5-rc.1`（2026-09-10），**一个月 22 个版本** |
| 会话格式 | `dsh-session-format-v0-to-v1` / `v1-to-v2` / `v2-to-v3` **三代格式迁移包已存在** → 破坏性变更是**已发生的事实**，不是预告 |
| 安全 | 官方 README 自述**尚未接受安全审计**，沙箱与审批不保证隔离 |

**四条契约的验证结论**

| 契约 | 结论 | 证据 |
| --- | --- | --- |
| **① 外部审批回调** | ❌ **标准嵌入路径做不到** | `dsh-sdk-protocol` 仅 3 个请求（`initialize`/`session/prompt`/`shutdown`）+ 4 个**通知**，**无审批方法**；`dsh-sdk-jsonrpc-server/lib` 内 grep `.request(` **零命中**（服务端从不发反向请求）；README 自述「Server→client requests are a **dead capability**」。进程内可用 cordis waterfall `approval/request`，但那是**进程内事件、不是进程边界协议** |
| **② 会话级工具白名单** | ✅ **能做到** | `dsh-tools` 的 `restrict(filter: {allow?, deny?})` —— 注释写明「Restrict global tools for the **calling agent scope**」，可返回 disposer 解除；`ctx.agents.create({ setup })` 的 `setup` 拿到 scoped ctx。MCP 工具进同一 registry，同样受限 |
| **③ 租户 / trace 透传** | ❌ **没有任何开放字段** | 全库 grep `tenantId\|traceId` **零命中**；`SessionHeader` 与 `CreateSessionOptions.meta` 均为**闭合类型**；遥测用 **OTel Logs 而非 Spans**，Resource 属性硬编码 |
| **④ 沙箱** | ⚠️ **可用但 partial，且 fail-closed** | `dsh-sandbox-local` 明确 `"windows-acl": "partial"`；实现为 WRITE_RESTRICTED 受限令牌，**只约束写，不约束读/网络/进程可见性**；不支持时抛 `SANDBOX_UNAVAILABLE`，**不静默降级**（这点是好的） |
| （附）嵌入方式 | ✅ stdio JSON-RPC | `dsh --profile sdk`，Python 后端可直接驱动；**但无 cancel、无 session-close、无版本协商**；`dsh --profile headless "task"` 是**一次性任务**，不是常驻多轮服务 |

**另外三条硬伤（影响设计）**

1. **审批请求不携带工具参数**（`ApprovalRequest` 只有 `toolName / callId / reason`）
2. **审批结果只有 `allowed-once`**，没有 allow-always / 规则记忆 / 撤销
3. **不存在 `metadata` / `tags` / `attributes` 开放 bag**，会话头字段是闭合枚举

**已纠正的一处错误判断**：曾据 npm 告警推断「工具执行链路残缺」（`dsh-subprocess-local` 的 postinstall 被拦）。核查 `scripts/ensure-spawn-helper.mjs` 全文后确认：该脚本只给 node-pty 的 **POSIX** `spawn-helper` 加可执行位，而 `node-pty/prebuilds/win32-x64/` 下**没有这个文件**，在 Windows 上是**纯 no-op**；沙箱走独立的受限令牌 runner，与之无关。**该结论基于文件证据，未做运行时验证（标为推断）。**

---

### 2.4 「EvoFlow」命名冲突专项调研（2026-09-12）

> **背景**：用户点名要研究「EvoFlow」。实测发现**至少 6 个互不相关的项目共用这个名字**，必须先分清。
> **用户已定**：**只当参照物，自己实现**（不采购、不集成其代码）。

| 候选 | 本质 | 许可证（一手核实） | 活跃度 | 处置 |
| --- | --- | --- | --- | --- |
| **EvovexAI/EvoFlow**（[evovexai.com](https://www.evovexai.com/)） | 商业桌面端「Agent Runtime + 控制平面」，含智能体员工与治理 | **`Evovex AI Non-Commercial License 1.0`** —— 自述「非 OSI 开源许可，商用需单独书面协议」，且把「**营利性实体的内部业务运营**」也列入 Commercial Use | 134★，2026-09-11 仍在推 | **仅作参照物**（见下「值得抄的设计」）；其公开仓库**根目录无任何业务源码**（英文 README 自述「Source code is not yet publicly released」），中文 README 却给出 `git clone && make dev` 步骤，**官方自相矛盾，未核实** |
| **FlowEvo**（[DEFENSE-SEU/FlowEvo](https://github.com/DEFENSE-SEU/FlowEvo)） | training-free：workflow ↔ 可执行技能**共进化** | **Apache-2.0** → 可商用 | 20★，2026-08-23 仍在推 | **自进化层的首选蓝本**（§14.1 P6） |
| arXiv 2502.07373 EvoFlow | 生态位进化算法搜索异构 workflow 种群 | **代码仓库 404，从未放出**（论文写的是 "will be available"） | 论文 2025-02 | **只借路由思想**；不得作为任何实现依据 |
| `evolution-foundation/evo-flow` | 客户互动与营销自动化引擎（Journey/Segment/Campaign） | Apache-2.0（已更名 `evo-flow-community`） | 169 commits | **无关**：不含 CRM 语义、单账号设计、最小约 9 容器 |
| `Micdiane/EvoFlow` | 个人构想 + 脚手架 | **无 LICENSE 文件** | 2025-06 后停更 | 忽略 |
| `superk668/EvoFlow` | 自进化多 Agent 前端开发 workflow | **无 LICENSE 文件** | 2026-01 后停更 | 忽略 |

**附带发现的三类「伪开源」陷阱（登记备查）**

1. **evovexai/EvoFlow**：看起来像开源（有 GitHub 仓库、README 里有构建步骤），**实际无源码 + 非商业许可**。按许可原文，**即便只在公司内部使用也可能需要先取得授权**。
2. **arXiv 2502.07373 EvoFlow**：看起来能用，**实际连代码都没有**。
3. **`EvoMap/evolver`**（顺带查到）：README 头标 MIT，正文自述「**核心进化引擎以混淆形式分发**」——开源壳 + 闭源核。

**值得借鉴的「员工级治理配置」（本立项直接采纳）**

evovexai 的员工治理字段设计比本方案初稿更细，经评审后**纳入 §7.2**（字段名对齐我方命名习惯，金额按宪法改为整数分）：

```
autonomy_level            自治等级：approval_for_all | approval_for_risky | full_auto
risk_threshold            风险阈值
approval_timeout_minutes  待批超时后的自动行为
daily_budget               每日预算熔断
department / reports_to    汇报线（本期不做，属组织架构，见 §1.3）
kpis / domain_scope / heartbeat_rrule  （本期不做）
```

**自进化路线选型结论（不和稀泥）**

企业内部数字员工**选 FlowEvo 范式，不选论文版 EvoFlow**：

1. **痛点匹配**：内部数字员工的价值是「同一类事第二次做得更快更稳」→ FlowEvo 把成功 workflow **编译成可复用技能并持久化**，命中「经验沉淀」；论文版优化的是「不同难度 query 选哪套 workflow」，那是**路由**问题。
2. **成本可行性**：论文版必须在种群上反复 rollout + 交叉/变异/生态位选择，而它的评测全是**反馈密集、可自动打分**的数学/代码/具身 benchmark；企业内部任务量小、成功信号稀疏、每次 rollout 都是真钱 → Pareto 搜索收益基本体现不出来。FlowEvo 是 **training-free + 推理期自适应**。
3. **可挂接审批闸门**：FlowEvo 的 **`admission`（技能准入）+ 效用打分 + 抑制负迁移** 天然是闸门结构，「数字员工想固化一条新技能时人审一次」正好插在 admission。论文版 EvoFlow **全文无任何 human-in-the-loop 设计**。
4. **法律与工程现实**：FlowEvo = Apache-2.0 + 代码在 + 分层清晰（`src/compiler` / `src/governance` / `src/memory`）；论文版 = 无代码、无许可证、论文自述数字前后不一致。

**必须记录的限制**：FlowEvo 是**论文配套研究代码**，不是产品级库，嵌入服务需自写工程外壳；它**自身也没有人类审核设计**——本方案是要把**既有审批层**插进它的 admission 环节，而不是采用它的判定。

---

## 3. 目标态一句话

> 员工在**对话入口**用自然语言布置任务或查询资料；平台把意图路由到某个**可配置的数字员工**（各自持有提示词 / 模型 / 温度 / 技能 / 知识范围 / 记忆策略）；Harness 跑 agent loop 并调用工具，**任何写类工具在执行前必须过控制面的审批闸门并写审计**；同时提供**客户管理**（客户 / 联系人 / 商机 / 跟进记录 + LLM 解读与跟进建议）；长期在一个**带人工闸门的自进化闭环**里沉淀技能与提示词。

---

## 4. 决策记录

> 本节是**唯一权威的决策日志**。§13 的开放问题已全部答复，决议编号合并到本节。

| # | 决策点 | 结论 | 状态 |
| --- | --- | --- | --- |
| **D1** | 商业化边界 | **按可切换设计**：架构从一开始按多租户隔离（复用既有租户模型），但**优先选许可证干净的组件**，不引入 AGPL / 需商业授权的依赖。不在本期实现计费、白标、配额售卖 | **已定**（用户，2026-09-12） |
| **D2** | Agent 编排（Harness）路线 | **集成 DeepSeek Harness（MIT）** 作为执行内核 | **已定**（用户，2026-09-12） |
| **D3** | CRM 路线 | **自建轻量 CRM 模块**（数据模型对齐 Salesforce/SuiteCRM，JSONB + 元数据表做自定义字段，外挂 LLM 做解读与跟进建议） | **已定**（用户，2026-09-12） |
| **D4** | 第一期切口 | **对话 + 数字员工配置** | **已定**（用户，2026-09-12） |
| **D5** | dsh 的集成姿态 | **审批不放 dsh，放我们自己实现的工具内部**。依据 §2.3：跨进程审批不可用、审批请求不含参数、无 allow-always。dsh 只负责 agent loop + `restrict` 收窄工具集 | **已定**（本文档推导 + 2026-09-12 评审通过） |
| **D6** | 会话与租户的映射 | 自建 `workbench_conversations` 持有 `tenant_id / agent_key / operator_id`，`dsh_session_id` 只做映射。**dsh 侧只存会话内容，租户语义 100% 在本项目**。依据 §2.3 Q3（dsh 无任何可承载租户号的字段） | **已定** |
| **D7** | 第一期 Harness 策略 | **P1 先用现有 `MockRuntime`** 打通对话层与配置层，**P2 再接真 dsh**。理由：dsh 集成复杂度集中在「自定义工具 + 回调审批」，先做不依赖它的部分，避免同时调试两侧 | **已定** |
| **D8** | P1 数字员工的能力边界 | **允许文件读写与命令执行**。同时定三条硬约束：① 拦截走**路线 A**——文件/命令**不用 dsh 原生实现**，改为我们自己实现并注册进 dsh 的工具，工具内部先回调 FastAPI 审批；② **只在隔离容器（Docker / k8s）内执行**，不进开发机与应用机；③ **该能力 P2 才真正生效**（P1 是 MockRuntime，不做真实工具调用） | **已定** |
| **D9** | 会话是否纳入既有审批聚合 | **不纳入**。不新增第五类；需要审批的是**工具执行**，沿用既有 `run_approval` / `task_approval` 语义 | **已定** |
| **D10** | CRM 与数字员工的关系 | **独立模块**：客户/联系人/商机/跟进是独立领域对象与独立权限，数字员工只能通过受控工具读写 | **已定** |
| **D11** | `system_prompt` 防护 | 上限 **8000 字符**；入库前过安全扫描；**显式禁止包含可改变权限判定的指令**（如「忽略审批」），命中则 `422` | **已定** |
| **D12** | pgvector 落地方式 | `023` **不建任何 `vector` 列，也不建占位列**；P3 在记忆表上**一次性**建 `vector` 列与索引（届时 embedding 模型已定）。理由：向量列一旦写死维度，改维度就要重建索引；而 `023` 里没有任何表是记忆向量的落点，**预留占位列属于为假想需求设计** | **已定**（2026-09-12 实现时收窄，原稿曾要求建 JSONB 占位列） |
| **D13** | 自进化评测集来源 | **用真实历史会话构建 golden set**。推论：**P6 必须排在最后**，且会话量起来前 **P6 不具备开工条件** | **已定** |
| **D14** | **界面交互模型的目标形态** | 现形态（11 个平级页面 + 整页导航 + 提交后轮询）判定为**管理后台**，不是工作台。目标改为**「对话主轴 + 右侧舞台 + 过程可见」**：对话是主轴，产物（子任务 DAG / 文件 diff / 终端 / 运行过程）在右侧舞台并排呈现，侧栏由 11 个平级页重组为分组（对话 / 任务与项目 / 员工 / 资产 / 知识 / 治理） | **已定**（用户，2026-09-12） |
| **D15** | **实时流契约** | 会话消息改为**可推流**（SSE）；PG 持久化**流帧序列**（`(tenant_id, conversation_id, run_id, seq)` + `is_terminal`），**支持断线续播**。理由：没有流，前端无法做「边跑边看」 | **已定** |
| **D16** | **过程事件（trace）契约** | 把 agent 的**工具调用 / 模型响应 / 文件改动 / 计划变更**暴露为**可订阅的过程事件**，供右侧舞台消费；事件与既有审计分离（审计记「谁改了什么」，过程事件记「agent 在做什么」） | **已定** |
| **D17** | **D14–D16 的落地时机与拆分** | 三条线**并入 P2**（因为 P2 接上 dsh 后才有真流可推、有真 trace 可追、有真文件操作可 diff）。但 P2 原范围已很大，**必须拆为 P2a/P2b/P2c 三段**，各自独立可验收 | **已定**（本文档推导，2026-09-12） |

---

## 5. 总体架构

```
┌─ 对话层（新）────────  会话 / 消息 / 流式输出；对话式下单与查询
├─ 数字员工配置层（新）─  提示词·模型·温度·技能·知识范围·记忆策略（每员工一份）
├─ Harness 层（新，外部） dsh：agent loop / 工具 / 子agent / 上下文压缩
├─ 记忆层（新）────────  短期(Redis+TTL) + 长期(PG+pgvector，双时间轴) + 画像
├─ 技能层（新）────────  SKILL.md 格式 + 技能注册表 + MCP 客户端
├─ 知识层（半有）──────  既有 agent 级绑定 + 首次真正启用 pgvector
├─ CRM 模块（新）──────  Account/Contact/Lead/Opportunity/Activity + 跟进计划
├─ 自进化层（新）──────  候选 → 离线评测 → 人工批准 → 灰度 → 回滚
└─ 治理层（已有，不动）─  租户 / RBAC / 审批 / 审计 / 预算 / 通知 / 生命周期
```

**两条不可违背的架构原则**

1. **治理层是唯一事实源**。租户、身份、权限、审批、审计、预算、任务状态只能出自本项目。任何外部系统（dsh / RAGFlow / 未来任何平台）**都不得持有这些语义**。
2. **跨进程边界，不做代码级耦合**。外部系统只通过 HTTP / stdio JSON-RPC 交互。这既是 AGPL 传染的规避手段，也避免出现「第二套用户与权限模型」。

---

## 6. 关键约束：dsh 的用法（本期最重要的技术约束）

**能用的**：agent loop、工具调度、子 agent、上下文压缩、原生 `SKILL.md` 技能（`dsh-skill-filesystem`）、原生 MCP 客户端（`dsh-mcp-client`）、会话日志与回放；工具集可用 `restrict` 按会话收窄。

**不能用的（必须在我们的控制面兜住）**：

| dsh 不提供 | 我们的替代 |
| --- | --- |
| 跨进程外部审批 | 写类工具**由我们自己实现**，工具内部回调 FastAPI 审批接口 |
| 审批请求携带工具参数 | 同上——我们自己实现工具，参数天然在手 |
| allow-always / 规则记忆 | 审批规则存我自己的库（`approval_rules`，属后续期） |
| 租户 / trace 字段 | 自建 `conversations` 表做映射（D6） |
| 多租户 / RBAC / 审计 | 既有治理层 |
| 完整沙箱（Windows 仅 partial，只约束写） | **不把 dsh 当安全边界**；高危工具一律经由我们自己的实现，dsh 沙箱只作为纵深防御的一层 |
| cancel / session-close | 会话生命周期由我们的超时与预算熔断控制 |

---

## 7. 数据模型（第一期）

> 迁移编号 **`023_conversational_agent.sql`**（`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`）。仅示意字段与约束，实现时以迁移文件为准。

### 7.1 新增表

```sql
-- 会话：租户语义的唯一落点（D6）
CREATE TABLE IF NOT EXISTS workbench_conversations (
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    agent_key       TEXT,                 -- 路由到的数字员工（目录可停用，故不加外键）
    operator_id     TEXT NOT NULL,        -- 发起人（账号 id）
    title           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL CHECK (status IN ('active','archived')),
    dsh_session_id  TEXT,                 -- 外部 Harness 的会话 id（映射用，可为空）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id)
);

-- 消息：append-only
CREATE TABLE IF NOT EXISTS workbench_conversation_messages (
    tenant_id       TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
    content         TEXT NOT NULL,
    tool_name       TEXT,
    tool_call_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, message_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id)
);
```

**设计要点**
- **复合外键** `(tenant_id, conversation_id)`：租户隔离写进约束，不只靠 `WHERE`（与 `workbench_job_roles` / `workbench_tasks` 同一手法）。
- 消息表**不建 `updated_at`、不建 update 路径**：append-only，与审计表同构。
- `agent_key` **刻意不加外键**：数字员工可停用（§既有 D4「停用不删除」），历史会话必须永远可解析。
- `dsh_session_id` 只做映射，**不持有任何租户语义**（D6）。

### 7.2 扩展既有表（数字员工配置）

```sql
ALTER TABLE workbench_digital_employees
    ADD COLUMN IF NOT EXISTS system_prompt     TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model_key         TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS temperature       NUMERIC(3,2) NOT NULL DEFAULT 0.20,
    ADD COLUMN IF NOT EXISTS tool_allowlist    JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS memory_policy     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- 治理字段：参照 EvovexAI EvoFlow 的员工级治理设计（§2.4），金额按宪法用整数分
    ADD COLUMN IF NOT EXISTS autonomy_level    TEXT NOT NULL DEFAULT 'approval_for_risky'
        CHECK (autonomy_level IN ('approval_for_all', 'approval_for_risky', 'full_auto')),
    ADD COLUMN IF NOT EXISTS risk_threshold    TEXT NOT NULL DEFAULT 'high'
        CHECK (risk_threshold IN ('low', 'medium', 'high')),
    ADD COLUMN IF NOT EXISTS approval_timeout_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (approval_timeout_minutes BETWEEN 5 AND 10080),
    ADD COLUMN IF NOT EXISTS daily_budget_cents BIGINT NOT NULL DEFAULT 0
        CHECK (daily_budget_cents >= 0);
```

| 字段 | 说明 | 约束 |
| --- | --- | --- |
| `system_prompt` | 人设与指令 | 长度上限待定（§13 Q2），**入库存前必须过安全扫描**（提示注入） |
| `model_key` | 指向 `ModelGateway` 的模型键 | 必须在网关已注册的候选内，否则 `422`；**空值 = 用默认模型** |
| `temperature` | 温度 | `0.00–2.00`，`CHECK` 约束（此处是参数不是金额，允许 `NUMERIC`） |
| `tool_allowlist` | 允许调用的工具名数组 | 必须是 `ToolCatalog` 白名单的子集，否则 `422` |
| `memory_policy` | 记忆策略（启用哪些层、保留期） | JSONB；第一期只做「短期开 / 关 + 保留轮数」 |
| **`autonomy_level`** | **自治等级**。`approval_for_all` = 每个工具都要批；`approval_for_risky` = 只有风险 ≥ `risk_threshold` 的才批（**默认**）；`full_auto` = 免批（**仅允许 `super_admin` 设置，且必须写审计**） | 枚举 `CHECK`；`full_auto` 的授予动作本身要进审批（§8） |
| **`risk_threshold`** | 触发审批的风险阈值，对齐既有 `RiskLevel`（`low/medium/high`） | 枚举 `CHECK`；`approval_for_risky` 时生效 |
| **`approval_timeout_minutes`** | 待批超时后的自动行为时间上限 | `5–10080`；**超时语义 = 拒绝（fail-closed）**，不是自动放行 |
| **`daily_budget_cents`** | 每日预算熔断（整数分，对齐既有 `usage_ledger` 口径） | `>= 0`；`0` 表示「用租户默认」；**超限直接拒绝，不降级** |

**为什么把这些放进「数字员工」而不是新建「策略」表**：自治等级与预算上限是**员工的属性**（同一个员工在不同岗位不该有两套自治等级），与 `name` / `status` 同级；独立成表会制造第二份真相。**汇报线（`reports_to`）与 KPI 不做**——那是组织架构，属 §1.3 明确排除的范围。

**不新建配置表**：配置是数字员工的**属性**，不是独立实体（避免「一个员工多份配置」的第二真相）。

---

## 8. 权限模型

| 动作 | `super_admin` | `ceo` | `department_lead` | `employee` | `customer_admin` |
| --- | --- | --- | --- | --- | --- |
| 与数字员工对话 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 查看**自己**的会话与消息 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 查看他人会话 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 配置数字员工（提示词/模型/温度/技能/记忆） | ✅ | ❌ | ❌ | ❌ | ❌ |
| 批准写类工具执行 | ✅ | ✅ | ❌ | ❌ | ❌ |
| **把某员工的 `autonomy_level` 设为 `full_auto`（免批）** | ✅ | ❌ | ❌ | ❌ | ❌ |

**强制约束（每条都要有对应用例）**

1. **严格本租户**：所有查询带 `tenant_id`，不依赖前端传参。
2. **数据归属**：普通岗位只能读写**自己发起**的会话（`operator_id` 必须等于当前身份），改别人的 `conversation_id` 一律 `404`（而非 `403`，避免探测存在性）。
3. **写类工具必须过审批**：这是本期**最容易出严重缺陷**的地方——对话入口与表单入口必须收敛到**同一套** `ensure_can_*` 与审批闸门，不允许对话路径绕过。**自治等级只决定「是否需要人批」，不决定「是否绕开权限判定」**：即 `full_auto` 的员工仍然不能做其操作者无权做的事。
4. **`full_auto` 是特权，不是默认**：默认值必须是 `approval_for_risky`；把它改成 `full_auto` 的动作本身要「仅 `super_admin` + 写审计」，且**不得由数字员工自己或对话内容触发**。
5. **审批超时 fail-closed**：超过 `approval_timeout_minutes` 未决议 → **按拒绝处理**，绝不自动放行。
6. **对话不新增权限面**：对话能做的事**不超过**该用户在表单里能做的事（初期甚至更窄：只开只读工具）。
7. **配置变更必须写审计**，并同步扩 `ALLOWED_DETAIL_KEYS`（事实 15，否则写审计直接抛错）。
8. **预算熔断**：`daily_budget_cents` 与既有 `ensure_can_create` 的 `budget` 语义叠加，超限**直接拒绝而非降级**。
9. **文件与命令的额外约束（D8，P2 生效）**：① 文件读写与命令执行**不得使用 dsh 原生 bash/fs 工具**，必须是我们自己实现并注册进 dsh 的工具；② 工具内部**先回调 FastAPI 审批，批准后才真正执行**；③ **只在隔离容器（Docker / k8s）内执行**，禁止落在开发机与应用机；④ 该能力的工具名必须出现在该员工的 `tool_allowlist` 里，否则 `restrict` 直接隐藏。
10. **提示词不得改变权限判定（D11）**：`system_prompt` 命中「忽略审批」「跳过权限」这类指令时在写入阶段就 `422`，**不允许进入运行期再拦**。

---

## 9. 接口契约草案（实现时写入 `docs/api-contract.md`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/conversations` | 新建会话；请求体含 `agent_key`（可选，缺省用默认员工）；返回 `conversation_id` |
| `GET` | `/api/v1/conversations` | 列表；`limit` 1–200 + `offset` + `total`（宪法：列表必须分页） |
| `GET` | `/api/v1/conversations/{id}` | 会话详情（含消息） |
| `POST` | `/api/v1/conversations/{id}/messages` | 发送一条用户消息；返回 `message_id`，助手回复经流式/轮询获取 |
| `POST` | `/api/v1/conversations/{id}/archive` | 归档（不删除） |
| `GET` | `/api/v1/workforce/agents/{agent_key}/config` | 读数字员工配置 |
| `PATCH` | `/api/v1/workforce/agents/{agent_key}/config` | 改提示词 / 模型 / 温度 / 技能白名单 / 记忆策略；仅 `super_admin` |

全部接口：未认证 `401`；越权 `403`；跨租户 `404`；只返回本租户数据；响应不含账号 PII。

**第一期不做的接口**：会话删除（物理）、会话分享、多员工协同、消息编辑重发。

---

## 10. 前端

> **状态**：本节描述**P1 已交付**的范围。P2 起的交互模型改造见 §17。

- 新增 `admin-web/src/features/conversation/`（`types.ts` / `api.ts` / `state.ts` / `ConversationPage.tsx` + 测试）；侧栏新增「对话」入口（`view: 'conversation'`，URL `?view=conversation`）。
- **首页改造**：现有 hero 的「快速建任务」输入卡改为**对话入口**（第一句话即创建会话），`执行人` 选择器即 `agent_key`。这是对 [`features/home`](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/home/HomePage.tsx) 的**替换**，不是新增。**同时保留「或直接建任务」次要入口**，避免 P1 期间丢掉唯一的建任务 UI 路径（建任务在后端接口仍在，但前端只有这一处入口）。
- **数字员工设置页**：在既有 `WorkforceSettingsPage` 的编辑态增加「配置」区（提示词 / 模型 / 温度 / 技能白名单 / 记忆策略 / 治理字段）。
- 四态齐备：加载 / 空 / 错误（含「重新尝试」）/ 无权限（`403` 显示明确文案）。
- **流式输出**：P1 用**非流式**（`POST /messages` 内联返回回复）——这是**刻意的**，因为 P1 的回复是确定性桩，没有流可推。流式见 §17（P2b）。

---

## 11. 迁移与兼容

| 项 | 处理 |
| --- | --- |
| 迁移编号 | `023_conversational_agent.sql` |
| 迁移清单 | 同步 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS`（事实 16，`tests/test_staging_assets.py` 守护） |
| 存量数据 | **不回填、不改写**。`workbench_digital_employees` 新增列全部有 `DEFAULT`，存量行自动获得空配置（= 用默认模型、无提示词、无工具） |
| 双实现 | 内存 + PostgreSQL 双实现（沿用既有 `_COLUMNS` / `_hydrate` / `_connection` 模式），memory 仅限 `development` |
| 回滚 | 新增表 + 新增列，回滚 = 停用入口 + 保留数据；**无需删列**（`ALTER ... ADD COLUMN` 可保留） |
| 破坏性变更 | 首页输入卡由「建任务」变「建会话」属**行为变更**，需在实现时同步更新既有 `App.test.tsx` 与 `HomePage.test.tsx` 的断言 |

---

## 12. 测试计划（先写失败测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 仓储 | 会话/消息的增删查、只列本租户、分页、`agent_key` 已停用时历史会话仍可读 |
| 接口 | `401` / `403`（非 `super_admin` 改配置）/ `404`（跨租户与改他人会话）/ 新建 `201` / 配置 `PATCH` 校验（非法 `model_key`、越界 `temperature`、白名单外工具一律 `422`） |
| **权限收敛（最重要）** | 对话入口与表单入口对同一动作的判定结果**必须一致**——构造「对话里试图做一件表单里不允许的事」，断言同样被拒 |
| 审批 | 写类工具在未批准时**不得执行**；批准后执行且写审计；审批被拒后会话状态正确 |
| 审计 | 新增动作写入成功；未在白名单的明细键被拒；`test_frontend_audit_labels.py` 覆盖新动作 |
| 前端 | 对话页四态、发消息、配置页编辑；首页第一句话创建会话 |
| 契约守护 | 全部新路由必须出现在 `docs/api-contract.md`（`tests/test_api_contract_coverage.py`） |
| **反假测试（必做）** | ① 去掉会话仓储的 `tenant_id` 过滤 → 跨租户用例必须变红；② 让对话入口绕过审批 → 「未批准不得执行」用例必须变红；③ 取消配置的 `model_key` 校验 → 非法模型用例必须变红 |

三类用例齐全：正常流程（**查库验证写入正确，不只看 200**）、临界值（空消息、超长提示词、温度边界 `0.00/2.00`、分页边界、同会话并发发消息）、异常与非法输入（跨租户、越权角色、白名单外工具、已停用员工）。

---

## 13. 开放问题 Q1–Q6（**已于 2026-09-12 全部答复**）

> 决议已合并进 §4（D1–D13）。本表仅保留「原问题 → 决议编号 → 结论摘要」的追溯关系，**不再作为待办**。
> ⚠️ **新的未决问题在 §17.7（Q7–Q10）**，与本节无关。

| # | 原问题 | 决议 | 结论摘要 |
| --- | --- | --- | --- |
| Q1 | 第一期 Harness 用真 dsh 还是先用 `MockRuntime`？ | **D7** | **先用 `MockRuntime`**，P2 再接 dsh |
| Q2 | `system_prompt` 的长度上限与提示注入防护 | **D11** | 上限 8000 字符 + 入库前扫描 + **禁止可改变权限判定的指令**（命中 `422`） |
| Q3 | 会话是否纳入既有「审批聚合」？ | **D9** | **不纳入**，不新增第五类 |
| Q4 | 长期记忆的 `pgvector` 维度与 embedding 模型 | **D12** | `023` 不建 `vector` 列也不建占位列；P3 在记忆表上一次性建列与索引，故 **embedding 模型只需在 P3 开工前定** |
| Q5 | CRM 与「数字员工」的关系 | **D10** | **独立模块**（独立领域对象 + 独立权限） |
| Q6 | 自进化的评测集从哪来 | **D13** | **用真实历史会话构建 golden set**；会话量起来前 P6 不具备开工条件 |

---

## 14. 分期路线与第一期落地清单

### 14.1 分期（每期独立评审）

| 期 | 内容 | 前置 |
| --- | --- | --- |
| **P0** | 本立项文档评审（**当前阶段**） | — |
| **P1** | 数字员工配置 + 对话层 + 首页改造。**Harness 用 `MockRuntime`，不执行任何真实工具**（D7） | P0 通过；无阻塞 |
| **P2a** | 接入 dsh：自定义工具（**含文件读写与命令，走 D8 路线 A**）+ 回调审批 + `restrict` 收窄工具集 + **隔离容器执行环境**。产出仍是**现有的非流式对话页** | P1 稳定；**dsh 契约必须在运行时复验**（本轮只做静态勘察）；**隔离容器就绪**（D8 ②） |
| **P2b** | **实时流 + 过程事件**（D15 / D16）：SSE 推流契约 + PG 流帧存储与断线续播；工具调用 / 模型响应 / 文件改动 / 计划变更作为可订阅过程事件 | P2a 稳定；**必须先有真实 agent 调用可流可追**（否则是空壳） |
| **P2c** | **前端交互模型改造**（D14）：对话主轴 + 右侧舞台 + 侧栏信息架构重组；消费 P2b 的流与过程事件 | P2b 契约冻结；**不照抄任何外部产品界面**（许可与外观版权约束，只借信息架构与交互模式） |
| **P3** | 记忆层（短期 → 长期）+ 个人知识库接上 pgvector（含 `vector` 列 `ALTER` 与索引） | P2a；**embedding 模型需在 P3 开工前定**（D12） |
| **P4** | 技能层（`SKILL.md` + 注册表 + MCP 客户端 + 白名单审计）+ 沙箱加固 | P3 |
| **P5** | CRM 模块（客户/联系人/商机/跟进 + 规则分 + LLM 解读与跟进计划） | 可与 P3/P4 并行；Q5 答复 |
| **P6** | 自进化闭环（**FlowEvo 范式** + SkillOpt 门禁 + Langfuse 灰度回滚，三方分工见下） | **必须最后**；Q6 答复 |

**P6 的三方分工（依据 §2.4 调研结论，取代初稿的单一 SkillOpt 方案）**

| 层 | 采用 | 职责 | 许可 |
| --- | --- | --- | --- |
| **技能沉淀** | **FlowEvo 范式** | 成功 workflow → 编译成可执行技能 → 持久技能库 → 追踪每个技能的下游收益 → **抑制负迁移** | Apache-2.0，可商用（论文配套代码，需自写工程外壳） |
| **准入闸门** | **Microsoft SkillOpt 范式** | `rollout → reflect → 受限编辑（有编辑预算）→ held-out 验证集严格提升才接受 → 导出` | MIT |
| **灰度与回滚** | **Langfuse labels 范式** | 版本 → 校验 → 门禁 → 灰度 → 观测 → 回滚（**改指针，不原地覆盖**） | MIT core |

**接缝（本方案独有，两个开源件都不提供）**：FlowEvo 的 `admission`（技能准入）环节**插我们既有的人工审批**——「数字员工想固化一条新技能时，人审一次」。**生成者 ≠ 评审者**（有实证 LLM 自评准确率仅 46.4%），这条是硬约束。

### 14.2 第一期落地清单（评审通过后才动手）

1. `migrations/023_conversational_agent.sql` + `.env.staging.example` 清单登记。
2. `app/conversation/`（新模块：模型 + 内存仓储 + PG 仓储 + 服务层；权限在仓储层与接口层各拦一次）。
3. `app/workforce/`：数字员工配置字段的模型、仓储与读写闸门（**只允许 `super_admin`**）。
4. `app/main.py`：§9 的 8 个路由；`app/audit/models.py` 扩动作与明细键（事实 15）。
5. **权限收敛**：把「对话入口」与「表单入口」对同一动作的判定收敛到**同一个 service 函数**（§8 约束 3）。
6. 前端 `features/conversation/`；**改造 `features/home/`** 的输入卡为对话入口；`WorkforceSettingsPage` 增配置区。
7. `docs/api-contract.md` 新章节；`docs/architecture.md` 同步七条线的状态。
8. 全量回归（`pytest` + `compileall` + 两端 vitest/build + 桌面 `node --test`）+ CI 实跑。

---

## 15. 已知风险（如实登记）

1. **dsh 是 RC，且一个月 22 个版本、已有三代会话格式迁移包**。它必须被隔离在适配器之后；**任何 dsh 类型都不得出现在本项目的领域模型里**。
2. **dsh 的沙箱在 Windows 只报 partial，且只约束写**。**不得**把它当安全边界；我们的自定义工具必须自己做参数校验与归属校验。
3. **`SKILL.md` 生态是攻击面**（已有开源项目因此发生技能包投毒事件）。技能必须走来源白名单 + 审核，**不允许用户自传技能包直接生效**。
4. **成本会失控**：多轮对话 + 记忆抽取 + 自进化评测三层叠加。必须有三级熔断（会话 / 员工 / 每日），且**默认拒绝而非降级**。
5. **取证边界**：本轮 dsh 验证是**静态勘察**（读 `.d.ts` / `lib` / README），**未起服务、未接模型、未运行**。§2.3 中 3 处标注为「推断」的结论需在 P2 用运行时复验。
6. **知识库清单仍写死在前端**（前序文档已登记的缺口），本立项不解决。
7. **本文件不构成任何实现完成的声明**：全部七条线**均未开始编码**；`d:\徐徐AI学习\_dsh-verify\` 是**仓库之外**的一次性验证目录（已用 `git` 确认 outside repository），可随时删除。
8. **「自进化」这个词对外要收住**。可交付的只有 §14.1 P6 那套**工程闸门**；不得对外宣称「自主进化」。且 §13 Q6 未答复前，**P6 不具备开工条件**（缺 golden set）。
9. **🔴 D8（允许文件与命令）是本立项风险最高的一条决策**，必须完整理解它的代价：
   - dsh 官方**自述未接受安全审计**；其 Windows 沙箱为 `partial`，**只约束写，不约束读 / 网络 / 进程可见性**——`read .env`、内网访问、跨进程可见性**都不在沙箱约束内**；
   - 跨进程审批**不可用**（§2.3 Q1），因此**唯一的拦截手段是 D8 路线 A**（文件/命令由我们自己实现成 dsh 工具）。**路线 A 未实现之前，这两项能力不得开启**——这是 P2 的硬门禁，不是建议；
   - 因此 P2 的开工前置在原本「dsh 运行时复验」之上**再加一条：隔离容器就绪**。
10. **P1 不执行任何真实工具**（D7 是 `MockRuntime`），所以**切勿把「P1 已完成」理解成「文件与命令已可用」**——该能力 P2 才生效。
11. **已登记缺口：创建会话时不校验 `agent_key` 是否在目录里存在且启用**（2026-09-12 P1a 实现时确认）。理由：§7.1 已定「`agent_key` 刻意不加外键」，加校验属规格未要求的行为变更；且 P1 无真实执行，typo 的后果要 P2 才显现。**收口时机 = P2**（`agent_key` 开始路由到真实执行时），届时按知识范围写路径闸门的同一口径收紧（复用 `ensure_agent_binding_available`），并保留「已停用员工的历史会话仍可读」。
12. **已登记限制：mock 模式下任何非空 `model_key` 都会 `422`**。因为 `ModelGateway` 仅在 `planner_backend=openai_compatible` 时注册模型，默认 mock 模式注册集合为空 → 校验 fail-closed。**这是正确行为**，但意味着本地开发无法配置模型键，需先配好模型后端。

---

## 16. 迁移 023 真实 PostgreSQL 回归（2026-09-12，本机一次性容器）

> **环境**：Docker `pgvector/pgvector:pg16`（PostgreSQL 16.15），端口 55434，容器 `workbench-pg-023`，**跑完即删**。
> **这不是 staging**：无独立主机 / TLS / 独立密钥 / 回滚演练，仅用于消除「PG 仓储只用假连接断言」这一缺口。

### 16.1 迁移链与结构声明

| # | 检查 | 结果 |
| --- | --- | --- |
| 1 | 从零应用迁移 | **23 条**，`001_initial` → `023_conversational_agent`；`vector` 扩展 0.8.6 由 001 装好 |
| 2 | 幂等性 | 重复执行新应用 **0** 条，记录表 23 条 |
| 3 | 会话表主键 | `PRIMARY KEY (tenant_id, conversation_id)` |
| 4 | 消息表主键 | `PRIMARY KEY (tenant_id, message_id)` |
| 5 | 消息表外键 | `FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(...)` |
| 6 | 消息表是否有 `updated_at` | **无**（append-only 成立） |
| 7 | 会话表是否加外键指向数字员工 | **无**（符合「停用不删除、历史可解析」） |
| 8 | 新增列 | **9 列**全部 `NOT NULL` 且带默认值，类型正确（`numeric(3,2)` / `jsonb` / `integer` / `bigint`） |
| 9 | **D12 是否被违反** | **全库 `vector` 列 = 0**；名为 `embedding_meta` 的列 = 0 |
| 10 | 存量行默认值 | 只写原列后读新列 = `('', '', 0.20, [], {}, 'approval_for_risky', 'high', 60, 0)`，全部符合预期 |

### 16.2 约束真的拦人（负向测试）

每条插入都补齐了合法字段，**唯一可能的违规点就是被断言的那条约束**：

| 用例 | 结果 |
| --- | --- |
| 会话 `status` 非法值 | `CheckViolation` |
| 消息 `role` 非法值 | `CheckViolation` |
| 消息指向不存在的会话 | `ForeignKeyViolation` |
| **消息跨租户引用他租户会话** | **`ForeignKeyViolation`** ← 复合外键在**数据库层**强制租户隔离 |
| 数字员工 `autonomy_level` / `risk_threshold` 非法 | `CheckViolation` |
| 审批超时越界（1 分钟） | `CheckViolation` |
| 每日预算负数 | `CheckViolation` |
| 数字员工指向不存在岗位 | `ForeignKeyViolation` |

### 16.3 本次回归查出并修复的缺陷（1 处）

**`temperature` 缺 CHECK 约束**。规格 §7.2 明确要求 `0.00–2.00` 的 `CHECK`，但实现漏了；而 `NUMERIC(3,2)` 只把范围限到 ±9.99，**实测 9.99 与 -1.00 都能写入**（数据库层未拦）。

已修复：在 `023` 给该列补 `CHECK (temperature >= 0.00 AND temperature <= 2.00)`，作为应用层校验之外的**第二道防线**（防绕过接口的直接 SQL 写入）。修复后在同一容器重建并复验：`0.00` / `2.00` 允许，`2.01` / `9.99` / `-1.00` 均 `CheckViolation`。

> 因该迁移此前**从未在任何真实库执行过**，直接改 `023` 是安全的（无需新增 `024`）。若已有库执行过 023，则必须另开 `024` 补约束。

### 16.4 应用层对真实 PG 的端到端验证

以 `WORKBENCH_STORAGE_BACKEND=postgres` + 真实 DSN 起 `TestClient`：

| # | 用例 | 结果 |
| --- | --- | --- |
| 1 | 创建会话 | `201` |
| 2 | 发消息 | `201`，`stub = true`（**桩回复显式标注**，未伪装成真实模型） |
| 3 | 会话列表 | `200`，`total = 1` |
| 4 | 会话详情 | `200`，消息 2 条 |
| 5 | 跨租户读会话 | **`404`**（未探测存在性） |
| 6 | 改他人会话 | **`404`** |
| 7 | 归档 | `200` |
| 8 | 提示注入提示词 | `422`，中文原因正确 |
| 9 | 温度越界（应用层） | `422` |
| 10 | 跨租户读员工配置 | `404`（配置路由同样有租户隔离） |
| 11 | 非超管改配置 | `403` |

**查库核对**（宪法要求：正常流程必须查库，不只看 200）：会话行状态为 `archived`；消息表 2 行（`user` + `assistant` 桩回复）；审计 6 行 = `conversation.created` / `conversation.message.sent` ×2 / `conversation.archived` / **`workforce.agent.config.rejected` ×2（被拒也写审计）**。

**隐私核对**：审计 `detail` 仅含标识、角色、状态与拒绝原因 —— **不含消息正文、不含提示词正文、不含桩回复文本**。

### 16.5 本次回归仍未覆盖

- **staging / 生产未验收**（无独立主机、TLS、独立密钥、回滚演练）
- **同会话并发发消息**未测
- **浏览器人工闭环**未做
- 测试脚本退出时 `psycopg_pool.ConnectionPool.__del__` 报 `PythonFinalizationError`，属**测试驱动未关闭连接池**的产物，非应用缺陷（应用由 FastAPI lifespan 管理连接池）。

---

## 17. 目标交互模型与所需契约（P2b / P2c 的设计依据）

> **本节是 D14–D16 的展开**，也是「为什么 P2 必须拆成三段」的依据。
> **触发**：2026-09-12 用户判定现形态「更像管理后台，不像工作台，交互体验不如参照产品」。

### 17.1 差距拆解：一半是界面，一半是后端还没有真东西

**这个区分是本节最重要的一条**——如果混在一起，就会照抄出一堆空壳界面（违反「做不到的功能不上界面」）。

| 维度 | 我们现状 | 目标 | 差距性质 |
| --- | --- | --- | --- |
| 主轴 | 11 个**平级页面**，对话只是其中之一 | **对话是主轴**，其他能力围绕对话展开 | 界面 |
| 产出呈现 | 整页导航，看不到「边聊边出产物」 | **右侧舞台**：与对话并排的 DAG / 文件 diff / 终端 | 界面 |
| 实时性 | **全部轮询**，无一处流式 | SSE 流式输出 + 断线续播 | **后端契约**（P2b） |
| 过程可见 | 只有「运行详情」一页的静态概览 | agent 的**工具调用 / 模型响应 / 文件改动 / 计划变更**可追 | **后端契约**（P2b） |
| 任务层级 | 任务 / 提案 / 运行是平级概念 | 项目 → 任务 → 子任务的层级 + DAG | 界面（数据模型已有 `parent` 概念，未做成层级视图） |

**关键约束**：表格中「后端契约」两行**必须先做**（P2b），否则 P2c 的右侧舞台与过程面板没有数据可承载。所以顺序是 **P2a（功能）→ P2b（契约）→ P2c（界面）**，不可颠倒。

### 17.2 目标信息架构（P2c）

侧栏由 11 个平级入口重组为**分组**（现有页面不删，只是归档与合并入口）：

| 分组 | 入口 |
| --- | --- |
| **对话** | 对话（主轴，默认视图） |
| **任务与项目** | 任务中心、内容工作台、历史草稿、协同动态 |
| **员工** | 员工与岗位、数字员工设置、数字员工工作看板（P5 起） |
| **资产** | 记忆与画像、技能与工具（P3/P4 起） |
| **知识** | 知识权限管理、知识库 |
| **治理** | 安全与审计、审批待办、用量与费用、通知 |

> 分组名与归属是**提案**，须在 P2c 开工前评审；不在本阶段冻结。

### 17.3 右侧舞台的构成（P2c）

与对话并排，按当前上下文切换内容，**只放真实数据**：

| 面板 | 数据来源 | 可用阶段 |
| --- | --- | --- |
| 计划 / 子任务 DAG | P2a 产出的计划与子任务 | P2c |
| 工具调用流水 | P2b 的过程事件 | P2c |
| 文件改动 diff | P2b 的过程事件（文件类） | P2c |
| 终端输出 | P2a 的隔离容器执行输出（经 P2b 流式） | P2c |
| 审批与人工闸门 | 既有审批聚合 | P2c |

**禁止**：在对应能力尚未落地时提前放一个空面板占位。面板按可用阶段**逐个出现**。

### 17.4 实时流契约（D15，P2b）

- **接口形态**：`GET /api/v1/conversations/{conversation_id}/stream`，SSE；认证与租户校验同其他接口（未认证 `401`，跨租户 `404`）。
- **帧模型**（新增表，迁移号在 P2b 开工时定）：
  `(tenant_id, conversation_id, run_id, seq, kind, payload, is_terminal)`，主键 `(tenant_id, conversation_id, run_id, seq)`。
- **写入顺序**：**先落库、再推送**。这样断线可补，也保证「刷新不丢流」。
- **断线续播**：客户端带 `Last-Event-ID`（或 `?after_seq=`），服务端从 `seq+1` 补发；`is_terminal` 为真表示本轮结束。
- **与既有 `POST /messages` 的关系**：P1 的契约是**内联返回回复**，且已被 PWA / 桌面端依赖，**不得直接破坏**。三条候选（P2b 开工前必须择一）：
  1. 新增 `POST /messages:stream`，保留旧契约（**推荐**，零破坏）
  2. 旧接口增加 `?stream=true` 参数，默认行为不变
  3. 旧契约改为返回 `run_id`，回复一律走 SSE（破坏性变更，需同步改两个客户端）

### 17.5 过程事件契约（D16，P2b）

- **复用既有事件类型**：项目已有 `RuntimeEventType` 十种（`plan.created` / `step.started` / `tool.call` / `tool.result` / `approval.requested` / `approval.decided` / `checkpoint.saved` / `run.paused` / `run.failed` / `run.completed`）。过程事件**在此之上扩展**，不另起一套枚举。
- **与审计的区别（必须守住）**：
  | | 审计（既有） | 过程事件（新增） |
  | --- | --- | --- |
  | 回答的问题 | **谁改了什么** | **agent 在做什么** |
  | 存储 | `workbench_audit_log` | 新的运行事件表 |
  | 明细 | **严格白名单**（`ALLOWED_DETAIL_KEYS`），未声明键直接拒绝 | 可含工具参数与输出摘要 |
  | 可清空 | **不可**（只有 INSERT/SELECT） | 可按保留策略清理 |
- **🔴 脱敏是硬要求**：过程事件可能携带**工具参数、文件路径、文件内容**。必须在写入前过既有 `redact_payload`（`app/runtime/contracts.py`），并且**默认只落摘要不落原文**；需要原文的场景必须单独评审。跨租户隔离与审计同口径。
- **订阅**：复用 P2b 的 SSE 通道（同一 `run_id` 的帧里携带过程事件），不另开传输。

### 17.6 借鉴边界（法律与工程双重约束）

参照产品（`EvovexAI/EvoFlow`）的公开树是 **PolyForm Noncommercial（源码可见、非开源）**，且界面外观本身受版权保护。因此：

- ✅ **可以**：借鉴信息架构、交互模式、字段设计、工程取舍；阅读其源码以理解设计意图
- ❌ **不可以**：复制其代码、逐像素复刻其界面、二次分发
- 本项目的 `docs/superpowers/specs/` 只记录**设计结论**，不引入任何其源码或截图

### 17.7 本节未决问题（Q7/Q8/Q10 须在 **P2b** 开工前答复；**Q9 会倒逼 P2a 的工具设计**，须在 P2a 开工前答复）

| # | 问题 | 拦谁的开工 | 影响 |
| --- | --- | --- | --- |
| Q7 | §17.4 的三条候选选哪一条？ | P2b | 决定是否破坏 PWA / 桌面端既有契约 |
| Q8 | 过程事件的保留期与清理策略 | P2b | 决定新建表的保留字段与后台任务 |
| Q9 | 过程事件是否允许落文件内容原文 | **P2a** | **安全关键**；默认结论是「不落原文，只落摘要 + 哈希」。P2a 在实现文件/命令工具时就要按这个口径决定回传什么 |
| Q10 | §17.2 的分组与归属是否采纳 | P2c | P2c 的信息架构基线 |
