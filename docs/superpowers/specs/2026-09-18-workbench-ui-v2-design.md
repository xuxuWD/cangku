# 工作台界面重做（UI v2：信息架构 + 设计规范 + 逐页重绘） 阶段规格

> **性质**：**阶段规格（唯一真源）· 待评审**。本文定义「前端重做专项」做什么 / 怎么做 / 怎么验收；实现按本文 §6 里程碑推进。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §17.1–§17.3（目标信息架构 / 右侧舞台构成）；[`feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)。
> **取代关系**：本文 §3（信息架构）**取代** [`2026-09-17-frontend-interaction-p2c-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md) §2.17 的侧栏与视图归属口径；该规格的**功能语义**（流、舞台、协作、验收、导出/删除）**全部保留不变**。
> **依据（审计与调研）**：[`ux-audit-batch1-information-architecture.md`](file:///d:/徐徐AI学习/公司工作台/docs/ux-audit-batch1-information-architecture.md)（IA-01～IA-11 实测）· [`ux-audit-batch4-copy-and-help.md`](file:///d:/徐徐AI学习/公司工作台/docs/ux-audit-batch4-copy-and-help.md) · [`audit-coverage-review-2026-09-18.md`](file:///d:/徐徐AI学习/公司工作台/docs/audit-coverage-review-2026-09-18.md)（E4-7 / B-15：本专项此前**完全未启动**）· [`evoflow-runtime-tour-2026-09-18.md`](file:///d:/徐徐AI学习/公司工作台/docs/evoflow-runtime-tour-2026-09-18.md)（实机巡览）· [`p2c-interaction-study.md`](file:///d:/徐徐AI学习/公司工作台/docs/p2c-interaction-study.md)。
> **日期**：2026-09-18
> **状态**：**待评审**。用户已裁决三条：① 走「正式立项」路线；② 视觉基准 = **WorkBuddy 风格**；③ 第一批范围 = **外壳 + 全站 17 页一起重绘**（本文按 M1–M3 三个可验收里程碑组织，全部属于第一批）。
> **前置**：P2c 已交付（迁移 `039` 收尾，六 job 全绿）。**本专项为纯前端专项**：不改后端契约、不改数据库、不改已验收业务语义。

***

## 0. 现状与根因（三条，均有既有证据）

| # | 事实 | 证据 |
| --- | --- | --- |
| 1 | **缺设计阶段**：全仓无设计规范 / 无组件清单 / 无页面模板，每页按"h1 + 描述 + 表格"即兴发挥 | 本专项在审计中被登记为**完全未启动**（E4-7 / B-15）；`admin-web/src/styles/global.css` 53 KB 单文件承载全站样式 |
| 2 | **验收口径偏功能**：单测 + 无障碍 + 对比度做了，"视觉层级 / 主操作是否明显 / 截图级评审"从未做 | audit §3 B 组：「主操作是否明显 ❌ 零命中」「无截图/录屏」 |
| 3 | **心智模型是后台管理系统**：6 组 17 项分组菜单、每功能一页、对话只是其中一页 | 批 1 实测：左栏无主按钮（IA-01）、会话列表不在左栏（IA-02）、点「对话」丢当前会话（IA-03） |

**结论**：不是技术栈问题（React 19 + Vite + TS 与参照产品同类），是**产品设计阶段缺失**。因此本专项的第一交付物是**规范**，不是代码。

***

## 1. 目标、范围、禁止事项

### 1.1 目标

把管理台从「功能页集合」改造成「**以对话为主轴的工作台**」：左栏只放主轴与高频入口，其余收进「更多」；每页骨架统一（标题 + 一句话副标题 + 唯一主操作 + 内容区）；全站视觉达到企业级观感；处处有「? 使用指南」。

### 1.2 做什么

| 层 | 内容 |
| --- | --- |
| 设计底座 | 设计令牌 v2（色 / 字 / 间距 / 圆角 / 阴影 / 动效）+ 组件层（§4.2）+ 五类页面模板（§4.3） |
| 外壳 | 侧栏三段式（主操作 / 主导航 / 会话列表）+ 顶栏（标题 + 主操作 + 使用指南）+ **新增全屏设置页** |
| 17 个既有视图 | 按 §3.2 重新归属与逐页重绘（**页面数量不减少、功能不删**） |
| 文案与帮助 | 去开发者词（批 4 清单）；每页「? 使用指南」（四段骨架）；空态统一口径（§5） |

### 1.3 不做什么（禁止事项）

1. **不搬** WorkBuddy / OpenWorkBuddy / EvoFlow / Trae 的**代码、组件、图片、皮肤、文案、商标**（前两者非商用许可、后两者闭源）——只借**信息架构与交互模式**，页面与视觉**自研**。
2. **不改后端契约**、不加新端点、不改数据库（若确需，先改 `api-contract.md` 再评审）。
3. **不改已验收的业务语义**（流续播、审批判定、协作权限、结构判定、导出/删除口径一律不动）。
4. **不顺手改** `companion-pwa` / `desktop` 的已验收行为（本专项结束后另批对齐）。
5. 不引入前端 UI 框架全家桶（保持零运行时依赖策略；组件层自研，必要时只引 headless 原语并单独评审）。

### 1.4 影响范围

`admin-web/src/**`（全量）；`admin-web/src/styles/global.css` 拆分为 `tokens.css` + 分层样式；`desktop` 与 `companion-pwa` **继承**（零改动）。

***

## 2. 设计基准与许可边界

| 项 | 决定 |
| --- | --- |
| 信息架构基准 | WorkBuddy（左栏「主按钮 + 扁平入口 + 会话列表」三段式；对话为主轴）· EvoFlow（任务看板 / 员工卡片 / 设置全屏页 / 「? 使用指南」四段骨架） |
| 视觉基准 | WorkBuddy 风格的**品质档位**：白底 + 靛紫主色 + 大留白 + 大圆角 + 胶囊控件 + 极轻阴影；**配色、插画、标识全部自研** |
| 许可边界 | 参照产品只用于**只读研读**（不入运行链路、不入仓库）；本专项产出物中**不得出现**其任何素材与文案 |
| 基准素材存档 | WorkBuddy 实机画面：`tmp/workbuddy-shots/`；EvoFlow 实机：`tmp/evoflow-shots/`（临时目录，验收后可删） |

***

## 3. 新信息架构

### 3.1 外壳（三层）

```
┌──────────────┬─────────────────────────────────────────────┐
│ 品牌          │ 顶栏：☰ 标题/面包屑      [页面主操作] [? 指南] │
│ ＋ 新建对话    ├─────────────────────────────────────────────┤
│ ─────────    │                                             │
│ 工作台        │                内容区                        │
│ 对话          │        （按 §4.3 五类页面模板渲染）             │
│ 任务          │                                             │
│ 员工          │                                             │
│ 知识          │                                             │
│ 更多 ▾        │                                             │
│ ─────────    │                                             │
│ 会话列表       │                                             │
│ （常驻·相对时间）│                                             │
│ ─────────    │                                             │
│ 身份 · ⚙设置   │                                             │
└──────────────┴─────────────────────────────────────────────┘
```

- 侧栏宽 **240px**（现 300px），白底 + 1px 右边框，**默认常驻**；≤1024px 折叠为图标栏，≤720px 收进抽屉。
- 「＋ 新建对话」为**每页常驻的主按钮**（首位），点击即进入新会话输入态（落 IA-01）。
- 会话列表**常驻侧栏**，带相对时间（落 IA-02）；点当前模块入口**不丢**已打开会话（落 IA-03）。

### 3.2 17 个视图的归属（页面不减少，只重新归属）

| 侧栏入口 | 承载视图 | 说明 |
| --- | --- | --- |
| **工作台** | `home` | T1：仪表盘（输入卡 + 指标卡 + 待办 + 最近会话） |
| **对话** | `conversation`（+ `run` 详情） | T2：消息流 + 右栏舞台；`run` 为 T4 详情页，从对话/任务进入 |
| **任务** | `workbench` + `history` | T3 两页签合并（任务 / 历史草稿）——同一件事不再两个入口 |
| **员工** | `workforce` + `workforceSettings` | T3 卡片网格 + T4 配置页（页内进入） |
| **知识** | `knowledge` | T3 |
| **更多 ▾** | `dynamics` / `inbox` / `audit` / `billing` / `crmAccounts` / `crmOpportunities` / `crmQuotes` / `crmContracts` / `crmProgress` | T3 列表（`billing` / `crmProgress` 为 T1+T3） |
| **⚙ 设置（新增全屏页）** | 外观 / 帮助与反馈 / 账号（收纳现有主题切换、HelpPanel、身份区） | T5；**不新增功能**，只换落位 |

> URL 模型保持 `?view=`（含 `&conversation=`），深链与浏览器后退语义不变（批 1 G-01～G-03 不得破坏）。

***

## 4. 设计规范 v2

### 4.1 设计令牌（`tokens.css` 全量替换；浅色为默认，深色同构覆盖）

| 组 | 令牌 | 值 |
| --- | --- | --- |
| 主色 | `--accent` / `--accent-hover` / `--accent-soft` / `--accent-fg` | `#4F46E5` / `#4338CA` / `#EEF2FF` / `#FFFFFF` |
| 背景 | `--bg-app` / `--bg-sidebar` / `--bg-card` / `--bg-subtle` / `--bg-hover` | `#FFFFFF` / `#FAFAFB` / `#FFFFFF` / `#F4F4F6` / `#F2F3F7` |
| 描边 | `--border-soft` / `--border-strong` | `#E7E7EC` / `#D9D9E0` |
| 文本 | `--fg-primary` / `--fg-secondary` / `--fg-muted` | `#111827` / `#6B7280` / `#9CA3AF` |
| 状态 | `--success` / `--warning` / `--danger` / `--info`（各带 `-soft` 淡底） | `#16A34A` / `#D97706` / `#DC2626` / `#2563EB` |
| 圆角 | `--radius-control` / `--radius-card` / `--radius-pill` / `--radius-inset` | `10px` / `14px` / `999px` / `8px` |
| 间距 | `--space-1..8` | `4 / 8 / 12 / 16 / 20 / 24 / 32 / 40` |
| 阴影 | `--shadow-pop` / `--shadow-modal` | `0 8px 24px rgba(17,24,39,.08)` / `0 24px 60px rgba(17,24,39,.18)`（卡片**不用阴影**，靠 1px 边框） |
| 动效 | `--motion-fast` / `--motion-normal` | `140ms` / `200ms` |
| 字号 | `--text-hero` / `--text-title` / `--text-body` / `--text-aux` / `--text-micro` | `26px/700` / `15px/600` / `14px/1.6` / `12px` / `11px` |

深色主题（`data-theme="dark"`）：底 `#0B0B0F` / 侧栏 `#121218` / 卡片 `#16161D` / 边框 `#26262F` / 主文字 `#F3F4F6` / 主色 `#818CF8`。**明暗同构：同一套结构，只换令牌。**

### 4.2 组件清单（首批必须落地；同类 UI 出现 >2 次即抽组件）

外壳：`AppShell` · `Sidebar` · `NavItem` · `PrimaryAction` · `TopBar` · `Breadcrumb` · `UserMenu`
基础：`Button`（primary / secondary / ghost / danger × loading / disabled）· `IconButton` · `Segmented` · `Chip` · `Badge` / `StatusDot` · `ProgressBar` · `Avatar`
表单：`Input` · `Textarea` · `SearchBox` · `Select` · `Checkbox` · `FormField`（标签 + 说明 + 错误）
容器：`Card` · `Section` · `Tabs` · `ListRow` / `DataTable` · `Timeline` · `Modal` / `ConfirmDialog` · `Toast` · `Drawer`
反馈：**`EmptyState`（自研 SVG 插画 + 标题 + 一句解释 + 主/次按钮）** · `LoadingState` · `ErrorState`（可重试）· `NoPermissionState` · `GuideCard`（使用指南）
业务：`Composer`（对话输入卡）· `MessageBubble` · `StagePanel`（右栏）· `MetricCard` · `ApprovalCard` · `ArtifactChips`

### 4.3 五类页面模板

| 模板 | 骨架 | 适用 |
| --- | --- | --- |
| **T1 工作台/仪表盘** | 大标题 + 场景胶囊 + 快捷 chip 网格 + 大输入卡 + 指标卡行（3–5）+ 待办/最近区 | `home`、`billing` 头部、`crmProgress` 头部 |
| **T2 对话** | 消息流（气泡 + 相对时间 + 用量小灰字）+ 右栏舞台（可折叠）+ 富控件输入卡 | `conversation` |
| **T3 列表/看板** | 标题 + 副标题 + **统计条** + 页签 + 筛选行 + 表格/卡片网格 + 空态（插画 + 主次按钮） | 任务、历史、员工、知识、通知、审计、CRM、协同动态 |
| **T4 详情** | 面包屑 + 标题 + 右侧操作 + 分区卡片（概览 / 明细 / 历史） | `run`、`workforceSettings` |
| **T5 设置** | 左分组导航（基础 / 能力 / 关于）+ 右内容区 | 新增设置页 |

**每页统一铁律**：① 唯一主操作，视觉权重最高；② 右上角必有「? 使用指南」；③ 四态齐备（加载 / 空 / 错误 / 无权限）；④ 只用令牌，零硬编码颜色。

***

## 5. 文案与帮助体系

1. **去开发者词**（批 4 清单）：生产产物中不得出现「桩回复 / P1 / 数据模型 / 后端 / 接口 / 422」等；能力边界改用业务语言（例："当前为演示回复，尚未接入真实模型，请联系管理员开通"）。
2. **「? 使用指南」四段骨架**（借 EvoFlow 实机模式）：`⏱ 30 秒上手` → `1 这是什么` → `2 什么时候用` → `3 最短怎么用`；每段结尾给**退出路径**（"只想问一句 → 回工作台直接说"）与**兜底**（"不会点 → 直接对数字员工说……"）。
3. **空态口径**：插画 + 一句解释（为什么空）+ 主/次双按钮（例：`创建空白任务` / `从模板创建`）。
4. **术语统一**：一套词表（对话 / 任务 / 员工 / 知识 / 审批），"内容工作台 / 历史草稿 / 伴侣端"等内部叫法一律不进用户界面。

***

## 6. 里程碑与验收

> 第一批 = 外壳 + 全站 17 页（用户裁决）；按下列三个里程碑组织，每个里程碑**可独立验收、可独立回滚**。

| 里程碑 | 范围 | 验收标准（可检查） |
| --- | --- | --- |
| **M1 设计底座 + 外壳 + T1/T2** | 令牌 v2 · 组件层 · 外壳三段式 · 全屏设置页骨架 · 工作台首页 · 对话页（含右栏） | ① 任意页面左栏首项为「＋ 新建对话」，键盘可达；② 左栏任一入口 ≤1 次点击到达；③ 每页唯一主操作；④ 每页有「? 使用指南」；⑤ 四态齐备；⑥ 截图归档（1440×900 + 1024×768 + 深色） |
| **M2 列表与看板 10 页** | 任务 / 历史 / 员工 / 知识 / 通知 / 审计 / 协同动态 / CRM 四页 / 用量 | 同 M1 五条 + **统计条与页签可用** + 空态插画与双按钮 + 列表有数据时的不折行核对 |
| **M3 详情与设置 + 全站收口** | 运行详情 / 数字员工设置 / 设置页完整 + 文案与帮助体系全站 + 视觉验收 | 去开发者词**零命中**（机检）；对比度 ≥4.5:1（正文）；深色与浅色同构；全量回归（既有 267 条前端用例不破） |

**每批必须附**：截图（浅色 + 深色 + 两档视口）· 走查记录（主流程 + 故意走歪路）· **反假测试**（见下）· 未验证项登记。

### 6.1 接缝 S1–S6（**用户已裁决并入本专项**，2026-09-18）

明细见 [`2026-09-18-workbench-closed-loop-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md) §3；**归属如下，随里程碑一并验收**：

| 接缝 | 内容 | 归属 |
| --- | --- | --- |
| **S1** | 审批「三处一致」（对话卡 / 运行详情 / 通知同一权威态；通知可直达该会话的该条卡） | **M1** |
| **S6** | 模式与场景可见（模式做成一等公民 + 斜杠指令最小集 `/new /stop /help /status` + 本会话工具画像可见） | **M1** |
| **S3** | 通知/待办 → 回到会话/运行（7 类目标无死胡同 + 面包屑 + 「回到会话」） | **M2** |
| **S5** | 待办与在岗可见（首页指标卡与员工页横幅同源，点开直达审批） | **M2** |
| **S2** | 交付 → 验收 → 沉淀（交付清单 + 确认完成 / 打回重做；确认后出「存成任务 / 设为自动化」轻量入口） | **M3** |
| **S4** | 干预闭环（暂停 / 恢复 / 取消，二次确认 + 权威态回流，**按钮隐藏 ≠ 权限**） | **M3** |

> **能力项边界（同步裁决）**：C1–C9（资产中心 / 任务驾驶舱 / 应用中心 / 值班调度 / 目标长跑 / 计划闭环 / IM 触达 / 观测排障 / MCP）**本轮不启动**，只在闭环规格 §4 登记。
> **纪律**：上表六条接缝一律走**服务端权威态**，不得用前端本地状态假装闭环；不得破坏既有深链（`?view=` / `&conversation=`）与浏览器后退语义。

**反假测试（本专项的四条，故意造假必须变红）**：

1. 令牌守护：在任一组件里写死颜色（如 `#fff`）⇒ 守护用例**必红**；
2. 主操作唯一：给某页加第二个 `primary` 按钮 ⇒ 页面用例**必红**；
3. 四态齐备：删掉某页空态 ⇒ 该页用例**必红**；
4. 术语守护：往生产文案里注入「桩回复」⇒ 术语用例**必红**。

***

## 7. 待裁决（评审时逐项确认；未确认前按"建议"执行）

| # | 问题 | 建议 |
| --- | --- | --- |
| Q1 | 主色由墨绿改为**靛紫** `#4F46E5`？ | 采纳（WorkBuddy 基准）；若要保留墨绿请在评审时提出 |
| Q2 | 「任务」入口合并 `内容工作台` + `历史草稿` 为页内两页签？ | 采纳（同一件事不再两个入口） |
| Q3 | 首位主按钮叫「＋ 新建对话」还是「＋ 新建任务」？ | **「＋ 新建对话」**（WorkBuddy 的「新建任务」点进去实为对话，已被其自身列为文案债，不学） |
| Q4 | 会话列表是否显示在**所有**页面（含设置页）？ | 采纳（常驻；设置页为全屏页时隐藏，返回后恢复） |
| Q5 | 空态插画用自研 SVG？ | 采纳（不引外部素材，避免许可与风格不一致） |

***

## 8. 风险与未验证（如实登记）

| # | 项 | 说明 |
| --- | --- | --- |
| 1 | **列表页真实数据的视觉验收** | 本机 dev 常为空库（内存仓储）⇒ M2 的"有数据折行/分页"验收需**种子数据**或真库环境；缺此条件时该项标**未验证** |
| 2 | 参考产品的**运行期**行为 | WorkBuddy 闭源未实测；OpenWorkBuddy 与 EvoFlow 仅静态/截图层面的观察 ⇒ 只用于**模式**参考，不当作契约 |
| 3 | 1024×768 以下与 4K/DPI | 承接审计批 5 未覆盖项，M3 至少覆盖 1440×900 与 1024×768 两档 |
| 4 | `companion-pwa` / `desktop` 的视觉对齐 | 本专项**不含**；M3 结束后单独立项 |
| 5 | 前端测试与视觉验收的关系 | 现有 267 条用例保护**行为**；视觉回归靠**截图归档 + 反假四条**，不引入像素比对工具（避免脆弱测试） |

***

## 9. 变更留痕

- 2026-09-18 起草：依据用户三项裁决（正式立项 / WorkBuddy 基准 / 外壳+17 页）落盘；同日补入 WorkBuddy 实机画面自采记录（`tmp/workbuddy-shots/`）。
- 2026-09-18 **M1 交付**：令牌 v2 + 六层样式拆分 + 组件层 + 三段式外壳 + 设置页 + 首页（T1）+ 对话页（T2）+ **S6**（模式一等公民 / 斜杠最小集 / 本会话能力）+ **S1**（审批卡三处共用 + 决议总线）。证据：280 用例全绿、反假 2 处变红、10 张截图（`docs/screenshots/ui-v2-m1/`）、浏览器走查 4 处缺口修复复验。
- 2026-09-18 **M2 交付**：十页 T3 化（任务两页签合并 + 员工 / 知识 / 通知 / 审计 / 协同动态 / 用量 / CRM×5）+ **S3**（通知 7 类落点无死胡同 + 运行详情面包屑「回到会话」）+ **S5**（`GET /approvals/pending` 同源：首页指标卡 + 「等你拍板」区块 + 员工页横幅）。证据：298 用例全绿、反假 2 处、14 张截图（`docs/screenshots/ui-v2-m2/`）、两轮走查修复复验。
- 2026-09-18 **M3 交付（详情与设置 + 全站收口 + S2/S4）**：
  - **S4 干预闭环**：新增 [`RunActions.tsx`](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/runDetail/RunActions.tsx)（暂停 / 恢复 / 取消，取消二次确认、成功后重取权威态、失败就地展示服务端结论、终态不渲染任何按钮），接入运行详情页与对话右栏舞台；`api.ts` 新增 `pauseRun` / `resumeRun` / `cancelRun`，`state.ts` 新增干预专用状态码映射（404 不泄露存在性、409 原样展示服务端原因）。
  - **S2 交付清单（读侧）+ 写侧如实标注**：运行详情新增「交付」区块（产物清单 + 三条件验收判定 + 未达标指引「回对话页一键重做」），并对**尚未交付**的「确认完成 / 打回重做 / 存成任务」写明现状、**不摆假按钮**（写侧需后端新增验收动作，已登记）。
  - **页面收口**：运行详情（T4：面包屑 + 指标 + 运行信息 / 交付 / 审批 / 事件时间线四卡）与数字员工设置（T4/T5：统计条 + 页签 + 卡片化）重绘完成；`VIEW_META` 收口为「**每页唯一 h1**」（`crumb` 形态与页内标题全部删除），`guides.ts` 收口为**全站每页四段**。
  - **全站收口（可复跑机检）**：`npm run check:ui-copy`（用户可见文案开发术语**零命中**，DEV 专属文案按 `ui-copy:dev-only` 豁免）、`npm run check:contrast`（浅/深两套、19 组关键组合**全部 ≥4.5:1**；据此调整 `--fg-secondary` / `--fg-muted` / `--bg-subtle` 与三档状态色，描边仅记录不判定）。
  - **证据**：`316/316` 用例全绿（38 文件 0 skip）、`npx tsc -b` 退出码 0、`vite build` 通过（JS 513KB，仍超 500KB 告警，未 code-split）、反假 2 处精确变红后还原复绿（① 暂停不发请求 ⇒ 3 条用例必红；② 交付区块摆假「确认完成」按钮 ⇒ 用例必红）、10 张截图（`docs/screenshots/ui-v2-m3/`）、脚本化走查 `tmp/m3-walkthrough.mjs` **26/26 通过**（含暂停→恢复→取消主流程、二次确认被拒不发请求、终态无按钮、深色切换、无控制台异常）；独立视觉复核 4 项缺陷（按钮高度不齐 / 判定列锯齿 / 两处表单列宽不一 / 滚动条位移）已修复并复测 **0.00px 偏差**。
  - **未验证（不得读成已验）**：① ~~后端侧 3 条发现~~ → **同日修复 2 条**（`resume` 未捕获授权错误、mock `pause_run` 无状态守卫，见下方「干预动作终态口径收紧」条），**剩 1 条保留**：`pause/resume` 在 **dsh 适配器上是空操作**（无外部暂停契约，如实登记为已知限制）；② ~~S1 第三款（通知直达会话卡）需后端补 `conversation_id/approval_id`~~ → **同日补齐**（见下方「S1 第三款补齐」条）；③ 干预闭环仅在 **mock 运行时 + demo-tenant 种子数据**上实测，未在 dsh / 真实工作负载上验证；④ 极矮视口（<620px 高）为降级布局；⑤ 审计明细的英文字段名与动作码原样展示（离线台账口径），未做业务化改写；⑥ 页面文案里「租户 / 本公司」两种口径并存（含后端返回的固定文案），未统一。
- 2026-09-18 **S2 写侧补齐（运行验收决议，同日续做）**：契约「运行验收决议（S2 · 人工验收）」+ 迁移 [`040_run_acceptance_decisions`](file:///d:/徐徐AI学习/公司工作台/migrations/040_run_acceptance_decisions.sql) + [`acceptance_decisions.py`](file:///d:/徐徐AI学习/公司工作台/app/runtime/acceptance_decisions.py)（内存 / PG 双实现，append-only + 幂等键唯一 + 复合外键租户隔离 + `rejected ⇒ reason 非空` 表级 CHECK）+ 端点 `GET/POST /api/v1/runs/{run_id}/acceptance/decisions`（**只记录不改状态**：仅终态可决议、越权一律 404、审计动作 `run.acceptance_decided` 只记结论与 `reason_present` 不落理由正文）+ 前端 [`AcceptanceDecisionPanel.tsx`](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/runDetail/AcceptanceDecisionPanel.tsx)（确认完成 / 打回重做带原因、服务端权威回流、运行未结束不给按钮、无权限只给说明）。**证据**：后端全量 `2329 passed / 0 failed / 114 skipped`；真库用例（`WORKBENCH_TEST_DATABASE_URL` 指向本机 pg16）15/15 通过（含 2 条新真库用例：幂等+排序、跨租户写被复合外键拒）；真实 HTTP 五类现象实例（正常 200 / 参数错误 422「打回重做必须写明原因」/ 缺身份 401 / 他人读写 404 / 跨租户 404 / 未知运行 404）+ 审计可追（两条审计明细 **不含理由正文**，理由只存决议表）；前端 `327/327`、`tsc` 0、`vite build` 通过；前端反假（去掉真实 POST ⇒ 3 条用例变红）、后端反假（去掉终态守卫 / 去掉幂等审计守卫 / 把理由写进审计 ⇒ 对应 3 条用例分别变红）。**残留（未验证）**：① 「存成任务 / 设为自动化」沉淀入口仍**未交付**（属 C3 应用中心范围，界面已如实标注）；② 决议未派生通知、「待确认」看板属 C2 未立项；③ 前端未在浏览器里连真实后端走查（dev API 进程未重启以加载新路由与 `040` 迁移）——UI 侧证据来自 47 条组件/客户端用例。
- 2026-09-18 **干预动作终态口径收紧（缺陷修复，存量问题）**：此前 `pause` / `resume` / `cancel` 在**已终态**运行上会被静默接受并改写状态（把 `completed` 置回 `running` / `paused`，或把已完成再标 `cancelled`）——与审批侧 `RunNotDecidable`（终态即终态）自相矛盾。本批：`MockRuntime` 三条动作加终态守卫（新异常 `RunNotActionable`）+ 三个端点映射 **409**（`运行已结束，无法暂停 / 恢复 / 取消`）+ `POST /runs/{id}/resume` 同时把 `ExecutionNotAuthorized` 映射为 **409**（原来外抛 500）。**证据**：后端全量 `2333 passed / 0 failed`；反假（去掉终态守卫 ⇒ 2 条用例变红）已复验；契约新增「干预动作的终态口径」小节并**如实登记** `dsh` 适配器 pause/resume 仍为空操作这一限制；7 个既有用例改为用「停在运行中」的运行验证干预路径（原用例因为该缺陷才写得出）。
- 2026-09-18 **S1 第三款补齐（通知点开直达「该会话的该条卡」）+ 两处真缺陷修复**：
  - **补齐 S1**：迁移 [`041_inbox_target_context`](file:///d:/徐徐AI学习/公司工作台/migrations/041_inbox_target_context.sql) 给 `workbench_inbox_items` **只增**两列 `target_conversation_id` / `target_approval_id`（存量行 NULL ⇒ 回落既有落点，零破坏）；运行类通知在 [`_notify_run_terminal`](file:///d:/徐徐AI学习/公司工作台/app/main.py) 里沿 `run_id → 幂等行 → conversation_id` **服务端反查**（取不到一律 `None`，不猜会话），驳回场景由决议端点接入 `approval_id`；`GET /inbox` 视图新增两字段（additive，见契约）。前端：`InboxItem` 增两字段 + `resolveInboxAction` 优先「打开该会话的审批 / 打开会话」（无上文仍回落运行详情）+ `App` 路由支持 `&approval=<id>`（`navigate` 只在显式传入时带上）+ 对话页 `focusApprovalId` 定位、高亮该卡，并对「对不上」如实说明（等服务端运行解析完再下结论，不误报）。
  - **缺陷①（后端，真机发现）**：CORS **不 expose** `X-Stream-Run-Id` ⇒ 跨源时前端读该头恒为 `null`，`useRunStream` 据此**提前关流**（`noData`），历史会话解析不到运行与审批——本机的 5199/5200 → 8100/8111 全部踩中，即 P2c-2 的「运行解析」在**任何跨源部署**下都静默失效。修复：`resolve_cors_options` 两个分支加 `expose_headers`（[settings.py](file:///d:/徐徐AI学习/公司工作台/app/settings.py)），契约「实时流」补「跨源读取」一行。
  - **缺陷②（测试，真库门控下才暴露）**：`test_runtime_events_postgres.py::test_mock_runtime_keeps_sequences_monotonic_across_store_reloads` 靠「暂停/取消一个**已完成**运行」走通——与「终态即终态」的收紧直接冲突（此前的 `2333 passed` 是 114 条真库用例被 skip 的绿，**并未覆盖它们**）。修复：改用「停在运行中」的运行。同批另一条失败（`purge_events_before` 计数 `14 != 2`）**未定位到独立根因**：修完上一条后单文件与全量均绿，推断为跨用例留库的连带；**保留风险登记**——该方法按全局时间窗口计数，库内若存在其它超期事件会影响该断言（本轮未改断言）。
  - **证据**：后端全量（`WORKBENCH_TEST_DATABASE_URL` 指向本机 pg16、**0 skipped**）`2453 passed / 0 failed`；反假 3 处（写死会话反查 / 丢掉 `approval_id` / 去掉 `expose_headers` ⇒ 对应用例分别变红后还原复绿）；前端 `332/332`、`tsc -b` 0、`vite build` 通过、`check:ui-copy` 与 `check:contrast` 通过；**真实浏览器走查 26/26**（`tmp/s1-deeplink-walkthrough.mjs`：通知点开 ⇒ URL 带会话+审批 ⇒ 对话页高亮该卡且同权威态「已驳回」；**刷新后仍高亮**、**深色下高亮环 2px 有效**、点开即标记已读；歪路「对不上的标识」如实说明不误报、不带标识时两不误报；**待批卡深链同样定位 + 发起人不摆决议按钮 + 服务端 403 拒自审且该条仍 pending**；**「更早一次运行」在真实数据上复现**；关联点检「运行详情 + 回到会话」未破坏），6 张截图归档 `docs/screenshots/ui-v2-s1-deeplink/`；**存量零破坏走查 5/5**（`tmp/s1-legacy-inbox-check.mjs`：新前端 5199 → 旧后端 8100，通知无上文 ⇒ 按钮仍「打开运行详情」、落点仍运行详情、不假装有上文）；**反假升级为走查级**（关掉前端直达分支 ⇒ 走查第 2 条即变红，还原后 26/26 复绿）。
  - **未验证**：① 走查栈是**内存 + 确定性假执行器**（本机不接 `dsh`，见 `tmp/s1-deeplink-api.py` 头部说明），未在 dsh / 真实工作负载上验证；② `041` 未在 **PG 存储** 的 dev/staging 进程上跑过（真库往返由门控用例覆盖，但生产进程重启与迁移顺序未演练）；③ **本机 8100（你的 dev 进程）仍是旧代码**：通知不带上文（回落运行详情，已验零破坏），且运行详情「交付」区块的验收记录读取会显示失败（`/runs/{id}/acceptance/decisions` 在旧进程上不存在）——属预期降级、不白屏，重启 8100 后即恢复。
- 2026-09-19 **S2 沉淀入口补齐（存成任务）+ 三处真缺陷**（目标「按交付标准完成未完成的部分」的首项）：
  - **补齐 S2 最后一段**：迁移 [`042_run_promotions`](file:///d:/徐徐AI学习/公司工作台/migrations/042_run_promotions.sql)（表 `workbench_run_promotions`，**主键 `(tenant_id, run_id)`** =「一个运行只能沉淀一次」；复合外键 + `ON DELETE CASCADE` = 沉淀是链接、任务是产物）+ [`promotions.py`](file:///d:/徐徐AI学习/公司工作台/app/runtime/promotions.py)（内存 / PG 双实现，`claim` / `find_for_run` / `release`）+ 端点 `POST /runs/{run_id}/acceptance/tasks`（**先确认完成才可沉淀**、仅终态、越权 404、先占位再建任务、占不到即读回赢家、建任务失败**归还占位**、`ensure_can_create` 与 `task_requires_approval` 同一闸门、审计 `run.promoted_to_task` **只记 task_id**）+ `GET .../acceptance/decisions` **只增** `promotion`；前端在「确认完成」后出现沉淀区块（标题默认取承载任务标题、服务端权威回流、失败原样展示服务端结论）。任务创建路径抽成 `_store_new_task`，与 `POST /tasks` **逐条同源**（不另写一套）。
  - **缺陷①（常驻外壳丢槽参数）**：`App` 的槽不卸载但 URL 换视图后 `route` 里就没有会话 / 运行号 ⇒ ① 运行详情槽拿**空运行号**继续请求（`/runs//metrics` 等 4 个 404）；② 从会话跳到别的视图再点「对话」**会话上下文丢失**（与真源 §5「会话上下文不丢」直接冲突）。修复：`App` 记住各槽最后一次参数（`lastIds`）+ 无运行号则不渲染运行槽 + 「对话」URL 兜底带上记住的会话；`selectConversation(undefined)`（删会话 / 回列表）显式清空。
  - **缺陷②（S3「打开任务」落点为空）**：**平任务**（`POST /tasks` 建的）在管理台**没有列表 / 详情页**（`?task=` 走的是内容工作台 → `/content-tasks/{id}`），因此任何指向平任务的「打开任务」都是死链 —— 本批新增的沉淀入口最初也踩了同一个坑，已改为**只给任务编号 + 如实说明、不摆按钮**（契约同步登记）。**S3 通知里 `task` 类目标的同一问题已登记**，待与任务中心（C2）一并收口。
  - **证据**：后端全量（真库 pg16）`2465 passed / 0 failed / 0 skipped`；`tests/test_run_promotions_api.py` 12/12（含真库：占位幂等 / 跨租户复合外键拒写 / `release`）；反假 2 处（去掉「先确认完成」闸门 / 去掉占位幂等 ⇒ 对应用例分别变红）；前端 `339/339`、`tsc -b` 0、`vite build` 通过、`check:ui-copy` 与 `check:contrast` 通过；前端反假（去掉「先确认完成」判断 ⇒ 3 条用例变红）；**真实浏览器走查 17/17、0 控制台错误、0 个 4xx/5xx**（`tmp/s2-promote-walkthrough.mjs`：未确认不给入口 → 确认后出标题输入 → 存成任务 → 已存成任务 + 编号 → 刷新仍在 → 幂等与审计离页复核 → 歪路「未确认就沉淀 409」「他人 404」），截图归档 `docs/screenshots/ui-v2-s2-promote/`；两条常驻外壳缺陷另有 `App.test.tsx` 守护用例（跳走再回仍在同一会话 / 不再出现 `/runs//` 空号请求）。
  - **未验证**：① 走查栈同前（内存 + 假执行器，非 dsh）；② `042` 未在 PG 存储的 dev/staging 进程上重启演练；③ 沉淀出来的平任务**在界面上无处可看**（任务中心 C2 未立项）——本批只保证「建好 + 可追溯（运行详情 / 审计 / `GET /tasks/{id}`）」，列表与详情属 C2。
- 2026-09-19 **B-1 导出闭环补链（服务端「包号发现」+ 管理台接入取回端点）**（目标「按交付标准完成未完成的部分」第二项，对应交付清单组 10.7）：
  - **原缺口**：取回端点 `GET /api/v1/commercial/exports/{package_id}` 与过期清理已于 2026-09-16 交付，但**申请响应（`LifecycleJobView`）与作业视图都不携带 `package_id`、也没有列表端点** ⇒ 客户端**无法发现包号**，取回能力实际不可用。10.7 未验证项②「管理台前端未接入取回端点」的根因不是前端没做，而是**后端缺这一环**（本轮先补链再接线）。
  - **补链（契约先行）**：`GET /api/v1/commercial/exports`（[api-contract.md](file:///d:/徐徐AI学习/公司工作台/docs/api-contract.md)「私有部署商业化 G0」段）——admin-only、租户由登录上下文解析（客户端不能指定）、`limit` 1–200 / `offset` ≥ 0 分页（非法值 `422`）、**列表不返回载荷**、顺序 `created_at DESC, id DESC`（同刻按包号倒序 ⇒ 确定）、**如实包含已过期但未被清理的包**（客户端按 `expires_at` 标注，取回仍 `404`）。实现：[lifecycle.py](file:///d:/徐徐AI学习/公司工作台/app/commercial/lifecycle.py) 的 `ExportPackageSummary`（列表面元数据）+ `ExportPackageStore.list_for_tenant`（内存 / PG 双实现，PG 侧 SELECT **不含 `payload` 列**）+ `CommercialLifecycleService.list_export_packages`；路由 [main.py](file:///d:/徐徐AI学习/公司工作台/app/main.py)（`ExportPackageSummaryView` / `ExportPackageListView`）。**无迁移**（复用 028 的 `(tenant_id, created_at)` 索引）、**无权限模型变更**（与取回端点同一 admin 口径）。
  - **管理台接线**：[UsageBillingPage.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/billing/UsageBillingPage.tsx) 新增「数据导出」区块——申请（`POST`）→ **认服务端作业状态**确认生成（首次即时查 + 每 3 秒复查、上限约 2 分钟，超时如实告知「仍在生成」）→ 列表回流（**不做本地乐观插入**）→ 按包号取回并以 Blob **落盘为文件**（载荷不进页面）；四态齐备（加载 / 空 / 错误 / 无权限），过期包标注「已过期」且**不提供下载**，租户删除申请与保留策略设置**不摆假按钮**、在页面如实说明属下一期；客户端四个调用点（`requestExport` / `getLifecycleJob` / `listExportPackages` / `getExportPackage`）+ 列表响应不符合契约时按「可重试错误」处理（不静默当空列表、不打崩渲染）。
  - **证据**：后端全量（真库 DSN，**0 skipped**）`2470 passed / 0 failed`（基线 2465 ⇒ ＋5）；前端 `350/350`（＋11）、`tsc --noEmit` 0、`vite build` 通过、`check:ui-copy` 与 `check:contrast` 通过；**先红后绿**（5 条红：`AttributeError`×3 / `405` / `KeyError`）；**反假四轮**（去 admin 校验 ⇒ `DID NOT RAISE` + `200 == 403`；去租户过滤〔内存 + 真库〕⇒ `assert 4 == 3` / `assert (5 == 2)` / 真库跨租户行泄漏；去掉过期判定 ⇒ 过期用例红；去掉响应边界校验 ⇒ 对应用例红，均还原复绿）；**真实浏览器走查 28/28、0 控制台错误、0 个 4xx/5xx**（`tmp/b1-export-walkthrough.mjs`：空态 → 申请 → 等生成 → 列表回流 → **真实下载事件落盘 + 包内校验（15 类齐备 / 脱敏声明 / 数据面无敏感词元）** → 刷新仍在 → 关联点检（用量区块未破坏）；歪路「普通员工查列表 / 取回双双 `403`」「不存在包号 `404`」「`limit=0` ⇒ `422`」），截图与下载包归档 `docs/screenshots/ui-v2-b1-export/`。
  - **未验证**：① 走查栈是**内存 + 假执行器 + 走查脚本自带的「代替 beat 的 2 秒线程」**（`tmp/s1-deeplink-api.py` 头部说明），**不是真实 worker / beat 排程**；② staging / 生产未验收；③ ~~导出包内容仍只有 `memories` 已接线~~ ⇒ **已推进（B-2a，同日）**：6 类接真实数据，其余 9 类**逐类登记未接原因**（见下条）；④ 租户删除申请与保留策略设置仍无界面入口（属 B-3 / B-4）。
- 2026-09-19 **B-2a 导出接线首批（6 类真实数据 + 上限 / 截断 / 失败三类如实标注）+ 一个生产向真缺陷**（目标「按交付标准完成未完成的部分」第二项续做，对应交付清单组 10.7）：
  - **原缺口**：真源 15 类里只有 `memories` 接线，其余 14 类恒为空数组。
  - **补链**：新增读取通道模块 [export_readers.py](file:///d:/徐徐AI学习/公司工作台/app/commercial/export_readers.py)（**无状态适配器**，契约 `reader(tenant_id, *, limit) -> (rows, total)`；不做鉴权、每方法带租户号、不改上游数据），首批接 **6 类**：`roles` / `agents`（workforce 目录、字段同既有对外视图）、`knowledge_documents`（知识治理层）、`audits`（通用审计，分页循环）、`runs`（运行记录，**新增 `count_for_tenant`** 提供总数——内存与 PG 双实现）、`memories`（既有实现归一到同一读取器，两条注入路径归一）。服务层 `build_export_payload` 改为：读取器按类别填真实行；**每类上限 `EXPORT_CATEGORY_MAX_ROWS=5000`**，超出在 `truncated_categories` 给 `{"exported","total"}`；读取器报错的类别进 **`unavailable_categories`** 且不写 `resources`（「读不到」≠「没有」）；全部行统一过 `redact_payload`。
  - **缺陷（生产向，真缺陷）**：导出作业在 **worker 进程**执行，而 worker 装配 `build_commercial_components` 时**既没注入记忆层仓储、也没有任何读取通道** ⇒ 生产里生成的导出包会是「所有类别皆空」的**假包**（2026-09-16 的加固只在 API 进程接线）。修复：worker 与 API **两侧同源注入** `build_export_readers`（worker 侧用共享连接构造 PG 仓储），契约补「⚠️ 部署口径：两个进程都必须注入」。
  - **口径（写入 [api-contract.md](file:///d:/徐徐AI学习/公司工作台/docs/api-contract.md)「导出包内容口径（B-2）」段）**：字段只取既有读模型/视图已有字段 + **凭据类列按类别硬排除**（口令哈希 / TOTP 种子 / SSO 主体 / 系统提示词 / 模型键 / 工具白名单 / 记忆策略 / 任务幂等键与请求指纹 / 运行执行授权位）；数字员工**只导目录字段**（PG 列表读模型不返回配置列，导配置等于导默认值——不装作有数据）。
  - **证据**：后端全量（真库 DSN，**0 skipped**）`2486 passed / 0 failed`（基线 2470 ⇒ ＋16：读取器 13 / 运行记录计数 2 / **真库端到端 1**——PG 仓储 + 读取器 → 载荷只含本租户真实行、上限压 1 时 `truncated_categories` 精确 `{"runs":{"exported":1,"total":2}}`）；**反假五轮真变红后还原**（去上限 / 去统一脱敏 / 吞掉读取失败 / 读者不按租户取数 / 用返回条数冒充总数）；**真实浏览器走查 36/36、0 控制台错误、0 个 4xx/5xx**（`tmp/b1-export-walkthrough.mjs`：走查 API 每类种一行 + **他租户对照行**，真实下载文件里 6 类种子行逐类命中、`unimplemented_categories` 恰为剩余 9 类、他租户种子零出现），截图与下载包归档 `docs/screenshots/ui-v2-b1-export/`。
  - **未验证**：① 走查栈同前（内存 + 假执行器 + 脚本自带「代替 beat 的 2 秒线程」，**非真实 worker/beat**）；② **worker 侧新装配未在 PG 进程实跑**（真库往返由门控用例覆盖，`configure_runtime` 组合仅静态核对）；③ 数字员工**配置明细**仍未进包（缺口登记，逐条 `read_agent_config` 属 N+1）；④ ~~剩余 9 类未接原因逐类登记~~ ⇒ **已推进（B-2b，同日）**：再接线 3 类（见下条），剩余 6 类逐类登记原因（`steps`/`artifacts`/`knowledge_versions`/`knowledge_references`/`growth_proposals`/`approvals`）。
- 2026-09-19 **B-2b 导出接线第二批（`tasks` / `users` / `usage`，9/15 类已接线）**（同目标续做）：
  - **补链**：为三类各加**按租户列出**读方法（内存 + PG 双实现，均返回 `(本页, 过滤后总数)`——`COUNT(*)` 与 `LIMIT/OFFSET` 同条件）：[`TaskStore`](file:///d:/徐徐AI学习/公司工作台/app/domain.py) / [`PostgresTaskRepository`](file:///d:/徐徐AI学习/公司工作台/app/repository.py)（`ORDER BY id`）、[`InMemoryAccountRepository`](file:///d:/徐徐AI学习/公司工作台/app/accounts/repository.py) / `PostgresAccountRepository`（`ORDER BY requested_at, account_id`；**未审批（`tenant_id IS NULL`）的申请账号不属于任何租户** ⇒ 天然不入包）、[`InMemoryUsageLedger`](file:///d:/徐徐AI学习/公司工作台/app/commercial/usage.py) / `PostgresUsageLedger`（`ORDER BY occurred_at, id`，复用 006 既有索引）。读取器 [export_readers.py](file:///d:/徐徐AI学习/公司工作台/app/commercial/export_readers.py) 增三类：`tasks`（不含 `idempotency_key` / `request_fingerprint`）、`users`（**手机号只出掩码列**；不含口令哈希 / TOTP 种子 / SSO 主体 / 驳回理由）、`usage`（明细，不含内部幂等键；冲正为负值 + `reversal_of` 可追）。装配：`usage` 读取器由 `build_commercial_components` 用**本进程账本实例**自行接线；API 侧 `account_service` 装配**提前**到商业化组件之前（注释说明原因），worker 侧用共享连接构造 PG 账号 / 任务仓储。
  - **证据**：后端全量（真库 DSN，**0 skipped**）`2498 passed / 0 failed`（基线 2486 ⇒ ＋12：存储读方法 6 / 读取器 5 / **真库端到端 1**）；**先红**（收集期 `ImportError`）→ 绿；**反假五轮真变红后还原**（不掩码手机号〔2 红，含真库〕/ 用量计数用返回条数 / 任务导出内部幂等键 / PG 账号查询去租户过滤 / 内存任务列表去租户过滤〔3 红〕）；**真实浏览器走查 40/40、0 控制台错误、0 个 4xx/5xx**（`tmp/b1-export-walkthrough.mjs`：走查 API 新增三类种子 + 他租户对照，真实下载文件里**九类**种子行逐类命中、`users` 行手机号为 `137****0001`、`unimplemented_categories` 恰为剩余 6 类、他租户种子零出现），截图与下载包归档 `docs/screenshots/ui-v2-b1-export/`。
  - **未验证**：① 走查栈同前（非真实 worker/beat）；② worker 侧新装配（账号 / 任务读取器）未在 PG 进程实跑；③ ~~剩余 6 类未接~~ ⇒ **已推进（B-2c，同日）**：再接线 2 类（见下条），剩余 4 类判定为「无实体 / 无按租户读通道」并**明确不接线**；④ 数字员工配置明细仍未进包。
- 2026-09-19 **B-2c 导出接线第三批（`artifacts` / `steps`，11/15 类已接线）—— 导出接线收口**：
  - **补链**：① 产物登记新增按租户列出（内存 / PG 双实现，**过期口径与 `list_for_run` 逐字一致** ⇒ 保留期外不入包也不计入总数；PG 侧 `COUNT(*)` 与 `LIMIT/OFFSET` 同条件），读取器在运行级视图之上**补 `run_id`**（租户级快照必须能看出产物属于哪次运行）；② 步骤元数据把运行状态的计划**展开成每个计划步骤一行**（`run_id` / `step_id` / `kind` / `tool` / `requires_approval` / `completed`；**不含**步骤正文与执行输出——那是运行事件明细）。装配：API 侧产物仓储装配**提前**到商业化组件之前、状态仓储直接复用；worker 侧用共享连接构造（产物保留期同源自 settings）。
  - **收口口径**：剩余 4 类（`knowledge_versions` / `knowledge_references` / `growth_proposals` / `approvals`）经复核**确无实体或确无按租户读取通道** ⇒ **明确不接线**，保留空数组 + `unimplemented_categories`（不造数据）；契约新增「剩余 4 类不接线」段与逐类原因。
  - **证据**：后端全量（真库 DSN，**0 skipped**）`2504 passed / 0 failed`（基线 2498 ⇒ ＋6：真库产物按租户列出 1 / 读取器 3 / 载荷 1 / **真库端到端 1**）；**先红**（收集期 `ImportError`）→ 绿；**反假四轮真变红后还原**（内存去过期判定 / 内存去租户过滤 / 步骤计数用行数冒充 / **PG 去租户过滤**）；**真机走查 42/42、0 控制台错误、0 个 4xx/5xx**（真实下载文件里**十一类**种子行逐一命中，`unimplemented_categories` 恰为剩余 4 类，他租户种子零出现），截图与下载包归档 `docs/screenshots/ui-v2-b1-export/`。
  - **走查暴露并补掉一处测试缺口**：首轮反假①（内存去过期判定）**未变红** ⇒ 内存侧缺「过期产物」样本（过期语义此前只有 PG 用例覆盖）；已在读取器用例补种保留期外产物，反假①随即精确变红——**这正是反假探针的价值：把「测了但没测到」暴露出来**。
  - **未验证**：① 走查栈同前（非真实 worker/beat）；② worker 侧新装配（产物 / 状态仓储）未在 PG 进程实跑；③ 剩余 4 类不接线属**口径决定**（若未来这些实体立项，需重开本条）；④ 数字员工配置明细仍未进包。
- 2026-09-19 **B-3 删除清场扩围 + 记录确认人**（同目标续做；真源 `2026-09-06-commercial-g0-design.md:114`「删除前必须生成最终导出包**并记录确认人**；业务数据……按策略清理」）：
  - **记录确认人**：新增迁移 `043_tenant_deletion_record.sql` 在 `workbench_lifecycle_jobs` 上**只增** `confirmed_by` / `confirmed_at`（存量行两列 NULL，不影响既有流程）；新增审计动作 `commercial.deletion.confirmed`（明细只记受控值 `kind` / `status`，确认人由 `actor_id` 承载，**不落自由文本**）；新增 `POST /api/v1/commercial/deletion-requests/{job_id}/confirm`（admin-only + 须处冷静期 + 须已完成最终导出 + **审计 fail-closed**）；删除执行前置从「冷静期 + 最终导出」扩为「冷静期 + 最终导出 + **已记录确认人** + 审计通道」**四闸门，缺一即拒**。
  - **清场扩围**：租户删除由「只清记忆层」扩到**记忆层 + 技能层 + 知识治理层**三面物理清场（逐面 `delete_all_for_tenant`），审计 `cleared_categories` **如实只列真正清到的面**（未注入的面不参与也不列出，不假装清过）；worker 装配补注入技能 / 知识治理仓储（worker 才是执行删除的进程）。**依据**：软删语义只留给正常业务，租户整体删除须物理清场以免孤儿数据残留。
  - **可用性兜底**：冷静期可长达数十天，管理员常遗忘最后一步 ⇒ 到期且已完成最终导出时 worker **按申请自动确认**（确认人 = 请求人），写**同一审计动作**，避免删除静默卡死；`PostgresLifecycleJobStore` 的列序集中到 `_COLUMNS` + `_hydrate`（此前三处 SELECT / 三处位置水合各写一遍，加列必漏）。
  - **证据**：后端全量（真库 DSN，**0 skipped**）`2509 passed / 0 failed`（基线 2504 ⇒ ＋5 新用例：lifecycle 4 / API 1；另回写既有 4 条并加严 2 条）；**先红后绿**；**反假四轮真变红后还原**（去确认人闸门 ⇒ 3 红 / 去技能清场面 ⇒ 1 红 / 去确认审计 fail-closed ⇒ 1 红 / 去 worker 自动确认 ⇒ 1 红）；前端 `350/350` + `tsc` / `ui-copy` / `contrast` / `build` 全过（审计动作标签两端一致由 `tests/test_frontend_audit_labels.py` 守护）；迁移清单已同步 `.env.staging.example`。
  - **未验证**：① 确认 / 清场未在**真实浏览器 + 真实 worker/beat** 现场走查（本步为后端能力 + 契约，管理台**未接入删除确认界面**——按纪律不摆假按钮）；② 真库上「同租户多条删除申请取最近那条 + 确认」的**高并发**未演练；③ 清场对**对象存储文件 / 向量索引 / 缓存**（真源同句提到的其余面）本期未接，属后续专项。