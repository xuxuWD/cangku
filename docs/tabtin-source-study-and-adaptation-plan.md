# TabTin 只读研读与适配评估（专项）

> **状态**：**v1 · 2026-09-21**（研读结论已出，待裁决 2 项 + 待裁决 1 项工程口径）
> **性质**：**只读研读（第三种模式）**——按 [`architecture.md` §「外部集成的判据」](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L41-L53) 与 [`moat-boundaries.md`](file:///d:/徐徐AI学习/公司工作台/docs/moat-boundaries.md) 既有口径定性：
> **不搬代码、不接适配器、连接都不接**（理由见 §5）。本文件**只提炼设计**，不含任何对方源码、不含任何复用决定。
> **上游登记**：`decision-log.md` **D-047**（本轮）+ `feature-inventory.md` §3.4 候选能力 C4 / C5。
> **唯一权威仍然在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)；
> 接口口径 = [`api-contract.md`](file:///d:/徐徐AI学习/公司工作台/docs/api-contract.md)；功能清单 = [`feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)。
> **本文件不复制任何口径、不改任何口径**，只登记"对方有什么、我们有什么、差在哪、能不能学"。

## §0 证据等级图例（本文件的诚实标记，**不得省略**）

| 标记 | 含义 |
| --- | --- |
| ✅ | **本轮我方一手核实**（`gh api` / 仓库文件直读 / 本地 grep），可复现 |
| ◐ | **抓取或转述**（官网页面抓取、上游文档自述），**未二次核实** |
| ○ | **未核实**（本轮未取得证据），**不得作为结论使用** |

## §1 调研来源与口径

| 来源 | 取法 | 说明 |
| --- | --- | --- |
| `www.tabtin.com`（含 `/pricing/`、`/app/`、`/skill/`、`/help/`、`/developer-support/`、`/privacy/`、招聘页） | ◐ 页面抓取 | `/about`、`/product`、`/features`、`/docs`、`/blog`、`/contact`、`/login` **全部 404** |
| `github.com/tabtin-ai/TabTin` | ✅ `gh api` + 目录/文件直读 | 仓库元数据、`requirements.txt`、根 `package.json`、根目录清单、后端 app 清单、code search |
| 我方仓库 | ✅ 本地直读 | 见 §4 各表右侧列的 `file:///` 链接 |

**调研边界（先说清，避免误读）**：**我方从未运行过 TabTin 产品**（无账号、无下载、无部署）。
本文所有"产品行为"结论均来自**公开文案与公开源码**，不来自实机行为。

## §2 事实一：TabTin 产品（对外）

| 项 | 事实 | 等级 |
| --- | --- | --- |
| 定位（逐字） | 「**让团队和 Agent 协作更优雅**」「TabTin 是一个**开源的人机 Agent 协作平台**」；README 首问：「**一个人已经完成的工作，能不能直接成为下一位同事的起点？**」 | ✅（README 直读） |
| 目标人群（逐字） | 「**深度使用 AI 的团队**是 TabTin 最初切入的人群，但不是产品边界」 | ✅ |
| 状态（逐字） | 「当前处于 **Public Preview（公开预览）** 阶段」；ROADMAP 自述边界：「不同组件的成熟度和跨端体验还不完全一致」「**Community Server 当前主要面向本机运行**」「**移动端不提供独立的 Agent 执行环境**」「Project 相关能力仍在建设中」「部分模块已有可用的默认实现，但**替换和扩展成本仍然较高**」 | ✅（ROADMAP 直读） |
| 官网自述功能 | 12 个应用（TabDoc / TabData / TabWeb / TabSlide / TabWhiteboard / TabMemo / TabFiles / TabTracker / TabMail / Terminal / TabDesktop / TabPhone）；48 个官方应用包 + 80 个 Skill；AI 分身（人设 / 技能 / 工具 / 记忆）；三档权限（请求权限 / 自动通过 / 全部允许）；Checkpoint 回退 + Checkpoint 审批；共享任务可 Fork | ◐ |
| 价格 | 公有云 **¥69/月起**（「之后的套餐与用量方案将另行公布」）；私有云 **¥29,999**（「限时三折」「一个月不满意全额退款」）；AGPL 开源版自托管 + **单独商业授权** | ◐ |
| 主体 | 上海摹范科技有限公司（信息来自官网隐私政策 / 招聘页；**未交叉验证工商公示**） | ◐ / ○ |
| 完成度判定 | **真产品 + 成长期落地页**（非空壳）：多语言营销站 + 帮助中心 + 开发文档 + 招聘页 + 可用下载入口（**下载按钮当前为禁用态**，"9.21 开放"） | ◐ |

## §3 事实二：TabTin 仓库（对工程）

### §3.1 元数据

| 项 | 值 | 等级 |
| --- | --- | --- |
| 全名 / 描述 | `tabtin-ai/TabTin` · "A workspace where people and multiple AI agents work together." | ✅ |
| **License** | **AGPL-3.0-only** | ✅ |
| 创建 / 最后 push | `2026-08-19` / `2026-08-31` | ✅ |
| star / fork / open issues | **417 / 97 / 3** | ✅ |
| 组织 | `tabtin-ai`（verified，Shanghai，blog=tabtin.com），**public_repos = 2**（TabTin、`.github`） | ✅ |
| 公开提交数 | **仅 7 条**（2026-08-22 ~ 08-29，作者 3 人）⇒ **历史被压缩为快照**，不代表真实开发节奏 | ✅ |
| Releases | `v1.1.2`（08-22）/ `v1.1.3`（08-31），自述"与线上产品 1.1.x 对齐"、"**tag 不触发生产部署**" | ◐ |
| CI | **无公开 workflows**（`.github` 下仅 ISSUE_TEMPLATE / PR 模板） | ✅ |

> **判读**：这是典型的 **Open Core 引流型开源**（可信性展示 + 社区版 + 商业授权入口），
> **不是社区共建型项目**。**star 数不得被读成"社区已验证"**。

### §3.2 技术栈（✅ 逐字取自 `requirements.txt` 与根 `package.json`）

| 层 | 上游 | 我方 |
| --- | --- | --- |
| Web 框架 | **Django 4.2.7 + django-ninja 1.5.3** | **FastAPI + pydantic-settings** |
| 异步/实时 | celery 5.3.4 + channels 4.3.2 + daphne + **Centrifugo v6 + Yjs(CRDT)** | celery + Redis + **自研 SSE + PG 流帧 + Outbox** |
| 存储 | PostgreSQL + **pgvector 0.2.4** + redis 5 + Elasticsearch + OSS | PostgreSQL + pgvector + Redis + 对象存储 |
| 模型接入 | **litellm + langchain-core** + openai/anthropic（BYOK） | 自研模型网关（`app/model_gateway/`） |
| 重依赖（服务端） | playwright、PyMuPDF、pdfplumber、python-pptx、python-docx、**paramiko（SSH 远程执行）**、boto3、google-api-python-client、`python-alipay-sdk`、`wechatpayv3`、oss2、nh3/bleach/defusedxml、pandas/numpy | pypdf、psycopg3、httpx、cryptography、docker（**直接依赖共 13 条**） |
| 前端 | pnpm monorepo：`apps/*` 8 个（django / electron / web / admindash / collab-live / daemon / android / ios）+ `packages/*` 80+ | 三个独立端：`workbench-web` / `admin-web` / `companion-pwa` + `desktop` |

**判读**：我方后端**直接依赖 13 条**是真实的**供应链与攻击面优势**，**不可为对齐功能而放弃**。

### §3.3 后端模块（✅ 目录直列：36 个 Django app）

`agent` / `agent_memory` / **`rag`** / `skills` / `chat` / `collab` / `credential_vault` / `tins` / `channel_gateway` /
`integrations_feishu` / `integrations_github` / `services`（agent_engine） / `analytics` / `fts` / `user_portrait` /
`platform_config` / `login_relay` / `maintenance` / `updater` / `diagnostics` / `client_errors` /
`tabdoc` / `tabdata` / `tabslide` / `tabmemo` / `tabsite` / `tabcode` / `tabchat` / `tracker` / `tabtinspace`

### §3.4 一处必须纠正的误判：**它不做 SaaS 多租户**（✅ code search 一手核实）

调研过程中出现过"TabTin 也做 schema 隔离 / 与我方同思路"的转述。**本轮一手核实后否定**：

- `search_path` 命中 11 处，主要集中在 `tabtin/settings*` 与 `tabdata`（**用户自定义数据库连接**），**不是租户路由**；
- `tenant` 命中 59 处，但 **`tenant_id` 仅 3 处**，且全是 **飞书 / MS Teams 等外部平台的 tenant key**（`integrations_feishu/*`、`channel_gateway/adapters/*`）；
- `.env.example` 为 `TABTIN_DATABASE_MODE=single_pg` / `PG_DB_NAME=tabtin_single`，配 `edition.py` / `community_database.py` 做版本与库分层。

⇒ **它的隔离单位是"一次部署 = 一个客户"**，商业化靠**私有化部署 + 商业授权**，**不是 SaaS 多租户底座**。
**这与我方 schema-per-tenant（51 表 / 53 索引 / 98 约束 / 2 序列模板 + `SET LOCAL search_path`）不是同一件事**，
不得写成"同思路"（见 `docs/contracts/schema-per-tenant-plan.md`）。

## §4 与我们的项目对照（十维度）

图例：**对方强** / **我方强** / **同向** / **不可比**

| 维度 | 我方（证据） | TabTin | 判读 |
| --- | --- | --- | --- |
| **多租户** | schema 级隔离、服务端注入租户上下文、租户名白名单、4 表留平台 schema（[schema-per-tenant-plan.md](file:///d:/徐徐AI学习/公司工作台/docs/contracts/schema-per-tenant-plan.md)） | 单库、一客一部署（§3.4） | **我方强**（不可比） |
| **权限模型** | RBAC+ABAC 三层；数字员工 = **创建者 ∩ 使用者 ∩ 岗位能力包**，禁止放大（[permission-matrix.md](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)） | 三档工具批准策略（请求权限 / 自动通过 / 全部允许） | **我方强**：对方是**策略开关**，不是**权限代数** |
| **执行闸门** | 九步闸门；`critical` 需审批；**审批通过后必须从第①步重跑全套闸门**；容器负向隔离（`--network none`、只读根、非 root） | 运行沙箱 + Checkpoint 回退 + 三档允许 | **同向**；我方"审批后重跑"更严；对方 **Checkpoint 回退**是我方缺的执行级原语 |
| **审计** | 审计查询 + 导出（`audit.exported` 留痕、仅超管、超限 `422` 不静默截断）（[audit-log-api.md](file:///d:/徐徐AI学习/公司工作台/docs/contracts/audit-log-api.md)） | `credential_vault` / `relay_audit_writer` / OTel / Sentry；**未见等价对外审计契约** | **我方强（契约化）** |
| **知识库 / RAG** | pgvector + 知识策略守卫（**fail-closed**：无绑定 ⇒ 空结果 + 审计）+ 检索前过滤 + 绑定治理台 + ACL（[knowledge-acl.md](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-acl.md)） | `apps/rag`（pgvector + `db_router.py`）+ Elasticsearch + `fts`；自述"Skill 对接第三方知识库" | **同向**；我方治理面完整，对方检索面更宽（ES 混合检索） |
| **Agent 运行时** | 自研 `AgentRuntimeAdapter` + **多适配器共存规约**（dsh / DeerFlow / Codex / Hermes 全部**适配器，不搬码**）（[multi-adapter-coexistence-spec.md](file:///d:/徐徐AI学习/公司工作台/docs/multi-adapter-coexistence-spec.md)） | 自研 Agent Runtime + 子 Agent + 记忆 + Skill + 编排；ROADMAP 把"**建立可插拔扩展体系**（配置选择 / Adapter 接口 / 用户管理员可安装启用）"列为**下一阶段重点** | **同向且我方领先**：对方当前"替换与扩展成本仍然较高"（自述），**我方已是对方的目标形态** |
| **实时协作** | 自研 SSE + PG 流帧 + Outbox（**无 CRDT**） | **Centrifugo v6 + Yjs CRDT**（多人同编文档 / 表格） | **对方强**；但引入 CRDT 属地基级改动，不得顺手加 |
| **客户端矩阵** | `workbench-web`（管理台）+ `admin-web` + `companion-pwa`（**只做登录 / 待办 / 审批**，轮询非 Push）+ `desktop`（Electron 安全壳） | Electron 桌面（**执行环境**）+ Web + iOS / Android / 鸿蒙 + `tabtin-daemon` | **同向 + 反向验证**：对方 ROADMAP 自述「**移动端不提供独立的 Agent 执行环境**」**与我方 PWA 取舍完全一致** |
| **产品面 / 办公应用** | 对话 + 舞台 + 产物面板 + CRM P5a + 知识治理 + 技能 / MCP + 审计 + 自进化 P6a；**无办公套件** | 12 应用 + 48 应用包 + 80 Skill + 帮助中心 + 开发文档 21 条 Prompt | **对方强**（工作面覆盖是他们押的方向） |
| **工程纪律 / 可追溯** | 契约先行（`api-contract.md` 唯一真源）+ 44 迁移 + 224 个测试文件 + 124 篇 docs + D 编号决策台账 + 五问汇报 + "未验证"标注 + [ci.yml](file:///d:/徐徐AI学习/公司工作台/.github/workflows/ci.yml)（含真连库 / 真容器两个 job，运行 run 已记录） | `contracts/`(openapi/asyncapi) + pytest 用例（文件名带需求号）+ biome/eslint + `lint-baseline.json` + `.gitleaks.toml` + SECURITY / CONTRIBUTING / CODE_OF_CONDUCT / ROADMAP / THIRD_PARTY_NOTICES；**但无公开 CI** | **两种纪律互补**：我方"契约 + 门禁 + 台账"**强于**对方公开部分；对方"**开源卫生 + 密钥扫描**"是我方缺口（见 §6 B 档） |

## §5 许可证红线判定（决定性，**不得绕过**）

**事实**：License = **AGPL-3.0-only**；README 明确"可向 Shanghai Mofan Technology Co., Ltd. **咨询单独商业授权**"。

按 [`architecture.md`](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L41-L53) 的三条路径逐条判定：

| 路径 | 判定 | 理由 |
| --- | --- | --- |
| ① **搬代码**（fork / vendor / copy） | **绝对禁止** | AGPL 是强传染许可；我方是**营利业务系统**（多租户 SaaS + 私有化交付），源码进入本仓库即触发向使用者提供对应源码的义务 ⇒ **违约**。无讨论空间 |
| ② **接适配器**（独立进程 + HTTP 边界） | **同样不做** | 理由**不在许可，在我方硬约束**：[architecture.md L51](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L51) 明文「把**用户本机 CLI 当引擎 / 单机单用户**形态的 harness 搬进来，会带进**第二套用户、权限与审计**」——**TabTin 正是该形态**（桌面端为执行环境 + 自建账号 / 权限 / 协作体系）。**命中既有的"一类明确不可搬"** |
| ③ **只读研读**（连接都不接） | **✅ 本条路径** | 只读源码、提炼设计、**自己实现**（思想与架构不受版权保护，源码才受）。与 EvoFlow / OpenWorkBuddy 的既有处置同口径 |

**结论一句话**：**TabTin 是一个值得反复只读研读的设计参照物，不是一个可集成的依赖。**
若将来确实要把它的能力对外售卖，**正解是走商业授权**，**不是研究怎么绕 AGPL**。

## §6 可借鉴清单（三档，均止于"登记 / 参考"）

### A 档 —— 可借鉴的设计思想（只读研读 → **自研**；已登记为候选能力）

| # | 借鉴点 | 对方做法 | 我方现状 | 障碍（为什么不能顺手加） |
| --- | --- | --- | --- | --- |
| **C4** | **任务交接 / 接手** | 交接**冻结必要的对话上下文**，并带上"任务中引用**且有权共享**的文档"；核心命题 = "已完成的工作成为下一位同事的起点" | P2c-6 会话协作已有成员表（`read`/`write`）+ **发言者本人身份执行**；**但没有显式的"交接 / 接手"动作与语义** | 属**范围变更**：需先定"交接什么（上下文 / 产物 / 证据）/ 权限如何收敛（沿用成员表两档？）/ 交接后原发起人是否失权"；须单独立项评审 |
| **C5** | **Checkpoint 回退 + 回退审批** | 执行级检查点，回退需审批 | 有产物版本、证据引用、运行重做（P2c-4）；**无"回退到某检查点"原语** | 属**运行域契约扩展**（先改 `api-contract.md` 再写码）；且须回答"回退是否等于新一次运行 / 是否重跑闸门 / 与新迁移的关系" |

### B 档 —— 可低成本补齐的开源卫生（对方有、我方缺）

| 项 | 用途 | 我方现状（2026-09-21 勘察） |
| --- | --- | --- |
| `SECURITY.md` | 漏洞披露渠道与边界 | **缺** |
| `CONTRIBUTING.md` | 协作与提交规范 | **缺** |
| `CODE_OF_CONDUCT.md` | 行为准则 | **缺** |
| `ROADMAP.md` | 方向与边界声明 | **缺**（我方路线图散在 `feature-inventory.md` / 各规格） |
| `.gitleaks.toml` | **密钥扫描基线** | **缺**（与宪法「密钥不进代码与仓库」直接相关） |
| `lint-baseline.json` | 渐进式 lint 收口 | **缺，且此刻不可落地**：全仓**无任何 linter 配置**（无 eslint / 无 `[tool.ruff]`，`ci.yml` 也不跑 lint）⇒ **没有可基线化的对象**，**照抄空壳属造假**。需先裁决"是否引入 linter"（新增依赖，属**依赖新增决策**） |

### C 档 —— **明确不可动**（写清理由，防"顺手抄"）

| # | 不可动项 | 理由 |
| --- | --- | --- |
| 1 | **单库单租户部署** | 我方多租户是**硬约束**（ADR-0002），不可降级 |
| 2 | **Centrifugo + Yjs CRDT** | 引入第二套实时基础设施与协同编辑数据模型，属**地基级**（须专项评审）；我方 SSE + Outbox 已交付且够用 |
| 3 | **并发铺开办公套件** | 与我方"**第一期只验证一个完整闭环**"的边界直接冲突 |
| 4 | **服务端依赖膨胀** | playwright / paramiko / boto3 / google-api / alipay / wechatpay / oss2 / ES / litellm —— 我方**直接依赖 13 条**是真实优势，不可为对齐功能而放弃 |
| 5 | **桌面端当 Agent 执行引擎** | 命中 [architecture.md L51](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L51) 硬约束（带进第二套用户 / 权限 / 审计） |
| 6 | **任何形式的代码复用** | §5 许可红线 |

## §7 待裁决项（**未动手，等裁决**）

| # | 待裁决 | 背景 | 建议 |
| --- | --- | --- | --- |
| **Q1** | **C4「任务交接 / 接手」是否立项** | §6 A 档；与我方成员表两档天然契合，价值高 | 建议**先只登记**（`feature-inventory.md` §3.4），待有真实业务诉求再立项 |
| **Q2** | **C5「Checkpoint 回退 + 回退审批」是否立项** | §6 A 档；涉运行域契约扩展 | 同上，**先登记**；立项前须先答"回退是否等于新一次运行 / 是否重跑闸门" |
| **Q3** | **是否引入 linter（Python ruff / 前端 eslint）** | §6 B 档末条：无 linter ⇒ `lint-baseline.json` 无从落地 | 属**依赖新增**，须你裁决；倾向"**先不引**，等有明确动机再单独立一轮" |

## §8 未核实清单（**不得读成已验**）

| # | 未核实项 | 原因 |
| --- | --- | --- |
| 1 | 官网 `/about` `/product` `/features` `/docs` `/blog` `/contact` `/login` 内容 | 站内**无这些路由**（均 404），帮助中心 / 开发文档替代 docs 角色 |
| 2 | **公有云是否可自助注册试用** | **未找到注册 / 登录页**（404）、下载按钮为**禁用态**（"9.21 开放"） |
| 3 | 真实定价档位与用量细则 | 官网写"另行公布" |
| 4 | 用户规模、营收、融资细节 | 仅招聘页标"天使轮"，**未交叉验证工商公示** |
| 5 | 上游产品**实际行为** | **我方从未运行 TabTin**（无账号、无下载、无部署）⇒ 一切产品结论仅来自公开文案与源码 |
| 6 | 仓库 CI / 生产部署 / 完整 git 历史 | 未公开；公开的 7 条提交**不代表真实节奏** |
| 7 | 官网自述的"48 应用包 / 80 Skill / 12 应用" | **未逐条核对** |
| 8 | 97 个 fork 的归属与内容 | 未核实 |

## §9 变更留痕

- **2026-09-21（v1，本轮）**：新建。起因 = 用户指令「深度调研 www.tabtin.com + github.com/tabtin-ai/TabTin，再对照我们的项目做深度分析」。
  产出：本文件 + `feature-inventory.md` §3.4 登记 **C4 / C5** + `decision-log.md` **D-047** + 六项开源卫生（**五项落地 / 一项待裁决**，见 §6 B 档）。
  **本轮零产品代码改动、零后端接口改动、零契约口径改动。**
- **血缘声明**：本仓库 `grep` **零处**命中 `tabtin` / `TabTin` / `摹范` / `Mofan` / `larchiveai`
  ⇒ **我方与 TabTin 无任何代码或文档血缘**，本文件是**纯外部参照**记录。