# TabTin 只读研读与适配评估（专项）

> **状态**：**v2 · 2026-09-21**（**前提变更已重写 §5**；待裁决 **Q1–Q5**；本轮主交付 = 新增 **§10 能力域研读提纲**）
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

> **⚠️ v2 修订声明（2026-09-21，用户口径变更）**：v1 的判定建立在「我方是**营利业务系统**」这一前提上。
> 用户现已明确「**目前不做商用、仅内部使用；商用以后再说**」⇒ **前提变了，推理链必须重写，不得沿用 v1 结论**。
> 同时 v1 把**许可**与**架构**两件事混在一格里判，v2 把它们**分开**——因为二者的可变性完全不同。

**事实**：License = **AGPL-3.0-only**；README 明确"可向 Shanghai Mofan Technology Co., Ltd. **咨询单独商业授权**"（Open Core 双许可形态；提交史 `b033ade release: publish LAN community packaging from opensource/v1` 印证存在"社区版打包"）。

### §5.1 第一层：许可（**会随"商不商用"改变**）

| 情形 | AGPL 义务 | 依据 |
| --- | --- | --- |
| **组织内部自用**（不对外分发、不向外部主体提供服务） | **一般不触发**源码提供义务 | GPL 系的判定核心是 **conveying（对外分发）**；组织内部使用通常**不构成**向公众分发 |
| **对外商用**（SaaS 给外部客户 / 私有化交付给客户） | **立即触发** §13 | 通过网络对外提供服务即须向使用者提供**完整对应源码** |
| **改造后"自研"**（无论内部或对外） | 衍生作品**整体**受 AGPL 约束 | 修改版本同样须提供源码 ⇒ **我方自有代码会被一并传染** |

⇒ **v1 写的"绝对禁止"在"纯内部自用"下不再自动成立**。但**三处风险不为零，必须一并说清**：

1. **主体边界**："员工 / 外包 / 多法人主体"是否构成 §13 意义上的"用户"，有**解释空间**，不是零风险。
2. **一个外部客户即触发**：只要有**一次**对外交付、外包驻场、或把系统给到法人外部，义务**瞬间**触发——而触发时点通常**不由我们决定**。
3. **债不可拆（本轮新增的决定性事实）**：仓库实测 **20,672 个文件 / 约 145 MB 源码**。这种体量混进我方底座后，**"到商用那天再剥离"在工程上不可行** ⇒ "以后商用再说"的真实含义是**把一份不可拆的债写进地基**，而不是"晚点再付钱"。

### §5.2 第二层：架构（**与商不商用无关，v1 的判定在这里仍然成立**）

- [architecture.md L51](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L51) 明文禁止「把**用户本机 CLI 当引擎 / 单机单用户**形态的 harness 搬进来，会带进**第二套用户、权限与审计**」——**TabTin 正是该形态**（桌面端为执行环境 + 自建账号 / 权限 / 协作体系）。
- ⇒ **即便许可允许，"接适配器 / 搬进底座"仍然不做**；这一条**不因"内部使用"而放宽**（它不是法律问题，是架构一致性问题）。
- ⚠️ **但用户已裁决启动重评审（见 §7 Q5）** ⇒ 上句是**当前口径**、**不是终局**。若重评审决定推翻 L51，必须**显式修改 `architecture.md`** 并留痕，**不得绕过它**。

### §5.3 三条路径的 v2 判定

| 路径 | v1 判定 | **v2 判定（本轮）** | 变更理由 |
| --- | --- | --- | --- |
| ① **搬代码**（fork / vendor / copy） | 绝对禁止 | **仍不做，但理由改写**：不是"许可无条件禁止"，而是①衍生作品整体传染（我方自有代码须开源）②2 万文件**债不可拆**③一次对外即触发 | 前提由"营利"改为"内部使用" ⇒ 许可理由从"绝对"降为"高风险 + 不可逆" |
| ② **接适配器**（独立进程 + HTTP 边界） | 同样不做 | **仍不做**（**理由未变**：`architecture.md L51` 架构硬约束） | 架构理由**与商用无关**，不随前提变更 |
| ③ **只读研读**（连接都不接） | ✅ 本条路径 | **✅ 仍然是本条路径**（用户 2026-09-21 裁决确认） | 唯一同时避开许可风险与架构冲突的路径 |

**结论（v2）**：**长期路径不变 = 只读研读、自研**；但**理由构成变了**：由 v1 的"许可绝对禁止"修正为「**许可高风险且不可逆 + 架构不允许 + 债不可拆**」。
若将来商用，正解仍是**商业授权**——**不是研究怎么绕 AGPL**。

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

### C 档 —— **默认不可动**（写清理由，防"顺手抄"；**第 1 / 5 条已启动重评审**）

| # | 不可动项 | 理由 |
| --- | --- | --- |
| 1 | **单库单租户部署** | ~~我方多租户是**硬约束**（ADR-0002），不可降级~~ ⇒ ⚠️ **用户 2026-09-21 裁决启动重评审（见 §7 Q4）**：本条由"明确不可动"**降级为"待评审"**；**评审结论出来前维持现状（不降级）**，本轮不改任何代码与契约 |
| 2 | **Centrifugo + Yjs CRDT** | 引入第二套实时基础设施与协同编辑数据模型，属**地基级**（须专项评审）；我方 SSE + Outbox 已交付且够用。⇒ **本轮未启动此项重评审**（用户两处裁决不含它）⇒ **仍为默认不可动**；但注意：「**文档 / 表格协同**」作为**能力域**我方是**空白**（见 §10 D2），**"能力要不要自研" ≠ "对方那套基础设施要不要搬"**，两者必须分开判 |
| 3 | **并发铺开办公套件** | 与我方"**第一期只验证一个完整闭环**"的边界直接冲突 |
| 4 | **服务端依赖膨胀** | playwright / paramiko / boto3 / google-api / alipay / wechatpay / oss2 / ES / litellm —— 我方**直接依赖 13 条**是真实优势，不可为对齐功能而放弃 |
| 5 | **桌面端当 Agent 执行引擎** | ⚠️ **用户 2026-09-21 裁决启动重评审（见 §7 Q5）**：本条由"明确不可动"**降级为"待评审"**；**原理由如实保留** = 命中 [architecture.md L51](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md#L51) 硬约束（带进第二套用户 / 权限 / 审计）。**若重评审决定采用，必须显式修改 `architecture.md` 并留痕，不得绕过** |
| 6 | **任何形式的代码复用** | §5 许可红线（v2 已把**理由构成**改写为「高风险且不可逆 + 债不可拆」，**结论不变**） |

## §7 待裁决项（**未动手，等裁决**）

| # | 待裁决 | 背景 | 建议 |
| --- | --- | --- | --- |
| **Q1** | **C4「任务交接 / 接手」是否立项** | §6 A 档；与我方成员表两档天然契合，价值高 | 建议**先只登记**（`feature-inventory.md` §3.4），待有真实业务诉求再立项 |
| **Q2** | **C5「Checkpoint 回退 + 回退审批」是否立项** | §6 A 档；涉运行域契约扩展 | 同上，**先登记**；立项前须先答"回退是否等于新一次运行 / 是否重跑闸门" |
| **Q3** | **是否引入 linter（Python ruff / 前端 eslint）** | §6 B 档末条：无 linter ⇒ `lint-baseline.json` 无从落地 | 属**依赖新增**，须你裁决；倾向"**先不引**，等有明确动机再单独立一轮" |
| **Q4** | **`single_pg`（一次部署 = 一个客户）取舍** | §3.4：对方是**一客一部署**；我方是 **schema-per-tenant**（ADR-0002，**44 迁移 + 51 表模板已建成**） | ⚠️ 属宪法「**地基不随手翻**」⇒ 本轮**只启动重评审**，**不改任何代码与契约**。评审须回答：①「内部使用」下**还需不需要多租户**②若不需要，**已建成的 44 迁移 / 51 表模板如何处置**（回退成本 vs 保留）③若保留，**是否只降级"默认形态"而不动隔离机制** |
| **Q5** | **桌面端作为 Agent 执行模型** | §5.2 / §6 C 档第 5 条：与 `architecture.md L51` **正面冲突**（会带进第二套用户 / 权限 / 审计） | ⚠️ 同上，**只启动重评审**。评审须回答：①桌面执行与**服务端容器九步闸门**是**替代**还是**并存**②若并存，**审计与审批闸门落在哪一侧**③若采用，须**显式修改 `architecture.md L51`** 并留痕（**不得绕过**） |

**Q1 / Q2 / Q3 的答复（2026-09-21，歧义已消解）**：此前一轮答复**同时勾选了"全部暂缓"与 Q1 / Q2 / Q3 三项**（**逻辑互斥**）。
按"**不静默取其一**"的纪律，本文件与 `decision-log.md` 暂按**保守口径**处理并请订正；**用户已于同日给出可执行口径 = 三项都暂缓**
⇒ **歧义消解**：**三项维持"只登记 + 待裁决"，本轮及 Q4 / Q5 出结论前均不推进任何一项**（不启动 C4 / C5 立项评审、不引入 linter）。
**复审时点 = §7 Q4 / Q5 出结论之后**——其中 **Q2 与 Q5 是硬耦合**（"回退是否重跑九步闸门"取决于执行模型落在服务端还是桌面）。

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
- **2026-09-21（v2，本轮）**：**前提变更触发的重写（不是增补）**。用户明确「**我们做出来目前也不是商用，只是用作工作内部使用。后面如果商用以后再说**」
  ⇒ v1「许可**绝对**禁止」的推理链**建立在"我方是营利业务系统"上，前提已变 ⇒ 必须重写**：
  **§5 整节重写为 v2**（把 v1 混在一格的**许可**与**架构**拆成两层分别判，因为二者可变性完全不同）。
  按用户三项裁决落地：① 与上游的关系 = **分域只读研读 + 自研**（§5.3 路径③）；② **两处"地基级冲突"启动重评审**（`single_pg` 取舍 / 桌面执行模型 ⇒ 新增 **§7 Q4 / Q5**，**§6 C 档第 1 / 5 条由"明确不可动"降级为"待评审"**）；③ 本轮主交付 = 新增 **§10 能力域研读提纲**。
  同步登记 `decision-log.md` **D-049**（并对 **D-047①** 加前提变更标注）。
  **本轮同样零产品代码改动、零后端接口改动、零契约口径改动**（两处重评审**只启动、不改动**：`architecture.md` 与 `schema-per-tenant-plan.md` 均**未动**）。
- **编号顺序说明（为什么要新增 §10 而不是插在 §5 后面）**：本文件 §1–§9 已有**外部引用**（`decision-log.md` 的 Q1 / Q2 / Q3 均指向"专项文档 §7"），
  在中间插节会让既有引用指向漂移 ⇒ 新节**一律追加在文末**。
- **血缘声明**：本仓库 `grep` **零处**命中 `tabtin` / `TabTin` / `摹范` / `Mofan` / `larchiveai`
  ⇒ **我方与 TabTin 无任何代码或文档血缘**，本文件是**纯外部参照**记录。

## §10 能力域研读提纲（v2 新增；**本轮主交付**）

> **归并口径（先说清，避免被读成"上游官方分类"）**：下面 8 个能力域是**我方归并**，**不是上游的官方分类**。
> 归并依据 = `gh api repos/tabtin-ai/TabTin/git/trees/HEAD?recursive=1` **一手取回**（`truncated=false` ⇒ 全量未截断）。
> **交叉校验**：本次实测 `packages/` 下 **90 个包 / 4,827 个文件**，与 §3 取回的 `packages/ 4,827` **完全一致 ✅**
> ⇒ 归并未漏包（8 域包数 11+20+9+20+5+9+16 = **90**，文件数 1,308+1,454+325+745+78+258+659 = **4,827**）。

### §10.1 全貌（三层，均为实测文件数）

| 层 | 实测 | 明细 |
| --- | --- | --- |
| `apps/` | **8 应用 / 15,337 文件** | `tabtin-electron` 6,951 / `tabtin_django` 5,017 / `tabtin-android` 1,406 / `tabtin-ios` 1,012 / `admindash` 407 / `tabtin-daemon` 233 / `tabtin-web` 207 / `collab-live` 104 |
| `packages/` | **90 包 / 4,827 文件** | 见 §10.2 八域 |
| 仓库总量 | **20,672 文件**（约 **145 MB** 纯源码） | `.ts` 7,656 / `.py` 4,910 / `.tsx` 2,176 / `.kt` 1,137 / `.swift` 545 / `.go` 227 |

**两条先摆出来的边界事实（都影响你清单的可行性）**：

1. ✅ **全仓 0 命中"鸿蒙"**（HarmonyOS / hvigor / ArkTS 等关键词均无）⇒ 你清单里的「**鸿蒙端**」**在上游没有参照物**，要做只能**纯自研**。
2. ✅ `apps/tabtin-android` 1,406 + `apps/tabtin-ios` 1,012 是**真实存在的原生端**；但上游 ROADMAP 自述「**移动端不提供独立的 Agent 执行环境**」
   ⇒ 与我方 PWA 取舍（**只做登录 / 待办 / 审批**）**完全一致**（§4 已记录，属**反向验证**而非差距）。

### §10.2 八个能力域（构成 / 我方现状 / 内部使用价值 / 合规红线 / 建议）

图例：**建议** = `深入研读` / `选择性研读` / `暂不` / **`不适用（红线）`**；「我方现状」只写**我方仓库可核对**的事实。

| 域 | 构成（包 · 实测文件数） | 我方现状 | 对"内部使用"的价值 | 合规红线 | 建议 |
| --- | --- | --- | --- | --- | --- |
| **D1 Agent 内核与运行时** | `agent-runtime` 646 / `agent-host` 323 / `action-tools` 143 / `agent-wire` 52 / `agent-prompt` 34 / `skills` 26 / `agent-import` 21 / `agents` 21 / `agent-modes` 19 / `prompt-contract` 19 / `action-tools-adapter` 4 ⇒ **11 包 / 1,308 文件** | **已有**：自研 `AgentRuntimeAdapter` + 多适配器共存规约 + 子 Agent / 记忆 / Skill / 编排（P3 / P4 / P6a 已交付） | 中：我方**已是对方 ROADMAP 的目标形态**（对方自述"替换与扩展成本仍然较高"）；可学其**接口分层**（`agent-wire` / `prompt-contract` / `agent-modes` **独立成包**） | 无 | **深入研读**（只读**接口与契约层**，不读实现层） |
| **D2 文档 · 表格协同（CRDT）** | `tabslide` 245 / `smartsheet-ui` 223 / `tabdoc-ui` 212 / `table-ui` 159 / `table-engine-canvas` 158 / `table-kernel` 103 / `table-core` 85 / `doc-editor` 63 / `collab-core` 56 / `table-engine` 54 / `table-kernel-pglite` 28 / `smartsheet` 20 / `doc-renderer` 12 / `smartsheet-adapter-electron` 8 / `ws-gateway-client` 7 / `markdown-resource-autolink` 6 / `smartsheet-adapter-web` 4 / `tabdoc-host-runtime` 4 / `table-host-runtime` 4 / `office-preview-runtime` 3 ⇒ **20 包 / 1,454 文件** | **空白**：我方实时协作 = 自研 **SSE + PG 流帧 + Outbox**，**无 CRDT、无协同编辑数据模型** | **高**：你清单的「**多人同编文档 / 表格**」正是本域，也是"人机协作工作区"的核心体验 | 无（CRDT 本身合规） | **深入研读**（读**数据模型与冲突合并口径**）。⚠️ **但"是否立项 / 是否引入第二套实时基础设施"本轮未启动裁决**（§6 C 档第 2 条仍为默认不可动）⇒ **本轮只研读、不立项** |
| **D3 执行环境（终端 · 浏览器 · PTY · LSP · 运行时宿主）** | `browser-core` 118 / `terminal-core` 97 / `pty-core` 39 / `lsp-runtime` 29 / `python-runtime` 17 / `file-history-core` 10 / `browser-capabilities` 7 / `python-runtime-host` 4 / `runtime-reporter` 4 ⇒ **9 包 / 325 文件** | **空白**：我方 `desktop/` 只是 **Electron 安全壳**，**无 pty / 浏览器 / LSP 内核** | **高**：这是「**桌面端为执行环境**」的**能力底座**，与 §7 **Q5 重评审**直接相关 | 无（`safe-fs` / `env-sanitize` 归 D5） | **深入研读**，但**顺序上 Q5 是前提**：先定"桌面执行 vs 服务端九步闸门"的关系，再决定读多深 |
| **D4 应用宿主与外壳** | `apps` 406 / `app-shell` 60 / `media-capabilities` 60 / `media-core` 33 / `connector-brand-icons` 32 / `platform-reach` 32 / `resource-router` 17 / `file-pipeline` 15 / `agent-orb` 14 / `app-host-sdk` 14 / `file-pipeline-errors` 10 / `storage-manager` 10 / `tabtin-desktop-contracts` 11 / `widget-tokens` 9 / `tabtin-desktop-native` 7 / `tabtin-config` 5 / `app-config` 4 / `platform-adapter` 3 / `tailwind-preset` 2 / `platform-capabilities` 1 ⇒ **20 包 / 745 文件** | **部分**：三端 `workbench-web` / `admin-web` / `companion-pwa` + `desktop`；**无统一"应用宿主 + 应用包"契约** | 中：若将来要"多应用"式铺开，本域是**宿主侧工程范式** | 无 | **选择性研读**（只读 `app-host-sdk` / `app-shell` / `tabtin-desktop-contracts` 的**宿主契约设计**；**不铺开应用面**，与 §6 C 档第 3 条一致） |
| **D5 安全与策略** | `security-policy` 39 / **`anti-detect` 22** / `checkpoint-core` 7 / `env-sanitize` 6 / `safe-fs` 4 ⇒ **5 包 / 78 文件** | **部分**：容器负向隔离（`--network none` / 只读根 / 非 root）+ 九步闸门；**无 `checkpoint-core` 等价原语**（= 候选 **C5**） | 中：`checkpoint-core`（**7 文件**）与 `security-policy` 可读；`safe-fs`（4 文件）/ `env-sanitize`（6 文件）是**小体积高价值**的隔离件 | **⛔ `anti-detect` 命中红线**：我方 `architecture.md` 明文"**不实现风控规避、设备伪装和代理轮换**"，候选 **C3** 已冻结 | `security-policy` / `checkpoint-core` / `safe-fs` / `env-sanitize`：**可研读**；**`anti-detect`：不适用（不得参照）** |
| **D6 爬取 · 站点 · 检索** | `tabsite-templates` 68 / `crawlspace-core` 67 / `crawl-integration` 47 / `local-docparse` 19 / `local-embedding` 17 / `crawl-contracts` 13 / `search` 13 / `extraction-core` 8 / `tabsite-core` 6 ⇒ **9 包 / 258 文件** | **部分**：知识库 = pgvector + 知识策略守卫（**fail-closed**）+ 检索前过滤 + 绑定治理台 + ACL；**无爬取域** | 低～中：`local-docparse` / `local-embedding`（**本地化、不依赖外部 API**）对"内部使用"有参考价值；**爬取域**与内部使用诉求弱相关 | **⚠️ 爬取有合规外部性**：`crawlspace` / `tabsite` 涉**目标站点抓取**，须单独判合规，**不得顺手引入** | `local-docparse` / `local-embedding` / `search`：**选择性研读**；**爬取与站点域：暂不** |
| **D7 CLI · SDK · 基础设施 · 代码生成** | `tabtin-cli-go` 230 / `wire-codegen` 169 / `cli-server-core` 47 / `cli-routes` 37 / `tabtin-shared` 37 / `tabtin-chat-client` 36 / `tabtin-filegen-python` 19 / `tool-errors` 12 / `contracts` 11 / `os-errors` 11 / `tabtin-cli` 11 / `api-client` 10 / `tabtin-sdk` 10 / `tabtin-sdk-python` 9 / `infrastructure` 6 / `oss-client` 4 ⇒ **16 包 / 659 文件** | **部分**：契约先行（`api-contract.md`）我方已有 `docs/contracts/` 等价物；**无跨端代码生成**（`wire-codegen` **零对应**） | 中：`wire-codegen`（169 文件）解决「**多端契约一致性**」，是**工程手段**而非产品能力——**我方多端铺开才需要** | 无 | **选择性研读**（只读 `wire-codegen` 的**生成管线设计思想**；其余暂不） |

> **对账（防漏包）**：11 + 20 + 9 + 20 + 5 + 9 + 16 = **90 包**；1,308 + 1,454 + 325 + 745 + 78 + 258 + 659 = **4,827 文件**。**无遗漏、无重复计入**。

### §10.3 三个"深入研读"域的研读要点（**问题清单，不是结论**）

**D1 Agent 内核**——要回答：① 子 Agent 的**创建 / 授权 / 回收**边界（与我方「数字员工权限 = 创建者 ∩ 使用者 ∩ 岗位能力包」**如何对表**）② 记忆的**分层与写入时机**（我方 `app/memory/` 已有 ⇒ **只取差异**）③ `agent-wire` / `prompt-contract` **为何独立成包** ⇒ 契约分层的做法值不值得学 ④ **反例必记**：`agent-runtime/src/subagent/agent-tool.ts` **单文件 154.8 KB**、`capability/core/shell.ts` **95.9 KB**、`engine/tooling/tool-orchestration.ts` **93.6 KB** ⇒ **这种组织方式不得模仿**。

**D2 文档 · 表格协同**——要回答：① Yjs CRDT 与「**二维表格**」这种结构**如何映射**（数组 / Map 嵌套？冲突合并对"单元格"意味着什么）② `collab-core`（56 文件）**为何独立于** `table-core` / `doc-editor` ⇒ 协同**抽象层**的划法 ③ `ws-gateway-client`（7 文件）与 Centrifugo 的**职责边界**，与我方 `SSE + PG 流帧 + Outbox` 的**差异点在哪** ④ `table-kernel-pglite`（28 文件）⇒ **本地库**在协同里扮演什么角色（我方**零对应**）。

**D3 执行环境**——要回答：① `pty-core` / `terminal-core` 的**进程隔离口径**（我方是**服务端容器负向隔离**，**方向相反**）② `safe-fs`（**4 文件**）+ `env-sanitize`（**6 文件**）如何**最小化**做隔离（**小体积 ⇒ 思路最值得直接学**）③ `browser-core` 与 `browser-capabilities` 的**分层** ⇒ 能力声明 vs 实现 ④ `lsp-runtime` 与 `python-runtime(-host)` 的**执行环境宿主抽象**方式。

### §10.4 本提纲**不**做的事（与 §5 / §6 / §7 对齐）

- **不搬代码**（§5.3 路径①：衍生作品整体传染 + 2 万文件债不可拆 + 一次对外即触发）；
- **不接适配器**（§5.3 路径②：`architecture.md L51` 架构硬约束，与商不商用无关）；
- **不引入 `anti-detect`**（D5 红线：我方明文不做风控规避）；
- **不铺开应用面**（§6 C 档第 3 条）；
- **本提纲 ≠ 立项**：D2 / D3 要不要做，分别取决于 **§7 Q5** 与新开的立项评审；本轮**只出提纲、不动代码、不改契约**。

> **⚠️ 本节的"未验证"（不得读成已验）**：① 分域是**我方归并**，**非上游官方分类**；② 各域成员包**只按包名 + 实测文件数归并**，**未逐条读上游实现**（因此 §10.3 全是**问题清单**，**不是结论**）；③ 「我方现状」列的"空白 / 部分 / 已有"来自**我方仓库直读**，未与上游做功能级二次比对；④ 上游**无鸿蒙端**这一条是**关键词 0 命中**（✅），但"0 命中"**不等于**"上游将来不做"。