# 路线图（ROADMAP）

> **性质声明（先读这一段）**：
> 1. 本文为**内部路线图**，**不构成任何承诺**——**不代表发布日期、不代表功能承诺、不代表排期**；
> 2. **唯一真源仍是 [docs/feature-inventory.md](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)**（期次与能力六要素）与
>    [立项文档](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs)（"做什么 / 不做什么 / 边界"）。**本文与真源冲突时以真源为准**；
> 3. 本文**不含对外口径**：任何对外表述（客户材料、商务方案）须**另行评审**后再写，不得直接引用本文；
> 4. 未开工期次**不得**读成"即将交付"；已交付能力**需以该能力的验收证据为准**，不以本文陈述为准。

## 一、产品边界（不做的事，与做的一样重要）

本项目是企业内部的**数字员工控制平面**：统一入口、身份、岗位、权限、任务、审批、通知、用量与审计；
主员工端为 Windows 桌面端，网页端用于管理与远程协作，手机端（PWA 伴侣）**只做登录、待办与审批**。

**现有客户端（4 个，如实登记）**：`admin-web`（管理视角）/ `workbench-web`（**员工视角**：我的工作台 / 我的数字员工 / 知识库 / 团队协作）/ `companion-pwa`（手机伴侣）/ `desktop`（Electron 安全壳）。
⚠️ **`admin-web` 与 `workbench-web` 的功能重叠与收敛方案属未决项**（见 `docs/contracts/decision-log.md` D-050⑤），本节**只登记、不定分工**。

**明确不做 / 明确边界**：

- GEO 项目、客户项目与实验项目**各有独立仓库**，本仓库**不合并、不引用**其代码历史；**GEO 本期暂不考虑**（用户 2026-09-22 裁决），后期作为**版本化适配器**接入；
- **CRM 不属于本期工作台产品边界**（用户 2026-09-22 裁决），后期作为**独立系统**通过版本化适配器接入。⚠️ **注意**：`app/crm/`（4,836 行）+ `admin-web/src/features/crm/`（16 文件）+ 5 张迁移表的**代码仍在仓库中**——"剥离"是**产品边界决策，不等于现在删代码**；**现有代码的处置（保留 / 归档 / 删除）属待裁决项**（见 `docs/contracts/decision-log.md` D-050③）；
- **不实现**风控规避、设备伪装与代理轮换（依据 [docs/architecture.md](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md) 发布边界）；
- **不搬**外部项目代码：外部能力一律"接适配器"；强传染 / 非商用许可**只读研读**；
- **不把**用户本机 CLI 当执行引擎（会带进第二套用户、权限与审计）。

## 二、当前阶段（已完成 / 已交付，均以各自验收证据为准）

| 期次 | 内容 | 状态 | 证据入口 |
| --- | --- | --- | --- |
| P1 | 数字员工配置 + 对话层 + 首页改造（`MockRuntime`，不执行真实工具） | 已交付 | [feature-inventory.md §3.1](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md) |
| P2a-1 | 治理收口（四档风险刻度 + `risk_threshold` + 授权位机制 + 前端常驻外壳） | 已交付 | 同上 §3.2 |
| P2a-2 | dsh 接入段（隔离容器执行 + 工具目录九步闸门 + dsh 适配器 + 对话入口路由） | 已实现（**≠ 已过门禁 / 可上线**，见该节自注） | 同上 §3.3 |
| P2b | 实时流 + 过程事件（SSE + PG 流帧） | 已交付（后端） | 同上 §2 期次表 |
| P2c | 前端交互模型改造与内容级呈现（六批） | 六批全部已交付 | 同上 §2 期次表 |
| P3 | 记忆层 + 个人知识库接 `pgvector` | **已交付**（2026-09-15）· **六要素待补** | [P3 规格](docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md) · [feature-inventory.md §2](docs/feature-inventory.md) |
| P4 | 技能层（`SKILL.md` + 注册表 + MCP 客户端 + 白名单审计）+ 沙箱加固 | **已交付**（2026-09-15）· **六要素待补** | [P4 规格](docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md) · [feature-inventory.md §2](docs/feature-inventory.md) |
| P5a | CRM 企业级一期（客户主数据 + 商务主线 + 智能化打底 + 受控工具面） | 已交付（后端 + API + 契约 + 前端五视图） | [feature-inventory.md §3.6](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md) |
| P5b / P5c / P5-二期 | 工单门户 + SLA / 营销自动化 + 触达渠道 / 发票与电子签章 | 待细化（另立规格） | 同上 §2 期次表 |
| P6 | 自进化闭环（评测集基础设施已交付；准入闸门 + 灰度回滚未开工） | P6a 已交付 / P6b 未开工 | [feature-inventory.md §3.5](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md) |

## 三、下一步方向（方向，不是承诺）

1. **把已交付的能力"变可信"**：补齐各期次登记的**未验证项**（真库路径、并发与负载、超时与不可达分支等），
   而不是新增能力面——**新能力强于旧能力可信**是本项目要避免的形态；
2. **交付门禁与真实部署验收**：容器化资产已完成静态校验但**真实镜像构建与容器运行尚未验收**；
   `sandbox` job **尚无 push 触发记录** ⇒ 这两项属"未验证"，需在声称"已容器化交付"之前收口；
3. **对外可用性（若要做客户交付 / 私有化）**：当前 `docs/` 是**内部工程文档**，对外可读性为零 ⇒ 需另立"对外文档与帮助中心"专项；
4. **候选能力**（**未立项，仅登记**）：见 [feature-inventory.md §3.4](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)；
   任何候选纳入都须**单独立项评审**，**不得作为某段次的顺带增量**。
5. **执行模型重构 + 客户端合并**（**规格已出，未评审**）：桌面 + 服务端并存（按"是否需要本机能力"分流；**用户/权限/审计仍只有服务端一套真源**）+ 4 端收敛为「1 份前端产物 + 2 种投递」。
   规格：[`2026-09-22-desktop-execution-and-client-merge-design.md`](docs/superpowers/specs/2026-09-22-desktop-execution-and-client-merge-design.md)；
   台账：[`decision-log.md`](docs/contracts/decision-log.md) **D-051**。**⚠️ 规格未评审、`architecture.md` 未改、`api-contract.md` 未动、逐模块归属待勾选；五项待裁决见规格 §6.1。**
6. **数字员工干线**（**规格已出，未评审**；**产品心脏**）：补 `owner` 归属 + 员工侧创建接口 + 目录开放 + 6 类岗位模板 + 前端接线。
   规格：[`2026-09-22-digital-employee-trunk-design.md`](docs/superpowers/specs/2026-09-22-digital-employee-trunk-design.md)；
   台账：[`decision-log.md`](docs/contracts/decision-log.md) **D-052**。**⚠️ 规格未评审；数据模型复用上一条规格 §3；四项待裁决见规格 §9.1。**

7. **能力来源（外部 skill 的处置口径）**（**规格已出，未评审**；**本文入口是一个口径冲突**）：本轮需求「全网找 skill」与**已评审的 P4 规格**「不建公开技能源下载」直接冲突。规格提出**关键区分**——`SKILL.md` 正文（方法论 = 只读研读自研）vs `scripts/`（代码 = 须许可 + 准入链）。
   规格：[`2026-09-22-capability-sourcing-design.md`](docs/superpowers/specs/2026-09-22-capability-sourcing-design.md)；
   台账：[`decision-log.md`](docs/contracts/decision-log.md) **D-053**。**⚠️ 待裁决 V1（处置口径）是入口；未变更 P4 口径；另有一项确定性付费义务（Remotion）须单独决策。**

8. **沉淀层计量与控制器**（**规格已出，未评审**；**直击「沉淀层没真正起作用」**）：给沉淀层装上**仪表**（`use_count` / `cite_count` / hot·cold 榜）+ **控制器**（零复用 → 标记 → 告警 → **人工**处置）+ craft→skill 硬晋升。
   规格：[`2026-09-22-sedimentation-metrics-design.md`](docs/superpowers/specs/2026-09-22-sedimentation-metrics-design.md)；
   台账：[`decision-log.md`](docs/contracts/decision-log.md) **D-054**。**⚠️ 未变更 P3/P4/P6 任何已评审规格（本文是填空白）；五项待裁决见规格 §10.1。**

9. **信息架构（三栏 · 对话常驻 · 悬浮助手 · 侧栏收敛）**（**规格已出，未评审**；解「**不像一个产品**」）：侧栏 ≤10 入口 / 主区域对话常驻（切走不卸载）/ 右栏当前对象（**收窄，不做通用舞台**）/ 全局悬浮助手。
   规格：[`2026-09-22-information-architecture-design.md`](docs/superpowers/specs/2026-09-22-information-architecture-design.md)；
   台账：[`decision-log.md`](docs/contracts/decision-log.md) **D-055**。**⚠️ 待裁决 V1（保留哪套前端底座）是本文前提——两个前端底座完全不同（AntD vs 手写 CSS），合并涉及 38,689 行。**

> **📋 五份规格的 23 项待裁决已汇总** → [`docs/contracts/pending-decisions-2026-09-22.md`](docs/contracts/pending-decisions-2026-09-22.md)

> **⚠️ 编号说明（2026-09-22）**：上列第 5–9 条属**批次计划**（记作 **`B0`–`B6`**），**不是**本文件的期次号 `P0`–`P6`（期次见 [`feature-inventory.md` §2](docs/feature-inventory.md)）。两套编号**不得混用**——此说明的由来见 [`decision-log.md`](docs/contracts/decision-log.md) **D-052⑪**（曾发生编号碰撞并已更正）。

## 四、维护规则

- 本文**不承载能力清单与权限口径**，只承载"方向与边界"；能力与口径变更**只改真源**，本文同步时**只改方向句**；
- 本文**不写日期承诺**；若需排期，排期落在真源文档的期次表，**不在本文**。