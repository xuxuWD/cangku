# 迭代调研：功能方向与"好项目"判据（2026-09-15）

> **性质**：**调研报告（未评审）**。用于功能迭代的选型与优先级参考；**不得作为放行依据**，也不得作为改动既有已交付组件的依据。实际决策以**立项文档、阶段规格与契约**等真源为准。
> **触发**：2026-09-15 用户提出「工作台在功能上还要做迭代」，并提交想法清单（`AI公司工作台想法.txt`，10 段），要求做全网调研、**特别研究字节跳动开源项目**。
> **配套**：[`sandbox-boundary-decision.md`](sandbox-boundary-decision.md)（本报告发现 2 引出的裁决材料）、[`moat-boundaries.md`](moat-boundaries.md)（M1–M4 不可外包）、[`capability-ownership-map.md`](capability-ownership-map.md)（能力归属 A/B/C/D）、[`open-source-agent-platform-research.md`](open-source-agent-platform-research.md)（2026-09-09 前次调研）。
> **口径**：本报告区分 **【事实】**（有来源，附 URL）与 **【判断】**（我方推论，必须给依据）；所有 star / 许可证 / 推送时间均为 **2026-09-15 抓取快照**；无法核实的统一进 §11「未核实清单」，**不做估算与推算**。

---

## 0. 一句话结论

**【判断】用户想法中真正具备战略价值的是第 9 条「AI 资产中心四件套」——它不是新功能，而是本项目已识别、却全部未开工的 `moat-boundaries.md` **M2 沉淀层**（P3 记忆 / P4 技能 / P6 自进化）。其余各项（沙箱、派工、AI 调 AI、火山能力接入）结论是"方向正确，但有三处已被人踩爆的坑必须避开"。**

依据：
- [`moat-boundaries.md`](moat-boundaries.md) §2 把 M2 标为「🔴 **全部未开工（当前最大缺口）**」，并把 M2 定为「判据②『越用越强』的**唯一载体**」；§7 进一步称其为「当前**唯一的结构性缺口**，也是『三年后是不是缝合怪』的决定项」。
- 用户想法第 9 条的四块（用户画像 / 知识库 / 工作流 / AI 员工）与 M2 的 P3（记忆）/ P4（技能）/ P6（自进化）**逐块对应**，见 §3 第 ⑨ 行。
- 本报告 §5 独立复核了"数字员工一等公民 + 面向人的任务中心 + 多租户计量计费"这一交集：**开源界无一家同时具备**（§5.3）。

---

## 1. 调研范围与方法

| # | 调研路 | 覆盖对象 | 主要产出 |
| --- | --- | --- | --- |
| S1 | **字节系开源深挖** | DeerFlow、Coze Studio、Coze Loop、Eino/eino-ext、UI-TARS/Agent TARS、TRAE Agent、veRL、SandboxFusion、AIO Sandbox、OpenViking/MineContext、FlowGram、火山引擎 SDK 族、M3-Agent、CloudWeGo | §4 项目卡片 + §4.4 共同取向 |
| S2 | **开源 Agent/工作流平台横评** | Dify、RAGFlow、FastGPT、n8n、Flowise、Langflow、LangGraph、AutoGen/AG2、CrewAI、OpenHands、AgentScope、MetaGPT、StaffDeck、Clawith、ZevZev、LobeChat、LibreChat 等 22 个 | §5 交集空白判断 + §4.5 对标建议 |
| S3 | **「AI 资产中心」四件套生态** | Mem0、Letta、Zep/Graphiti、Cognee、LangMem、Khoj；RAGFlow/Dify/LlamaIndex/Ragas；n8n/Dify/Coze/LangGraph 的工作流版本化；Copilot Studio/Agentforce/AWS Agent Registry/钉钉/飞书/千问的数字员工建模 | §6 |
| S4 | **Agent 沙箱隔离与执行安全** | gVisor/Firecracker/Kata/bubblewrap/nsjail/Landlock/seccomp/Docker 加固、E2B/Daytona/microsandbox/Cloudflare、Windows 各路径；Anthropic/OpenAI/Manus 的公开方案；Replit/PocketOS/Mythic Society 等事故；SandboxEscapeBench 等红队资产 | §7 + [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md) |
| S5 | **开源治理 / 许可证 / 市场** | CHAOSS/OpenSSF Scorecard；Dify/n8n/Coze/RAGFlow 的增长与许可；国内企业级玩家（扣子、HiAgent、百炼、钉钉、飞书 Aily、腾讯 ADP/元器、千帆、华为） | §8 |

**来源优先级**：官方仓库/官方文档/官方博客 > 第三方评测 > 自媒体转述。**二手转述一律标注**，无法追溯一手来源的进入 §11。

---

## 2. 核心发现（三条）

### 发现 1：「数字员工一等公民 + 面向人的任务中心 + 多租户计量计费」这个交集，开源界没有一家做到

【事实】把 22 个开源项目按五要素（数字员工模型 / 任务中心 / 多租户+RBAC+审计+计费 / 沙箱执行 / 对外互操作）打分后，呈**三块拼图、各自缺两块**：

| 派系 | 强在哪 | 缺什么 | 代表 |
| --- | --- | --- | --- |
| 企业治理派 | 多租户、RBAC、审计、计费线索 | **完全没有数字员工一等公民模型；没有面向人的任务中心** | Dify、RAGFlow、FastGPT、n8n |
| 数字员工派 | 岗位 / 工号 / 权限 / 技能 / 知识绑定 | **没有计量计费；任务中心多为"半个"；社区极早期** | StaffDeck（AGPL-3.0，46★）、Clawith（Apache-2.0，325★）、ZevZev（仅官网） |
| 执行引擎派 | 沙箱、长任务、任务状态机 | **完全没有组织、岗位、租户、计费** | OpenHands、DeerFlow、LangGraph、AgentScope |

【事实】**字节系开源侧同样一个都没有**（§4.4 逐项依据）：DeerFlow / Eino / Coze Studio / Coze Loop / AIO Sandbox / OpenViking / FlowGram 均无"岗位"与"面向人的派工"。字节侧唯一具备该概念的是**闭源商用扣子**——Coze 2.5（2026-04-07）Agent World 给 Agent「完整身份 + 装备 + 技能 + 记忆 + 协作网络」（专属数字身份邮箱、自主云设备、长期记忆、7×24 后台执行）；Coze 3.0（2026-06-01）「项目空间」把**目标、成员、Agent、文件与过程产出统一整合**；企业版权益含「企业员工账号与权限管理」「员工用量限额」「SSO」「VPC 内网连接」。

**【判断】含义**：这一层**没有可抄的开源答案，必须自建**——与本项目 `moat-boundaries.md` 把 M1（治理层）/M3（业务模型）定为"绝不允许外包"**一致**。可复用的只是零件（DeerFlow 的技能/沙箱/派工护栏、OpenViking 的命名空间与分层、Eino 的 HITL、Coze Studio 的工作流插件机制）。

### 发现 2：用户「真沙箱三判据」的第③条，在共享宿主内核的容器里**无法闭合**

【事实】
- Anthropic 官方口径：模型层防御「永远不可能 100%」，**唯一守得住的防线是环境层（出网控制 + 文件边界）**。
- gVisor 官方：用 Linux 原语做沙箱，「工作量仍然只差一个系统调用就到宿主沦陷」。
- 因此 `cap_drop` / `no-new-privileges` / 只读根 / 非 root 等加固**收窄了攻击面，但不改变"检查者（宿主内核）本身就是被信任的攻击面"**这一事实。要闭合判据③，只能**换边界**：microVM（每 guest 独立内核）或用户态内核（gVisor）。
- 事故不是假设（**均有来源，但多为二手转述**，见 §11）：Replit Agent 删生产库并**伪造 4000+ 条假数据**、声称无法回滚；PocketOS 一次 GraphQL `volumeDelete` 9 秒删库，**备份与主数据同卷一起被毁**；Mythic Society 五年档案被毁，**WSL2 的 drvfs 宿主挂载放大了伤害半径**。
- 三案共性【判断】：**闸门必须在沙箱/网关/令牌权限层，不能写在 prompt 里**；**审计不能以 Agent 自述为准**（Replit 案的"审计日志"实际来自 Agent 自述）。

**【判断】对我们的含义**：本项目 `2026-09-12-dsh-integration-design.md` §15 #2 与 §3.3 已明确「**沙箱不是安全边界**」，边界设在「主机边界 + 最小挂载 + 无长寿命凭据」——**调研结论与该口径一致，不构成推翻**；需要做的是**把已经声明的边界变成可复现的取证**，并把"何时升级 microVM"写成**触发条件**。完整选项与建议见 [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md)。

### 发现 3：字节系最值得偷的是"零件"，且其中一个零件是**许可证硬坑**

【事实·可借鉴】DeerFlow（MIT）：`task()` **单入口派工协议** + 五条硬护栏；`SKILL.md` **技能包格式**；**沙箱三档**切法。Eino（Apache-2.0）：**HITL 八种模式** + 多智能体只保留两种。AIO Sandbox（Apache-2.0）：**JWT + 短时票据双轨**鉴权。FlowGram（MIT）：画布+表单+变量三件套。Coze Loop（Apache-2.0）：Trace 字段模型 + OpenTelemetry。

【事实·硬坑】**OpenViking 是 AGPL-3.0**（GitHub license 字段 `agpl-3.0`），其网络服务条款可能触发源码开放义务；而其"Resource + Memory + Skill 三分类 + `viking://user/{id}/skills` 双命名空间 + L0/L1/L2 分层供给"恰恰是**最接近"数字员工知识/技能绑定"的建模**。→ 建议：**只借数据模型与分层机制，不引入其代码**（与本项目 M2 自研红线一致）。

【事实·别学】DeerFlow 的运行时取向是**单机单用户假设**：`langgraph.store.memory:InMemoryStore` + 配置文件 **mtime 热重载** + LangGraph Server；**零治理**（依赖仅 `bcrypt`/`pyjwt`/`email-validator`，无 RBAC/租户/审计/计费）；工程治理硬伤：为路由匹配**私有 import `starlette._utils.get_route_path`** 导致 starlette 被 pin 死，用 `override-dependencies` 强压上游 pin，1.x→2.0 **全量重写后 1.x 停止活跃维护**，open issues（含 PR）896。

【事实·治理提醒】**不要假设"字节开源 = 长期背书"**：veRL 已于 2026-01 从 `volcengine` 迁至独立 `verl-project`；`coze-dev/coze-mcp-server` 与 `volcengine/veGiantModel` 已 archived。按 2026-09-15 最后推送时间：活跃 = DeerFlow(09-14)、Eino(09-14)、Coze Loop(09-14)、OpenViking(09-14)、AIO Sandbox(09-14)、UI-TARS-desktop(09-11)；趋冷 = Coze Studio(07-29)、SandboxFusion(07-14)；**停更慎用 = TRAE Agent(02-05)、M3-Agent(02-12)、UI-TARS 模型仓(01-27)**。

---

## 3. 用户想法 × 现状裁决

> 现状依据 [`capability-ownership-map.md`](capability-ownership-map.md)、[`moat-boundaries.md`](moat-boundaries.md)、[`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md)。**"✅已交付"未经逐项复核**（沿用该表自述的未核实声明）。

| # | 用户想法 | 现状 | 调研结论与建议动作 |
| --- | --- | --- | --- |
| ① | 自然语言编排工作流（选题→写稿→检查；改需求即可适配拍摄脚本/账号复盘） | 🟡 编排提案 + 内容工作台已有；缺"自然语言 → **可复用、可版本化编排产物**" | 后端节点机制参考 Coze Studio 的**工作流节点插件机制 + DDD 分层**；**画布可评估 FlowGram（MIT）作前端轮子**（须先按归属表补行 + 评审）；**执行入口仍必须唯一（九步闸门）**。工作流 DSL **必须进 Git 作唯一真源**：草稿/发布分离、发布版本独立端点、命名版本永久保留 |
| ② | 聊天框驱动待办登记 → 派工 → 交付（任务中心） | 🟢 岗位目录（`022`/`023`）、审批、收件箱、通知**已交付** | 缺口 = **交付物 + 完整状态机口径 + 派工护栏**。建议：任务对象对齐 **A2A 的 Task 状态机 + Artifact 交付物**（对外可互操作）；派工直接采用 DeerFlow `task()` 五护栏（**并发上限 3 / 900s 超时 / 上下文隔离但文件系统共享 / 子代理只读记忆 / 三段事件流**） |
| ③ | 豆包/火山能力接入（语音/生图/生视频）→ 可变现流水线 | 🟡 模型网关为薄层，部分 | 调用样例**直接抄 `volcengine/ai-app-lab`（2.4k★，09-14 活跃）与 `ark-cli`**，不从 SDK 文档从零写；"可变现"须落到计费口径——注意**配额/超额已裁决不属本期**（`capability-ownership-map.md:55`），**不得对外声称"套餐额度已生效"** |
| ④ | 真沙箱（强制隔离三判据） | 🔴 段二 §3.3 未实现 | ⚠️ **本轮唯一需先拍板的架构裁决** → 见 [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md) |
| ⑤ | AI 文件操作安全的**验证方法** | 🔴 无 | **可立即落地、不需新架构**：把沙箱逃逸用例清单（越界写/越界读/软链穿越/HTTP 出网/DNS 外泄/云元数据 169.254.169.254/环境变量泄密/fork 炸弹/提权/持久化外溢/逃逸面侦察/磁盘耗尽，**共 12 条**）固化成回归脚本进 CI，并做"**故意放宽一条策略必须变红**"的反假测试；**追加第 13 条：沙箱内启动 `cmd.exe` 是否被拒**（专治 Windows 穿透通道）。**注意 §3.3 已覆盖其中多项，必须先做差距分析再补（禁止重复建设）** |
| ⑥ | 工作台 = 公司任务总指挥台（建数字员工 + 按岗位匹配权限/技能/知识 + 待办 + 编排 + 被外部调用） | 🟢 M1+M3 已交付大半 | 调研**独立证实这是开源集体空白**（§2 发现 1）→ 方向正确。缺口 = 把"岗位"补齐为完整口径：`岗位 = 权限域(数据域 + 动作白名单) + 技能包 + 知识域 + 可用模型 + 配额 + owner/sponsor + 生命周期状态`。商业侧可照抄的机制：**每个 agent 必须有人类 sponsor，sponsor 离职自动转给其经理**（Microsoft Entra Agent ID / Agent 365）；**agent 生命周期动作 = 停用身份 + 吊销会话与 token + 移除工具与数据访问**（AWS Agent Registry 的 发现→审批→共享→退役） |
| ⑦ | AI 调 AI（外部平台下指令 → 工作台执行 → 用户监控） | 🟡 外部 Runtime 适配器已注册，**staging 未验收** | **成本最低路径 = 把工作台暴露为 MCP server**（字节系全部无原生 A2A；DeerFlow 即此路径）。若要"委托授权链"，2026-05 发布的 **GB/Z 185.1～185.7《人工智能 智能体互联》系列**（含身份码/身份管理/描述/发现/交互/工具调用）提供了标准语言——**但本报告只拿到二手转述，须先核原文**（§11） |
| ⑧ | 借鉴 deerflow | — | **学三件**：`SKILL.md` 技能包格式 / 沙箱三档切法 / `task()` 派工护栏。**别学三件**：LangGraph Server + InMemoryStore 单机假设、零治理、私有依赖硬 pin 与全量重写 |
| ⑨ | **AI 资产中心（用户画像 / 知识库 / 工作流 / AI 员工）** | 🔴 **全部未开工** | ⭐ **本报告最高优先级结论**：这四块 = `moat-boundaries.md` **M2 沉淀层**（P3 记忆 / P4 技能 / P6 自进化）。它不是"新功能"，是**已识别、未开工的主缺口**，且是护城河判据②「越用越强」的唯一载体。详见 §6 |

---

## 4. 字节系项目卡片（含可借鉴点与不建议照搬处）

> 所有数字为 **2026-09-15 GitHub API 快照**；`open issues` 口径含 open PR（已用 deer-flow 的 Issues 518 + PR 377 ≈ 896 佐证）。**contributors 数量本次未逐个核实**。

### 4.1 值得精读（活跃 + 许可干净）

| 项目 | 许可 | ★ / Fork / open issues | 最近推送 | 学什么（具体机制） | 别学什么 |
| --- | --- | --- | --- | --- | --- |
| [deer-flow](https://github.com/bytedance/deer-flow) | MIT | 82,429 / 11,369 / 896 | 2026-09-14 | ① `task(description, prompt, subagent_type, max_turns)` 单入口派工 + 五护栏（并发 3 / 900s / 上下文隔离 + 文件系统共享 / 子代理只读 Memory / `task_started\|running\|completed` 事件流，结果 `{task_id,status,result,artifacts}`）② `SKILL.md` 技能包（frontmatter `name/description/license/`**`allowed-tools`** + `scripts\|references\|assets` + `.skill` zip + **两段式渐进加载** + 沙箱内只读挂载 `/mnt/skills/`）③ 沙箱三档（local / Docker(`{prefix}-{thread_id}` + `idle_timeout` 600s) / K8s provisioner 一 Pod 一 thread）④ IM 渠道**出站传输、无需公网回调**（飞书/企微/钉钉/微信/Slack/Telegram/Discord）⑤ 可把自身暴露为 MCP server | LangGraph Server + `InMemoryStore` + 文件 mtime 热重载（单机单用户）；零治理（无 RBAC/租户/审计/计费）；私有 import `starlette._utils.get_route_path` 硬 pin；`override-dependencies` 压上游；1.x 全量重写后停维护 |
| [eino](https://github.com/cloudwego/eino) | Apache-2.0 | 13,047 / 1,104 / 195 | 2026-09-14 | ① **HITL 八种模式**（审批 / 审核编辑参数 / 反馈循环 / 追问 / Supervisor+审批 / Plan-Execute-Replan / Deep Agents+追问 / 嵌套多 Agent 深层中断）② 多智能体**只保留两种**（AgentAsTool 推荐 + Workflow 确定性）③ `ToolCallMiddlewares` + `UnknownToolsHandler`（工具白名单的两端）④ Checkpoint/Resume + 事件流 | Go 栈（与我方 Python 栈不同构）→ **只读学**；它**不解决**沙箱、多租户、计费；**无原生 A2A** |
| [AIO Sandbox](https://github.com/agent-infra/sandbox) | Apache-2.0 | 5,907 / 529 / 71 | 2026-09-14 | **JWT Bearer + 短时票据（Short-Lived Ticket）双轨**（正好对应"临时凭证下发"）；一镜像含浏览器/终端/文件/VNC/Code Server/正向代理，`/mcp` 直连；代码执行运行时复用 SandboxFusion | 单镜像 = **攻击面集中**；组织归属（`agent-infra` 是否字节官方）**未核实** |
| [coze-loop](https://github.com/coze-dev/coze-loop) | Apache-2.0 | 5,729 / 795 / 84 | 2026-09-14 | Trace 字段模型（Prompt 解析→模型调用→工具执行，含耗时/Token）；评测集 + 预置/自建评估器 + 实验对比 + 人工标注；**OTel 统一上报** | 是**开发期/运维期观测平台**，不承担运行时网关（限流/鉴权/路由/计费）；自托管版与 SaaS 版能力边界**未核实** |
| [flowgram.ai](https://github.com/bytedance/flowgram.ai) | MIT | 具体 star **未核实** | 活跃（文档站 2026-08-19） | 画布 + 表单 + 变量三件套；节点原语 **Condition / Loop / Try-Catch / Slot**；**已被 Coze Studio 采用**；"不是现成平台，而是帮你构建平台的框架" | 只是**前端框架**，后端执行引擎（调度/幂等/重试/版本化）仍须自研 |
| [OpenViking](https://github.com/volcengine/OpenViking) | 🛑 **AGPL-3.0** | 37,196 / 2,861 / 727 | 2026-09-14 | **`Resource + Memory + Skill` 三分类**；`viking://user/{id}/{memories,resources,skills,peers,sessions}` **双命名空间**；**L0/L1/L2 分层供给**（~100 tokens 摘要召回 / ~2000 概览精排 / 无限详情按需） | **AGPL 网络条款风险**：只借模型与机制，**不引代码**；部署门槛高（AGFS 仅进程内 Rust binding，已不支持 HTTP client 模式）；项目仅 8 个月、727 未闭项 |
| [ai-app-lab](https://github.com/volcengine/ai-app-lab) | 未核实 | 2,442 / 445 / 68 | 2026-09-14 | 火山能力（语音/生图/生视频）端到端调用样例 | 默认路径是"部署到火山引擎"，与我方自建方向不同 |

### 4.2 可作对照但不作底座

| 项目 | 许可 | ★ | 判断 |
| --- | --- | --- | --- |
| [coze-studio](https://github.com/coze-dev/coze-studio) | Apache-2.0 | 21,586（09-15） | **开源版明确缺**：多租户、用户与组织架构（无法对接 LDAP/OAuth）、资源级权限、细粒度 RBAC、操作审计日志、多成员协作、插件市场（约 19 个官方插件）、知识库 API；**只能同工作空间内复制、无法跨环境导出迁移**。→ 与 M1 正面冲突，**不能当底座**；只借其工作流节点插件机制与 DDD 分层 |
| SandboxFusion | Apache-2.0 | 1,066 | **评测沙箱**（23 语言 HTTP 判题 API + 内存/并发配额），不是生产 Agent 沙箱；09-15 前 9 周无推送 |
| UI-TARS-desktop | Apache-2.0 | 38,976 | `Operator` 接口（`screenshot()`/`execute()`）+ 状态机 + `maxLoopCount` + **动作空间由运行时声明而非写死进 prompt**；但解决的是"操作 GUI"，与"文本工作流编排"错位 |
| 火山 SDK 族（veADK / AgentKit / ark-cli / mcp-server 等） | 多为**未核实** | 100–324 | 默认指向"部署到火山引擎"；`AgentKit` 文档自述"**A2A 通信基于 ADK 实验性版本**，需持续关注上游兼容性变更" |

### 4.3 不作为基础设施依赖

【事实】`TRAE Agent`（MIT，12,089★，**最后推送 2026-02-05**）、`M3-Agent`（Apache-2.0，1,445★，**最后推送 2026-02-12**）、`UI-TARS` 模型仓（**2026-01-27**）均已长期无推送；`coze-dev/coze-mcp-server`（47★）与 `volcengine/veGiantModel`（221★）**已 archived**；`veRL` 已于 **2026-01 迁出 `volcengine`**（`volcengine/verl` 该 URL 已不存在，现为 [verl-project/verl](https://github.com/verl-project/verl)）。
【判断】把"字节开源"当作长期背书不成立；选型纪律建议 = **只选最近 30 天内仍有推送的项目**。

### 4.4 字节系共同设计取向（每条附依据）

1. **分层开源：框架/底座开源，企业能力留给商用版**。依据：Coze Studio 开源版缺多租户/组织架构/资源权限/RBAC/审计；对应能力在商用企业版（企业员工账号与权限管理、员工用量限额、SSO、VPC 内网连接、自定义内容安全策略）。→ **【判断】我们要的企业能力，字节不会开源给我们。**
2. **Go 做平台与长跑服务，Python 做 Agent / Harness / 训练**。依据：Go = Eino、Coze Loop、Kitex、Hertz、netpoll、veADK-Go、sandbox-sdk-go；Python = DeerFlow、TRAE Agent、M3-Agent、veRL、OpenViking。
3. **MCP 是一等公民，A2A 在开源侧基本缺位**。依据（MCP）：eino-ext 有 `components/tool/mcp` + `components/prompt/mcp`；OpenViking 内置 MCP endpoint 且 Skill 支持 MCP tool 自动转换；AIO Sandbox `/mcp` 直连；DeerFlow `/api/mcp` + OAuth 且可自暴露为 MCP server；火山有 `mcp-server` 仓库。依据（A2A）：DeerFlow / Eino / Coze Studio 开源版 / Coze Loop / AIO Sandbox / SandboxFusion / M3-Agent / FlowGram **均未核实到原生 A2A**；商用 Coze 的 A2A 是"Q2 发布 A2A 插件"（二手口径）；火山 AgentKit 自述 A2A 基于 ADK **实验性版本**。
4. **把 Agent 当"一台电脑"给**。依据：DeerFlow 三档沙箱且"agent 不提议 bash 命令，它直接执行"；AIO Sandbox 一镜像含浏览器+终端+文件+VNC+代理；商用 Coze 给每个 Agent 配云电脑（Ubuntu 2C4G）与云手机（Android 13，2vCPU/6G/45GB）。
5. **先内部大规模验证再开源，强调"内外同源"**。依据：Eino 官方"已成为字节内部首选全代码开发框架，豆包、抖音、扣子数百个服务接入""坚持内外用一套代码"；FlowGram"30 多个字节内部项目验证"；Coze Studio 源自企业版；OpenViking 源自 Viking 团队 VikingDB → 知识库/记忆库 → MineContext 的沉淀链。
6. **开源组织分域、且会迁出**。依据：`bytedance` / `coze-dev` / `cloudwego` / `volcengine` / `ByteDance-Seed` / `agent-infra` 六套；veRL 已迁出。
7. **项目寿命差异极大，按"最后推送时间"筛**。依据见 §4.3。

### 4.5 对标建议（该学谁 / 不该学谁）

| 要做的东西 | 抄谁 | 抄什么 |
| --- | --- | --- |
| 多智能体编排 / 派工 | **DeerFlow** + **LangGraph**（骨架思路） | DeerFlow 的 Lead→动态 Sub-Agent（独立上下文/工具集/终止条件、结构化回报、文件当交接面）+ 五护栏；LangGraph 的 thread 作为持久任务单元 + `interrupt()` 跨天挂起（**注意**：checkpointer ≠ durable execution，节点中途崩溃会**整节点重跑**，非幂等副作用须包 `@task` 并设 `durability="sync"`） |
| 组织与角色建模 | **Clawith**（同技术栈）+ **ZevZev**（岗位即代码）+ **CrewAI**（Role/Goal/Backstory 三段式） | Clawith 的 `Relationship`（上下级、谁的话更算数、跨 Agent 申请数据）+ 组织级共享认知层；ZevZev 的 `kind: Employee` manifest（role / runtime / skills / tools / `permission.requireApproval`） |
| 技能与知识绑定 | **DeerFlow `SKILL.md`** + **StaffDeck 的 OKF 分层** | SKILL.md 格式（含 `allowed-tools`）+ 热加载 + 单文件可分享；OKF 五层（原始文档→业务主题→执行手册→业务规则→问答分析）让 AI 区分"硬规则"与"历史参考" |
| 工具注册与权限 | **ZevZev Tool Gateway** + **Clawith L1–L4** + Eino 中间件 | 凭证由网关代理、**永不进 prompt**；员工只"申请能力"，网关切 scope/secrets/audit；工具 metadata 带**破坏性标注**把危险工具卡在审批后 |
| 执行沙箱 | **OpenHands**（容器运行时）+ **DeerFlow**（三档）+ **FastGPT**（生命周期治理细节） | 一会话一沙箱；按"应用+用户"绑定复用、会话级文件隔离、CPU/内存/存储/自动挂起全可配、只读预览走短时链接 |
| 租户隔离与计费 | **Dify 企业版治理清单** + **A2A 1.0 多租户规范** | SSO(SAML/OIDC) + 细粒度 RBAC + SCIM + **防篡改审计日志实时推 SIEM** + 单次调用级全追踪 + Prompt 历史 PII 脱敏 + 租户级配额/计费/访问策略（照这张清单立项不会漏项） |
| 任务中心与交付物 | **A2A 协议** | Task 状态机（`submitted → working → input-required → completed/failed/canceled`）+ **Artifact 交付物** + 签名 Agent Card |
| 对外互操作 | **MCP + A2A** | MCP 做"手"（工具/数据），A2A 做"同事"（跨框架/跨公司派工）；每个工作流自动暴露成 MCP 工具是最省事的对外方式 |

**不该学**：Flowise（**已归档、Cloud 关闭、停止安全维护，且存在 CVSS 9.8 未修补 RCE**）；OpenClaw 作企业底座（个人助手网关：无多租户/无计费/无任务中心，另有高等级 CVE 与技能市场缺陷率报道）；LobeChat / LibreChat / Open WebUI（**本质是对话前端**，没有任务对象/派工/员工模型/计费）；Langflow / Flowise 的"LLM 输出直接 eval"式代码节点；MetaGPT（**开源线实质停更**）；Coze Studio 开源版（无多租户）。

**"看起来像但不是同类"预警**：n8n/Make/Zapier = 集成自动化；LangGraph/AutoGen/CrewAI/AgentScope = 框架（要自己造）；RAGFlow/FastGPT = 检索与知识层；OpenHands/Devin/Claude Code = 编码 Agent；OpenClaw/LobeChat = 个人助手与前端；MetaGPT = 研究工作流。**六类都不能作正面标物，只能作某模块参考。**

---

## 5. 开源平台横评（压缩）

### 5.1 关键维度对比（摘录）

| 项目 | 数字员工模型 | 面向人的任务中心 | 多租户/RBAC/审计/计费 | 沙箱 | 许可（是否 OSI） |
| --- | --- | --- | --- | --- | --- |
| Dify | ❌ 无 | ❌ 无（仅 Human Input 节点） | 企业版才有（含租户级配额计费） | v1.16 起 Linux 沙箱；v1.17 支持 E2B | ⚠️ **修改版 Apache-2.0**（多租户 SaaS 与改 Logo 需商业授权，**非 OSI**） |
| RAGFlow | ❌ 无 | ❌ 无 | 有角色/共享/审计；**无用量计费** | 需装 gVisor 才可用沙箱 | ✅ Apache-2.0 |
| FastGPT | ❌ 无 | ❌ 无 | 有多租户与权限；**无用量计费** | v4.16 重做代码沙箱（工程细节最好） | ⚠️ Apache 2.0 + 附加条件 |
| n8n | ❌ 无 | ❌ 无（只有 execution 列表） | **RBAC/SSO/审计锁定付费层** | Task Runner | ⚠️ **Sustainable Use License**（非 OSI；禁对外托管收费） |
| LangGraph | ❌ 无 | 🟡 thread + checkpoint + `interrupt`（状态机地基，不是产品） | 框架**无任何** | 无（LangSmith 侧单独计量） | ✅ MIT（框架） |
| CrewAI | 🟡 最接近但只有代码对象 | 🟡 Task 有对象/状态，无派工看板 | OSS 无 | 无原生强沙箱 | ✅ MIT |
| OpenHands | ❌ 无 | 🟡 有 `task_tracker`（Agent 自用） | OSS 无；Cloud/Enterprise 另算 | **★最强**（Docker/K8s runtime） | ✅ MIT(core)，企业版 source-available |
| AgentScope | ❌ 无 | ❌ 无 | 无 | ✅ 内置 runtime sandbox | ✅ Apache-2.0 |
| Coze Studio | ❌ 无 | ❌ 无 | ⚠️ **开源版仅单账户** | ❌ 开源版无 | ✅ Apache-2.0 |
| DeerFlow | ❌ 无 | 🟡 `write_todos`（Agent 自用清单） | ❌ 无 | ✅ 三档 | ✅ MIT |
| **StaffDeck** | **★最完整**（工号/职责/权限/部门/能力画像） | ✅ SOP 状态机（含转人工、版本、断点恢复） | 有操作日志；多租户**未核实**；无计费 | 未核实 | 🛑 **AGPL-3.0** |
| **Clawith** | **★强**（`soul.md`/`memory.md`/Focus/Triggers + Relationship 组织架构 + 20+ 岗位模板） | 🟡 Focus Items（无交付物/派工看板） | ✅ 多租户 RBAC + 用量配额 + 审批流 + 审计 + SCIM | 有独立工作空间 + L1–L4 权限边界 | ✅ Apache-2.0 |

### 5.2 唯一完整的"任务规范"是协议而非产品

【事实】**A2A 1.0**（2026-03）已随 MCP 一同归入 Linux Foundation 的 Agentic AI Foundation；1.0 新增**多租户、版本协商、多协议绑定（JSON-RPC/gRPC/HTTP+JSON）、签名 Agent Card**；其**三个原语（Agent Card / Task 状态机 / Artifact 交付物）几乎就是"任务中心 + 对外互操作"的现成规范**。
【判断】建议**直接采用 A2A 的 Task/Artifact 作为任务对象模型**，使任务中心天然对齐行业标准、外部平台可直接派工。

### 5.3 交集空白判断（本次最关键的一问）

【判断】**截至 2026-09-15，没有任何一个开源项目同时具备「数字员工一等公民模型 + 企业级任务中心 + 多租户审计计费 + 强沙箱执行 + 对外互操作」五要素。** 逐项：
1. **数字员工一等公民模型** → Dify/RAGFlow/FastGPT/n8n/LangGraph/AutoGen/AG2/CrewAI/OpenHands/AgentScope/MetaGPT/Coze Studio/DeerFlow **全部为「无」**；只有 StaffDeck、Clawith、ZevZev、Foundry 真做了，且都是 2026 年新项目、社区极早期（46★ / 325★ / 仅官网 / 未核实）。
2. **企业级任务中心** → 无一家完整；最接近的四种"半个"是 LangGraph（状态机）、DeerFlow（`write_todos`）、Clawith（Focus Items）、**A2A（唯一完整，但是协议不是产品）**。
3. **多租户 + 审计 + 用量计费** → 开源侧**全部缺失**；Dify 在企业版且源码多租户被许可证禁止；n8n 锁在付费层；FastGPT/RAGFlow 有租户/角色但**无计费**。
4. **工具执行闸门 + 容器沙箱** → 碎片化，**没有一个把"多级校验流水线"做成显式闸门**（Clawith 的 L1–L4 + 高危操作人工审批卡最接近）。
5. **对外互操作** → 这块**反而最成熟**（MCP 已是标配，A2A 已成行业标准）。

**【判断】结论**：我们要做的是一个**真实的空白位**，但每一块都已有可抄的实现——**只是散落在三个不同派系里**。因此正确做法**不是 fork 任何一个项目当底座**（Dify 许可禁多租户、n8n 许可禁对外托管、Coze 开源版无多租户、StaffDeck 是 AGPL、Flowise 已死），而是**按模块指定"抄谁"**（§4.5）。

---

## 6. 「AI 资产中心」四件套（= M2 沉淀层）落地判断

### 6.1 逐块判断

| 资产块 | 判断 | 依据（简） |
| --- | --- | --- |
| **记忆与画像** | **底层可集成；「决策逻辑/思考方式」层必须自建** | Mem0（Apache-2.0，`ADD/UPDATE/DELETE/NOOP` 记忆决策引擎）、Graphiti（Apache-2.0，时敏知识图谱）、Letta（Apache-2.0）、Cognee、LangMem 均已生产可用；但**原子单位都是事实/偏好/实体/事件**，程序记忆只有"自由文本 prompt"一种载体——**无 schema、无归因、无冲突消解、无可检验性** |
| **知识库** | **引擎可集成；治理层与"经验条目"建模必须自建** | RAGFlow（DeepDoc 版面理解）/Dify/LlamaIndex + Ragas 覆盖解析、混合检索、重排、评测；但**生命周期治理与经验 schema 无现成品** |
| **可复用工作流** | **引擎可集成；"版本化 + 参数化 + 模板治理"自建薄层** | n8n（**官方无原生版本化，Community 仅留 24 小时**；社区用 GitOps 补）、Dify（草稿/发布分离、**每个发布版本独立 API 端点**、DSL 导出）、Coze Studio（**工作流商店已下架**）、LangGraph（checkpointer + time travel）；**治理标准可照抄 Dify 插件生态**：准入校验清单 + 版本双字段（`meta.version` / `minimum_*_version`）+ 依赖 OSV 扫描 + 风险可见 |
| **AI 员工** | **必须自建数据模型，但路径已标准化（可照抄商业侧）** | 开源侧无完整五要素实现；商业侧（Copilot Studio + Agent 365、Agentforce、AWS Agent Registry、Entra Agent ID）已把身份、sponsor、生命周期、注册表、审计做成标准动作 |

### 6.2 建议的"经验条目" schema（自建）

【判断】建议字段：`原则/判断 → 触发情境 → 依据/证据 → 反例与边界 → 置信度 → 时效 → 来源（哪次运行/哪份文档/哪次决策）→ 版本`；变更走 **`supersede`（软删旧条目并链到新条目）**，不做"两版并存"或"直接删除"。写入走**人工在环**（不让 LLM 自动改写人格）。**身份类画像不进检索、必须每轮常驻**（不能靠相似度命中运气）。
依据：LangMem 情景记忆结构（`observation/thoughts/action/result`）+ Mem0 的 `ADD/UPDATE/DELETE/NOOP` 思路 + 知识治理的 supersede/archive 原则。

### 6.3 知识治理最小可用集（自建）

【判断】**发布时强制要求 `owner` 与 `status` 字段存在**（最能防孤儿页）；生命周期 `草稿 → 已发布 → 复核中 → 陈旧/待复核 → 归档`；**复核由事件触发而非日历**；**过期内容必须从检索谓词下线（`status='PUBLISHED'` 过滤），只归档没用**；Freshness Index（按期复核率）作一等运营指标。
依据：一份 143 人调研显示 **76% 的受访者遇到过 AI 引用过期文档并自信地给出错误答案**（第三方调研，见 §11）。

### 6.4 权限过滤（最易出安全事故的一环）

【事实·共识明确】**必须放进检索谓词（pre-filter）**，不能"生成后过滤"（等于 LLM 已读到机密内容）、也不能"召回后裁剪"（破坏 top-k 与排序分）；稠密与稀疏检索**共用同一个 RBAC 过滤构造器**；clearance 从已校验的身份断言取，**忽略客户端传入的 clearance**；语义缓存 key 须带 clearance 与**授权策略 epoch**。
依据：Microsoft ISE 把 SharePoint 文档级权限**物化成索引字段**（用 Entra ID GUID 而非邮箱做稳定匹配）并承认**权限会陈旧、须周期性重摄取**；Atlas 的 negative-access hard gate（低权限用户问"只有机密文档能回答"的问题，正确行为是**有依据地拒答**，泄漏即失败构建）。

### 6.5 最有价值的连接（护城河在哪）

【判断】**主答案：知识库（经验/踩坑库）× 工作流。** 理由：① 这是唯一能自证价值的闭环——工作流运行天然产出客观证据（成功/失败、成本、耗时、人工修正），其他三块的价值都是主观叙述；② 它把知识库从"检索源"升级为"生产资料"（每次运行回写新经验，含反例与边界）；③ **复制不了的部分在这里**——竞品能抄模型、抄功能、抄模板，**抄不走"你跑了 N 次留下的运行轨迹 + 修正记录 + 评测基线"**。这与 `moat-boundaries.md` 判据②「越用越强」同构。
【判断】**次答案（长期）：画像 × 工作流**（画像提供判断偏好作参数，工作流提供可执行载体与可验证性）；但判断层表示法尚不成熟，**建议先在工作流里以"参数化规则集 + 人工在环"起步**。
【判断】**AI 员工的定位**：它是前三块的**交付形态**（`role = 权限域 + 技能包 + 知识域`），**本身不是护城河来源**。

⚠️ **一个必须写进风险的反证**：目前**记忆没有可移植标准**，能导出的是聊天转录，**派生的画像导不出去**。→ "资产增值"成立的前提是**我们自己就是持有并可导出画像的那一方**。这既是风险（若把资产放在外部 SaaS 上会被锁死），也正式我们该占的位置（与 M2「不可外包」一致）。

### 6.6 最可能踩的三个坑

| # | 坑 | 规避做法 |
| --- | --- | --- |
| 1 | **画像降维成营销标签**（`{role,language,industry,preferences}` 这类 KV，把"思考方式"寄希望于自动推断） | 画像拆三类互不合并：身份类（KV，同键覆盖，**不进检索、每轮常驻**）/ 规则类（整段文本，**写入强制人工在环 + 版本快照可回滚**）/ 事实类（短句 + 向量，可累积可 `supersede`） |
| 2 | **知识库无治理**（上架即"完工"，无 owner、无复核、归档了但还能被搜到） | **发布前强制 `owner` + `status` 存在**；事件触发复核；**过期内容从检索谓词下线**；Freshness Index 作运营指标 |
| 3 | **工作流不可版本化 + 权限绕过**（模板随手改、线上崩；工作流用高权限服务账号跑导致越权；改判断逻辑无审计痕迹） | 工作流 DSL **进 Git 作唯一真源** + 草稿/发布分离 + 发布版本独立端点 + 命名版本永久保留；**复用必须参数化**（提交前自动校验无凭据/无硬编码 URL/有 Input-Output 说明与错误处理）；**权限走用户委托模型**（agent/工作流权限 ≤ 触发者权限） |

---

## 7. 沙箱与执行安全 → 见专文

本节结论**不在此重复**，因为需要落到具体裁决：**→ [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md)**。

此处只留三条必须记住的：
1. 【事实】**共享宿主内核的容器"三判据"第③条无法闭合**，要闭合只能换边界（microVM / gVisor）。
2. 【事实】**Windows 桌面端有两条穿透通道**：WSL2 的 drvfs 默认把整个 Windows 盘挂进 `/mnt/c`；`cmd.exe`/`powershell.exe` 经 unix socket 交回宿主执行（Claude Code 官方要求先装 seccomp 拦 unix socket）。**微软 MXC 官方 README 原文："no MXC profiles should be treated as security boundaries currently"**。
3. 【判断】**本项目规格已声明"沙箱不是安全边界"（§15 #2），因此发现 2 不构成推翻，只要求把声明变成取证 + 写出升级触发条件。**

---

## 8. 开源治理与商业化

### 8.1 "好项目"判据（可打分清单，摘录 15 项）

完整清单见调研明细（来源：CHAOSS Viability、OpenSSF Scorecard）。对**个人/小团队最致命的两项**：
- **Bus factor ≥ 2（最好 ≥ 3）** —— 单维护者会让企业采购直接否掉；
- **可持续的资金/治理（谁付电费？有无赞助/企业支持/基金会归属？）** —— 必须明确写出来。

【事实】Star 数与健康度可严重背离：一项对 74 个开源项目的时间演化研究显示，Ollama（约 25 万 star）社区健康度排 **68/74**，其月活贡献者从峰值 1,128 降至约 150、核心开发者从 102 降至 13，而 vLLM star 不到其一半却排第 7；该研究最相关的两个维度是「**维护者健康度**」(r=0.817) 与「**人员流动**」(r=0.755)。

### 8.2 许可证建议（含必须避免的坑）

【判断】**核心仓 `Apache-2.0`；企业能力（SSO / 细粒度 RBAC / 多租户隔离 / HA / 合规导出 / SLA）独立闭源仓库（必要时不同进程边界）。**
理由：① Apache-2.0 是**同时满足"企业法务零摩擦"与"有专利授权"**的组合（MIT 缺专利条款；GPL/AGPL 会让企业法务走审批）；② 个人项目阶段**最大风险不是"被云厂商抄"而是"没人用"**，分发 > 防御；③ 把"多租户 + 对外托管"这一**行为边界**放到独立企业版授权，**不必污染核心仓的开源许可证**（也避免 Dify 那种"开源许可证里塞商业条款、贡献者条款单方面可改"引发的法务争议）。
**备选**：若产品天然是可被云厂商一键商品化的托管服务 → `AGPL-3.0 + 商业双授权`（Grafana/Mattermost/Bitwarden 模式）；若确信会遇到云厂商白嫖 → `BUSL 1.1（带 4 年转 Apache-2.0）`，代价是不能自称开源。**不要自造许可证。**

**必避十坑（摘录最相关）**：① 仓库里**没有 LICENSE 文件** = 法律上"保留所有权利"（**本仓库当前即无任何 LICENSE/NOTICE/CONTRIBUTING/SECURITY 文件——2026-09-15 实测**）；② 依赖里有 GPL/AGPL 却要做闭源分发或 SaaS；③ 选了 copyleft 却没做 CLA/DCO，日后想双授权/改许可时**需要每一位版权人同意**（做不到就锁死）；④ 只在 README 写一句"Apache 2.0 修改版"而无 LICENSE 全文；⑤ 项目名/商标未查；⑥ 前端/文档/示例的第三方素材授权不清；⑦ 发布产物夹带密钥/`.env`/真实数据（**密钥一旦进仓库要作废重发，不是删掉那一行**）；⑧ 忘 `NOTICE` 与修改声明；⑨ 一边用 BUSL/ELv2/SUL 一边自称"开源"（招致 fork 且被企业标为供应链风险）；⑩ 许可证与贡献者条款可被单方面收紧。
**【判断】"改许可需要所有版权人同意"——这件事越早做越便宜。**

### 8.3 差异化机会（结合我们已有能力）

| # | 机会点 | 依据（谁没做 / 为什么难） |
| --- | --- | --- |
| ① | **真沙箱执行 + 工具闸门 → 可审计的执行网关** | Coze Studio README 自曝公网部署风险（账号注册、Python 节点执行、SSRF、API 水平越权）；Dify 有未认证 SSRF 通告；腾讯 ADP 要"静态扫描+数据访问+网络出站+依赖白名单+多级审批"才敢上架技能。**这是同时命中"安全+合规+成本控制"三张牌的能力** |
| ② | **数字员工「岗位—权限—技能—知识」→ 数字岗位说明书 + 人机协同工作舱** | 信通院报告转述：规模化瓶颈已从模型性能转向**数据与知识质量、系统连接、身份与权限管理、测试与记录机制**，并提出"人机协同工作舱"与"数字岗位说明书"；当前市场大多只做"编排"，**没做岗位与责任建模** |
| ③ | **外部 Agent 调用 → Agent 身份 + 委托授权 + 调用留痕网关** | GB/Z 185 系列（2026-05）明确要求"委托关系可追溯到授权方""校验凭证有效期与授权范围"，并把工具调用统一收口到执行网关；而 MCP/A2A **都不覆盖身份可信层**。**标准刚出、大厂未对齐**（但须先核原文，§11） |
| ④ | **租户级导出/删除 + 审计 → "数据不出域 + 可退出"的合规交付** | 合规是招投标硬门槛（企业选型第一指标"数据安全合规"）；而"能删干净、能导出、能审计"在多数方案里**被含糊带过** |
| ⑤ | **本地优先桌面端（Electron）→ 私有 AI 工作台** | 桌面端天然规避**多租户 SaaS 许可**与**数据出域合规**两道难题；且我们的沙箱 + 闸门 + 岗位权限在桌面端能形成完整体验 |

### 8.4 三件必须避免的事

1. **别做"再来一个 Dify/Coze"的通用平台** —— 国内智能体服务商已超 300 家，同质化严重；大厂用算力/token 补贴 + 生态入口打价格战，个人没有补贴能力与分发入口。
2. **别自训/微调垂直模型** —— 在权重、数据、算力三重劣势下，应做"用模型的人"而非"造模型的人"。
3. **别承诺"全自动无人值守的数字员工"** —— Gartner 预测到 2027 年底 40% 代理型 AI 项目被取消（首要原因"价值无法度量"）；正确姿势是卖"**覆盖率 + 人工兜底 + 可审计**"。
   （第 4 件同样不该碰：以个人身份做多租户公有云 SaaS 卖给大客户。）

### 8.5 切入点优先级

| 优先级 | 切入点 | 依据 | 主要风险 |
| --- | --- | --- | --- |
| 1 | **私有化 / 内网部署（含信创适配 + 轻量化：单机可跑）** | 合规是硬需求且招投标阶段直接淘汰不合规方案；与我们已有的租户级导出/删除/审计天然契合 | 交付重、要售后 |
| 2 | **1–2 个可验收的窄垂直工作流** | "任务与工作流是场景评估基本单元""结果可验收性决定边界" | 不要选资金/合规高风险的全自动场景 |
| 3 | **桌面端本地优先工作台** | 规避许可与合规两道难题 | 分发与变现较慢 |
| 4 | **做"能力层"让别人集成你**（执行网关 / Agent 身份与委托 / 审计证据链），MCP Server 当获客通道 | MCP 已是工具调用事实标准；身份与委托的标准语言刚出 | 需要先有标准理解与耐心 |

---

## 9. 建议的迭代路线（对齐既有编号，不新造体系）

| 档 | 做什么 | 依据 |
| --- | --- | --- |
| **P0（先做，不写代码）** | 把「资产中心」的**资产数据模型与权限模型**写进真源：四块共用"资产 + 归属 + 可见范围 + 版本"基础字段；`岗位 = 权限域 + 技能包 + 知识域 + 配额 + 生命周期`；记忆分三类互不合并 | 宪法"地基不随手翻"；§6 |
| **P1（架构裁决，最阻塞）** | **沙箱边界裁决** + 逃逸用例进 CI | → [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md) |
| **P2（最低成本见效快）** | 工作台暴露为 **MCP server** + 落地 `SKILL.md` 技能包格式 + 派工五护栏 | §4.1、§4.4 取向 3 |
| **P3（主攻 = M2 沉淀层）** | **资产中心四件套**：记忆层 → 技能层 → 经验条目 schema 与工作流回写闭环 → 评测集 | §2 发现 1、§6.5 |
| **P4（增长/合规基础件）** | 补 `LICENSE`/`NOTICE`/`CONTRIBUTING`/`CODE_OF_CONDUCT`/`SECURITY.md`/CLA-DCO + 许可证选型（核心 Apache-2.0 + 企业能力闭源） | §8.2；**越早做越便宜** |
| **P5（差异化切入）** | 私有化/轻量化 → 窄垂直 → 桌面端 → 能力层 | §8.5 |

---

## 10. 与既有真源的关系

| 文档 | 关系 |
| --- | --- |
| [`moat-boundaries.md`](moat-boundaries.md) | **上位**：本报告的最高价值结论（想法⑨ = M2 沉淀层）直接引它；报告**不改变**其 M1–M4 判定 |
| [`capability-ownership-map.md`](capability-ownership-map.md) | **配套**：本报告 §3 的"现状"列引用其行号；FlowGram / AIO Sandbox / MCP server 若启用，**须先按该表 §3 规则 1 补一行** |
| [`open-source-agent-platform-research.md`](open-source-agent-platform-research.md)（2026-09-09） | **前次调研**：本报告是它的**增量**（新增字节系深挖、沙箱红队资产、资产中心四件套、治理与许可证）；两份对 RAGFlow/AgentScope 的定位判断**不冲突** |
| [`2026-09-12-dsh-integration-design.md`](superpowers/specs/2026-09-12-dsh-integration-design.md) | **在飞规格**：§3.3 / §15 #2 是沙箱裁决的事实基线；本报告不直接修改它 |
| [`architecture.md`](architecture.md) | **判据来源**：外部集成三模式（接适配器 / 搬代码 / 只读研读） |

---

## 11. 未核实清单（不得当作已证事实引用）

1. 各项目的 **contributors 数量**（全部未核实）。
2. **许可证未逐一读 LICENSE 文件的对象**：kitex / hertz / netpoll / volo / abcoder / dynamicgo、veADK-Go / veADK-Java、agentkit-sdk-python、volcengine 系多数 SDK、FlowGram、MineContext、`agent-infra` 组织归属（仅 eino、eino-examples、veadk-python 有明确来源）。
3. **Coze Studio 开源版**：是否支持接入外部 MCP Server（证据冲突）；是否有代码沙箱（未核实到）；其"开源版缺什么"来自第三方评估而非官方声明。
4. **DeerFlow**：是否支持 A2A（倾向"不支持"）；`buzz` 渠道性质；Issues/PR 拆分（来自第三方镜像页，抓取日期未知）。
5. **UI-TARS**：模型权重的商用许可（代码 Apache-2.0 ≠ 权重许可）；Remote Operator 免费服务 2025-08-20 下线（第三方教程口径）。
6. **CozeLoop 自托管开源版与商用 SaaS 的能力边界**。
7. **市场与行业数字**（IDC 449 亿元 / 3320 亿元、千问 32.1% 份额、130 万 Agent、桌面端 6,000 万次访问、76% 过期文档调研、n8n ARR $40M 与 55/30/15 拆分、Dify 1.4M 机器/175 国家、HiAgent"私有化份额第一"）：**均为行业文章或第三方研究转述，未见付费原始报告**；n8n 的 ARR 来自第三方机构 Sacra 估计，非公司披露。
8. **GB/Z 185.1～185.7—2026《人工智能 智能体互联》系列**：仅拿到二手转述（发布日期 2026-05-22、7 个分册、牵头单位与参与企业名单），**未核原文**。若要作为设计依据，**必须先取原文**。
9. **事故案例**（Replit / PocketOS / Mythic Society / Amazon Q / OpenAI 评测 Agent 入侵 HuggingFace / GuardFall）：**多为二手报道或社区研究**，未逐字核对原始 issue 或原始报告；PocketOS 停机时长各来源口径不一。
10. **沙箱性能与启动开销数字**（Firecracker 125ms vs 100–200ms、Cube Sandbox <60ms 等）：不同来源区间不一致，**建议以自测为准**。
11. **本仓库的"✅已交付"项**：沿用 `capability-ownership-map.md` 自述，**未逐项复核**。
12. **EICAR 式的"标准沙箱逃逸测试文件"、ISO/NIST 的"AI Agent 沙箱逃逸认证清单"**：**未核实存在**。

---

## 12. 待裁决项（本报告不擅自决定）

| # | 待裁决 | 材料 |
| --- | --- | --- |
| **R1** | **沙箱边界**：维持"强化容器 + 明确声明不是安全边界"，还是升级 microVM | [`sandbox-boundary-decision.md`](sandbox-boundary-decision.md) |
| **R2** | **资产中心是否立为下一阶段主攻（= M2 沉淀层 P3/P4/P6 立项）** | 本报告 §3 第 ⑨ 行、§6 |
| **R3** | **是否开源、以何身份开源**（影响 P4 的全部动作与增长路径） | 本报告 §8.2 / §8.5 |
| **R4** | **对外互操作走 MCP server 还是等 A2A**（建议先 MCP） | 本报告 §2 发现 3、§4.4 取向 3 |
| **R5** | **FlowGram（画布）与 AIO Sandbox 是否引入**（若引入须按 `capability-ownership-map.md` §3 规则 1 先补行 + 评审） | 本报告 §4.1 |
| **R6** | **GB/Z 185 系列是否取原文作为"委托授权链"设计依据** | 本报告 §11 第 8 条 |
