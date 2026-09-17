# 前端交互模型改造与内容级呈现（对话主轴 + 右侧舞台 + 侧栏重组 + 契约扩展） 阶段规格

> **性质**：**阶段规格（唯一真源）· 已评审**。本文定义 P2c「做什么 / 怎么做 / 怎么验收」；实现按本文 §7 分批推进（宪法 2.1；feature-inventory 维护规则②）。
> **上位真源**：[`2026-09-12-conversational-agent-platform-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §17.1–§17.3（目标信息架构 / 右侧舞台构成）/ §17.7 **Q10**；[`feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md) §2（P2c 行）。
> **依据（契约与调研）**：[`api-contract.md`](file:///d:/徐徐AI学习/公司工作台/docs/api-contract.md)「实时流与过程事件（P2b）」「对话式 AI 员工平台（P1）」「工具执行（P2a 段二）」「待我审批聚合」「Agent Runtime 运行」；[`P2b 规格`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-17-realtime-stream-p2b-design.md)（Q9/Q10 归属、审批分支口径）；[`段二规格`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-dsh-integration-design.md)（§3.3 容器边界 / §3.4 正文密文唯一受控例外 / §4.1 待批动作）；调研输入：[`p2c-interaction-study.md`](file:///d:/徐徐AI学习/公司工作台/docs/p2c-interaction-study.md)、[`openmausbot-source-study-and-adaptation-plan.md`](file:///d:/徐徐AI学习/公司工作台/docs/openmausbot-source-study-and-adaptation-plan.md)（**只借模式，不复用代码**）。
> **日期**：2026-09-17
> **状态**：**已评审（2026-09-17，用户批准本文件）**；§5 待裁决**按推荐执行**。实现按 §7 分批推进——**P2c-1 已交付**（见 §0 交付记录）。**未经用户确认不提交、不推送**。
> **前置**：P2b 后端已交付（迁移 `036` + 帧仓储 / 写入网关 + `messages:stream` + SSE 读端点 + 清理任务）。**本阶段含后端与契约改动**（见 §1.2 分批与 §1.5 变更留痕）。
> **2026-09-17 用户裁决（本规格的范围裁决，评审时逐项确认）**：① 原 §1.3 排除项**大范围纳入**——终端输出面板、文件 diff 面板、审批后推进的过程事件、产出 chip、每会话模式、收尾检查、模型/工具选择器、个人数据导出/删除、PWA 消费流**全部纳入 P2c**；② **允许 P2c 内按需新增端点与契约修订**；③ **允许放宽底座**（可引入前端路由库与流解析依赖）。
> **2026-09-17 二次裁决（P2c-2 开工前）**：① §1.3 剩余四条**功能级排除全部纳入**——自动验收（**结构判定**）＋一键人工重做、分享（**本租户指定用户 · 只读**）、多端协同（**受邀成员可发言**）、物理删除（**真删消息行**）；② 内容级边界**维持有界摘录**（默认 16 KiB，可配 0–256 KiB；不落全文、不落二进制）；③ 落位：物理删除与自动验收并入 **P2c-4**，分享与协同**新增 P2c-6**；④ **不做**：LLM 判分、自动重跑、部门级/跨租户/公开链接分享、实时在线态、管理端代删（见 §1.3）。

***

## 0. 现状盘点（2026-09-17 起草时静态核对）

> 体例说明：本阶段含迁移与后端改动，开工日按 [`knowledge-governance-design.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-15-knowledge-governance-design.md) §0 同体例补写（**迁移从零应用 + 真库用例 + 一键全量 + CI 销账**）。本节登记起草时**已核实的实现事实**（静态核对，非运行时取证）。

| #   | 事实（静态核对）                                                                                                                                                 | 证据                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | 默认视图 = `home`；路由是 `?view=` 查询串（无路由库）；视图常驻挂载（`hidden` 切换）                                                                                                  | [App.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/app/App.tsx#L71-L101)                             |
| 2   | 侧栏为两段平级入口（6 + 10 = 16 个），分组用数组下标切片表达                                                                                                                     | [AppShell.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/app/AppShell.tsx#L26-L49)                        |
| 3   | 对话页两栏（列表 + 内容），发送走旧 `POST .../messages`，响应后整页重取；无第三区                                                                                                      | [ConversationPage.tsx](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/conversation/ConversationPage.tsx#L117-L133) |
| 4   | 前端**无任何 SSE / `EventSource` / `ReadableStream` 流消费**；认证走自定义请求头 ⇒ `EventSource` 不可用，须 `fetch` + 读流                                                     | 全仓 grep；[conversation/api.ts](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/conversation/api.ts#L9-L13)      |
| 5   | 对话页发送**恒带幂等键** ⇒ 真实执行已装配时「纯文本必 `422`」（P2a 结构化调用口径）；首页 `sendHomeMessage` **不带键**（桩路径）——两处口径不一致                                                             | execution.py L167-183 / L244-246；home/api.ts L56-61                                                  |
| 6   | 消息视图**无 `run_id`**；`201/202` 响应带 `run_id`，P2b 另有 `X-Stream-Run-Id`                                                                                         | conversation/types.ts L23-33；契约 L690 / L920                                                          |
| 7   | 运行侧只读数据面齐备：`GET /runs/{run_id}/events`、`GET /runs/{run_id}/approvals`、`POST .../approval`（仅 `ceo`/`super_admin`、发起人不得自审）、`GET /approvals/pending`           | 契约 L628-L637、L394-L431                                                                             |
| 8   | **工具目录已有 13 个工具键**（**2026-09-17 P2c-4 实测更正：起草时记的「16」为笔误**）：`fs.list` / `fs.read` / `fs.stat`（low）、`cmd.run` / `fs.write`（medium）、`fs.overwrite` / `fs.delete`（high）、`artifact.export`（critical）、CRM 读 ×4（low）+ `crm.activity.log`（medium） | [catalog.py](file:///d:/徐徐AI学习/公司工作台/app/tool_execution/catalog.py#L93-L210)                       |
| 9   | **🔴 `fs.*` / `artifact.export` 在容器内的执行入口尚未实现**：`_command_for` 只支持 `cmd.run`，其余**fail-closed 拒绝**（"由后续适配器段实现"）                                                | [executor.py](file:///d:/徐徐AI学习/公司工作台/app/tool_execution/executor.py#L77-L93)                      |
| 10  | **🔴 `cmd.run` 的输出当前被丢弃**：执行只取容器 `StatusCode`，`ExecutionOutcome.summary` = `{tool_key,status,exit_code}`——**无 stdout**                                          | executor.py L386-L436                                                                              |
| 11  | **🔴 工作卷是容器内 tmpfs，随容器销毁**（`/workspace`，`noexec,nosuid,nodev`，`uid/gid/mode` 显式钉死）；文件**不跨执行留存** ⇒ 文件变更与产物**必须在执行时产出并落库**，不能事后扫描                     | executor.py L18-L27、L56-L69                                                                         |
| 12  | 正文唯一受控例外 = `027` 的 `workbench_tool_actions.body_ciphertext`（AEAD 密文、审批超时到期、**密文不上帧**）；工具结果落库只有「摘要 + `args_digest` + `sha256`」（Q9 口径）                    | `027` 头注释；P2b 规格 §2.5                                                                               |
| 13  | **无产物登记表**（迁移全量 grep `artifact` 零命中）；`artifact.export` 默认**不装配**（`WORKBENCH_ARTIFACT_EXPORT_ENABLED=false`）                                           | migrations/；service.py L105-L112                                                                   |
| 14  | **`workbench_conversations` 无「每会话模式」列**（列：`agent_key/operator_id/title/status/dsh_session_id/时间戳`）；自治三档在**员工级配置**（`workbench_digital_employees.autonomy_level`） | [023](file:///d:/徐徐AI学习/公司工作台/migrations/023_conversational_agent.sql#L14-L25)；023 L59-L60              |
| 15  | 模型候选只存在于装配期：`registered_model_keys(settings)`（配置校验用）；**无只读端点**（契约 Y1 明确「不加工具目录只读端点，沿用自由文本 + 422」）                                                          | [bootstrap.py](file:///d:/徐徐AI学习/公司工作台/app/bootstrap.py#L1125-L1129)；契约 L760                      |
| 16  | 消息表 **append-only**（不建 `updated_at`、无 update 路径）；会话只有归档（`active/archived`），**无删除/导出**                                                                        | 023 头注释 L7；契约 L655                                                                                 |
| 17  | **`companion-pwa` 现状只有三个功能面**：登录、审批、收件箱——**没有对话页面**（"PWA 消费流"实为「**新建** PWA 对话面板」）                                                                               | companion-pwa/src/features/{session,approvals,inbox}                                                |
| 18  | `desktop` = Electron 外壳（`loadURL`，可加载远端 URL 或打包的 admin-web 产物）⇒ 桌面端**继承** admin-web 改造（零额外 UI 工作）                                                        | desktop/src/main.cjs L89、config.cjs                                                                 |
| 19  | 过程事件既有消费路径：运行详情页 `RUN_EVENT_LABELS` + `RUN_EVENT_PAYLOAD_FIELDS` 白名单                                                                                    | [runDetail/types.ts](file:///d:/徐徐AI学习/公司工作台/admin-web/src/features/runDetail/types.ts)                   |
| 20  | 前端测试基建：每 feature `*.test.tsx`（vitest）；`companion-pwa` / `desktop` 各有测试；CI 现有 6 job                                                                        | `*/src/features/*/*.test.tsx`、`.github/workflows/ci.yml`                                            |

**结论（决定分批的关键三条）**：事实 9/10/11 ⇒「终端输出」「文件 diff」「产出 chip」三类面板**不是"拿到数据画界面"**，而是要先把 **①容器内工具执行入口补完（fs.\*）、②执行输出与文件变更的受控回传、③产物登记**三件后端事件做完；事实 17 ⇒ PWA 是**新建对话面板**而非接流；事实 18 ⇒ 桌面端零额外改造。

> **交付记录（P2c-1，2026-09-17 本机）**：侧栏 6 分组（新增「客户与商务」；资产组不建）+ 默认视图改对话（`?view=home` 保留可用）／对话页三区（会话列 + 对话流 + 右侧舞台，窄屏舞台折叠为抽屉）／SSE 读端（`fetch` + 读流 + `eventsource-parser`；`Last-Event-ID` 真增量续播、指数退避重连、终态关流、切走即断）／发送路径路由（结构化 ⇒ `messages:stream` + 幂等键；纯文本 ⇒ 不带键桩路径）／舞台三块（运行概览 / 过程时间线 / 审批）+ 对话内联审批卡（既有审批接口、权威态回流）+ 收尾检查（**仅展示**）。
> **验证**：`admin-web` vitest **220 passed（32 文件）** + `tsc -b && vite build` 通过；**反假测试 2 项已实测变红**（① 读端重连起点固定 0 ⇒ 续播用例红；② 纯文本也带键 ⇒ 路由用例红）；浏览器走查 2 轮（默认视图 / 侧栏 6 组 / 三区与抽屉 / 概览切换 / 纯文本桩回复无过程条；结构化调用路径）。
> **走查发现并修复 1 个真实缺陷**：后端**未装配真实执行**时结构化调用回落桩路径（响应无 `X-Stream-Run-Id`、不产生运行），前端曾持续挂流并永远显示「执行中」⇒ 现改为 **关流 + 如实告知「本次没有过程流」**（用例：`结构化调用未产生运行 ⇒ 关流并如实告知`）。
> **环境限制（登记未验证）**：本机 dev 后端未装配真实执行（结构化调用回落桩路径）⇒ **真实帧流的浏览器端到端未取证**；帧流语义由单测（解析 / 续播 / 终态 / 退避 / abort）与 P2b 真库用例覆盖，**真实执行装配后的端到端走查留待 staging**。**CI 销账（2026-09-17）**：提交 `a1eb73f` 推送后 run `35192322076` ⇒ **六 job 全绿**（「网页管理台」job 真跑 `admin-web` vitest + build）。
>
> **交付记录（P2c-2，2026-09-17 本机）**：① **契约修订先行**——`api-contract.md` 新增「内容级回传」（`tool.result` **只增** `output_excerpt` / `output_truncated` / `output_bytes` / `output_sha256`；三个配置项 `WORKBENCH_OUTPUT_EXCERPT_MAX_BYTES` / `WORKBENCH_FILE_DIFF_EXCERPT_MAX_BYTES` / `WORKBENCH_FILE_CHANGES_MAX`；七条硬边界）、审批分支改「**决议后推进接入同一帧写入**」（推翻「本期不做」）、SSE 读端**只增**响应头 `X-Stream-Run-Id` 与帧内 `run_id`；`P2b 规格` §1.3 / §2.5 / §5 / §6 回改留痕。② **后端**：`ContainerExecutor` 新增 `OutputCapture` + `_capture_output`（**流式有界读取**、1 MiB 硬上限、`0` = 关闭且**不读日志**、严格 UTF-8 判定 + 尾部半截字符容忍、**读取先于 `remove_container()`**、读取失败不影响执行）；`ToolExecutionResult.output`（白名单折算、**不进审计**）；`tool.result` 帧 payload 只增摘录字段（缺省不出现 ⇒ 既有帧逐字节不变）；`StreamStore.reopen_if_terminal`（PG + 内存；`unavailable` 不复活）；`ExecutionIdempotencyStore.find_by_run`（PG + 内存，走 027 既有索引）；`decide_run_approval` 接入 `_resume_stream_frames`（写 `tool.result` + 终态收口；决议后**重开读端**由前端承担）。③ **前端**：新增 `features/stage/ToolOutputPanels.tsx`（终端输出 / 文件改动面板，帧驱动 + 白名单 + 截断告知，**无数据不渲染**）；`useRunStream` **解析 run**（响应头 / 帧内 `run_id`，显式 `runId` 优先；无 run ⇒ 关流 + `noData` 如实告知；发送中 `awaitRun` 继续等）；对话页**进入会话即开回放读端**、`effectiveRunId` 驱动概览与审批、决议成功后重开读端尾随推进帧。
> **验证**：后端 **2315 passed**（含新增：`tests/test_execution_output_capture.py` 8 条；`tests/test_conversation_stream_api.py` +5 条（帧携带 + 掩码 / 审计零污染链 / 决议后推进端到端 / 历史会话解析 / SSE 只增字段）；`tests/test_conversation_stream_postgres.py` +4 条（重开续写 / 熔断不复活 / 缺状态行不建 / 摘录落库掩码）；`tests/test_conversation_stream_writer.py` +1 条（**摘录同样受字节熔断**）；`tests/test_tool_execution_gate.py` +1 条）。前端 `admin-web` **235 passed（33 文件）** + `tsc -b && vite build` 通过；`companion-pwa` 37；`desktop` 19。**反假两轮已实测变红**：① 去掉摘录上限 ⇒ 3 条变红；② 推进不接帧（`_resume_stream_frames` 直返）⇒ 2 条变红（均已复原）。**浏览器走查 1 轮**（本机 dev：前端 5173 + 后端 8010 新代码）：默认视图 / 侧栏 6 组 / 新建会话 / 舞台三空态 / **无「终端输出」「文件改动」假面板** / 纯文本桩回复 / 结构化调用「本次没有过程流」并回空态 / 全程无 `.notice-error`（`net::ERR_ABORTED` 的流中断为「切走即断」设计行为）。
> **未验证（登记）**：真实执行装配后的**帧驱动端到端**（终端面板实际数据 / 决议后推进的真实帧）留 staging；≥1281px 宽视口三列常驻未实测（走查窗口 913px）。
> **CI 销账（2026-09-17）**：提交 `a1eb73f`（P2c-1）推送后 run `35192322076` ⇒ **六 job 全绿**；**P2c-2 + P2c-3 一并推送**（`2e9dcb4` / `997f682`，`4b13f34..997f682 main -> main`）⇒ run **`35207649604` 六 job 全绿**（后端 pytest + compileall、后端真库（含新迁移 `037` 与 `test_run_artifacts_postgres.py`）、**沙箱加固与真容器回归**（含 `test_container_executor_fs.py`）、网页管理台 vitest + build、手机伴侣端 vitest + build、桌面端 node --test）。
>
> **交付记录（P2c-3，2026-09-17 本机）**：① **契约与规格先行**——契约「内容级回传」补 `file_changes` 取值域与 `file_changes_truncated`（**只增**）、三个配置项的 `0` 语义、硬边界第 7 条（`fs.*` 在「空工作卷」下的语义）；新增「产物登记与只读端点」（`GET /api/v1/runs/{run_id}/artifacts`、保留期 30 天、清理任务与两项配置）；规格 §2.7 补「实现期裁定 1–5」（落地形态 / 内容传递 / 空工作卷语义 / 端点与清理口径 / 截断告知）并收口 §6-5。② **后端**：新增 `app/tool_execution/file_ops.py`（**自建内联脚本** + 结构化 argv + base64 内容传递 + 覆盖 / 幂等删除语义 + 变更标记解析与上限折算）；`_command_for` 接入 `fs.*`（`artifact.export` 仍 fail-closed）；`ContainerExecutor` 新增变更通道（来源白名单只认 `fs.*`、标记行不进摘录、`0` = 关闭）；`service.py` 把变更折算进 `ToolExecutionResult.output` 并**best-effort 登记产物**（与帧同一集合、失败不阻断执行）；新增 `app/runtime/artifacts.py`（内存 + PG 仓储、复合外键跨租户拒写、保留期到期过滤、逐租户清理）+ 迁移 `037_run_artifacts` + worker 周期任务 `run-artifacts-purge` + 只读端点（归属判定同运行接口）。③ **前端**：`ArtifactPanel`（四态 + 白名单投影 + 保留期如实告知）、`ArtifactChips`（对话流内按虚拟路径聚合、点开 diff 摘录、截断告知）、`useRunArtifacts`、`listRunArtifacts`，并统一 `changeKindLabel`（`created` / `overwritten` / `deleted`）。
> **验证**：后端 **2362 passed**（含真库：新增 `tests/test_fs_tools.py` 21 条、`tests/test_execution_output_capture.py` +7 条、`tests/test_tool_execution_gate.py` +3 条、`tests/test_conversation_stream_api.py` +4 条（含**真实执行服务端到端**：`fs.write` 202 → 决议 → 重跑 → 变更入推进帧 + 产物登记 + 端点读回）、`tests/test_run_artifacts_postgres.py` 5 条、`tests/test_worker_runtime_wiring.py` +3 条）；**真容器** `tests/test_container_executor_fs.py` **5 passed**（fs.write 变更记录 / 标记剥离 / 文件不跨执行留存 / 容器内路径闸门拒绝逃逸 / 空卷幂等删除）。前端 `admin-web` **248 passed（35 文件）** + `tsc -b && vite build` 通过；`companion-pwa` **37 passed** + build；`desktop` **19 passed**；`compileall` exit 0；`.env.staging.example` 迁移清单补 `037_run_artifacts`（预检守护用例）。**反假四轮已实测变红**（均已复原）：① 去掉 `fs.*` 来源白名单（内外两道）⇒ `cmd.run` 伪造标记能产出假变更记录（1 条红）；② 去掉变更上限截断 ⇒ helper / 执行器 / 服务 / 帧**四层用例同时红**（4 条）；③ 去掉容器内 realpath 落点判定 ⇒ **符号链接逃逸**用例红（读到了工作卷之外）；④ 登记失败不兜底 ⇒ 执行结果被登记失败打断（1 条红）。**浏览器走查 1 轮**（dev：前端 5173 + 后端 8010 新代码，已用 `openapi.json` 核对端点注册）：默认对话视图 / 新建会话 / 纯文本发送成功 / 舞台三空态 / **无「终端输出」「文件改动」「产物登记」假面板** / 控制台无 error。
> **未验证（登记）**：本机 dev 未装配真实执行（结构化调用回落桩路径、无运行）⇒ **产物面板与产出 chip 的真实数据渲染**未取证（组件级用例 + 真容器用例已覆盖语义，真实端到端留 staging）；`fs.overwrite` / `fs.delete` 的「目标已存在」分支在**跨执行**场景不可达（空工作卷架构限制，已写入契约硬边界第 7 条，宿主侧脚本用例覆盖该分支）。
>
> **交付记录（P2c-4，2026-09-17 本机）**：① **契约与规格先行**——契约新增「P2c 对话模式 · 导出与物理删除 · 候选端点 · 结构判定（P2c-4）」整节（模式语义与两处判定 / `POST .../mode` / `GET .../exports/mine`（500 页 + 5 万条上限）/ `POST .../{id}/delete`（顺序与失败语义）/ 两个只读候选端点（**Y1 推翻留痕**）/ `GET /runs/{run_id}/acceptance`（纯读、不改状态））；P1 章节补 `mode` 只增与「受控物理删除」引用；Y1 决议行加推翻留痕。规格 §1.4 落定迁移实号（P2c-4 = **`038`**）、§2.5 / §2.9 / §2.10 / §2.11 各补「实现期裁定」（判定落服务端 / 正常终态取 `run_completed` / `ask` 拒绝码 409 与幂等行 / 推进处拦截点 = 决议入口 / 两集合如实分开 / 导出上限与前端逐页合并 / 删除顺序与原子性）、§0 事实 8 **实测更正**（工具目录 13 键，非 16）。② **后端**：迁移 `038_conversation_mode_and_soft_delete`（`mode` 带 CHECK 默认 `craft` + `deleted_at` 软删列）；`Conversation` 增 `mode` / `deleted_at` 与 `ConversationMode` / `normalize_mode`；仓储层增 `get_conversation_including_deleted` / `set_mode`（返回 `(会话, 变更前模式)`）/ `delete_conversation_content`（消息 + 软删同事务）/ `export_mine`，并把软删过滤写进**全部读路径**；流仓储与幂等仓储各增 `delete_for_conversation`；`ConversationService` 增 `set_conversation_mode` / `delete_conversation`（固定顺序：幂等行 → 帧 → 流状态 → 消息 + 软删；复删幂等不重复写审计；缺仓储 fail-closed）/ `export_mine`（条目上限如实告知 + 审计）；`ConversationExecutionService` 增 `ask` 拒执行（409 + 审计 + `rejected` 幂等行）与 `plan` 强制待批（经唯一判定入口 `needs_approval`，等价 `approval_for_all`）+ **推进处** `ensure_resume_allowed`（决议入口最前拦截、校验失败 `503` fail-closed）；新增 `app/runtime/acceptance.py`（纯函数结构判定）；4 个新端点（`/conversations/{id}/mode`、`/conversations/exports/mine`、`/conversations/{id}/delete`、`/workforce/model-candidates`、`/tools/catalog`、`/runs/{id}/acceptance`）+ 4 个新审计动作码与 9 个明细键。③ **前端**：对话页模式下拉（服务端回流、无乐观更新）、删除（二次确认 + 计数提示 + 清空选择）、导出（逐页合并 → JSON 下载，超限如实告知）、收尾检查升级（**服务端结构判定** + 会话模式 + 产物数 + 未达标一键重做 / 无原件降级提示）；数字员工配置页 `model_key` 改候选下拉、`tool_allowlist` 改目录多选（灰显给原因 + 不可用项一键移除 + 端点失败回落自由文本）。
>
> **验证**：后端 **2395 passed**（含真库；新增 `tests/test_conversation_mode_api.py` 9 条、`tests/test_conversation_delete_export_api.py` 6 条、`tests/test_run_acceptance_api.py` 6 条、`tests/test_tool_catalog_api.py` 6 条、`tests/test_conversation_lifecycle_postgres.py` 7 条；`compileall` exit 0）；前端 `admin-web` **261 passed（36 文件）** + `tsc -b && vite build` 通过；`companion-pwa` **37 passed** + build；`desktop` **19 passed**。**反假三轮已实测变红**（均已复原）：① `ask` 只在前端拦（后端放行）⇒ 用例 ① 红（`201` 而非 `409`）；② 删除只做软删（消息行不真删）⇒ 真库用例 ② 红（`message_count` 断言失败）；③ 结构判定改接 LLM（探针调用）⇒ 「不调模型」断言红（5 条端点用例同时红）。**浏览器走查 1 轮**（dev：前端 5173 + **新代码**后端 8010）：默认对话视图 / 6 分组 / 新建会话 / 列表条目模式徽标 / 模式切换双向（`ask` ↔ `craft`，提示与徽标同步、列表回流）/ 「导出我的数据」触发导出接口 + 计数提示 / 删除会话（确认后计数提示 + 列表消失 + 回空态）/ 数字员工配置页**模型键为下拉**（本部署候选为空 ⇒ 如实显示「（默认模型：本部署未注册模型键）」）与**工具白名单为 13 项复选框列表**（本机未配置 `WORKBENCH_PLANNER_TOOLS` ⇒ 13 项**全部灰显**并给出受控原因，与「保存会被 422 拒绝」一致）/ 全程无 `.notice-error`。
>
> **未验证（登记）**：① 导出**文件是否真正落盘**未取证（走查环境未观察到下载栏与 `blob:` 资源，接口调用与计数提示已确认；下载行为依赖浏览器设置，组件级用例已断言 `createObjectURL` 与锚点点击被调用）；② 二次确认对话框**本身**未在自动化下被观测（由自动化层以 accept 放行，删除效果已确认）；③ **结构判定与一键重做的真实运行数据**端到端未取证（本机 dev 未装配真实执行 ⇒ 无运行；组件级用例覆盖 `met` / `unmet` / 重做新幂等键路径，真实执行装配后的端到端留 staging）；④ `mode=ask` 的**推进处拦截**在真实执行装配下的端到端未取证（接口层用例已覆盖：待批 → 切 `ask` → 决议 `409` 且不落决议 → 切回后可决议）；⑤ ≥1281px 宽视口三列常驻仍未实测（走查窗口 913px，承接 P2c-3 同项）；⑥ 本机 dev 的 `WORKBENCH_PLANNER_TOOLS` 为空 ⇒ 选择器「灰显给原因」路径已取证，而**可选（可保存）路径**只在组件测试里取证。
>
> **CI 销账（2026-09-17）**：提交 `5d92fcc` 推送后（`ad3711e..5d92fcc main -> main`）run **`35234051711` ⇒ 六 job 全绿**（后端 pytest + compileall、后端真库（含迁移 `038` 与 `test_conversation_lifecycle_postgres.py`）、**沙箱加固与真容器回归**、网页管理台 vitest + build、手机伴侣端 vitest + build、桌面端 node --test）。

***

## 1. 范围

### 1.1 边界定义

把 `admin-web` 从「16 个平级页面 + 对话只是其一」改造为**对话主轴**形态，并补齐让「边聊边看真实过程与产物」成立所需的**内容级回传链路**：

1. **交互层（P2c-1）**：侧栏分组（Q10 落地）；对话页 = 会话列 + 对话流 + 右侧舞台；消费 P2b 流契约；审批内联；性能与状态纪律。
2. **内容层（P2c-2）**：执行输出与文件变更的**有界受控回传**（修订 Q9 口径：仍不落全文、不落二进制）；审批后推进的过程事件**接入帧写入**。
3. **工具面（P2c-3）**：容器内 `fs.*` 执行入口补完（段二-3 遗留）+ 文件变更记录 + **产物登记**与 chip。
4. **产品项（P2c-4）**：每会话模式（Ask/Plan/Goal/Craft，与自治三档**取更严**合成）；收尾检查（展示型）；模型/工具选择器（新增只读端点，推翻 Y1）；个人数据导出/删除（合规，含墓碑语义）。
5. **多端（P2c-5）**：PWA **新建对话面板**（含流消费）；桌面端继承（零改造，仅核对）。

**不是**新的执行引擎（九步闸门原样）；**不是**第二套权限判定（所有新面都是既有判定的展示或入口）；**不是**放宽容器边界（`--network none`、tmpfs、root 只读、非 root 全部不动）。

### 1.2 做什么（分批清单）

| 批         | # | 事项                                                                                     | 一句话                                                                                                          | 类型       |
| --------- | - | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------- |
| **P2c-1** | A | **侧栏重组（Q10 落地）**                                                                        | 16 平级入口 → 6 分组（对话 / 任务与项目 / 员工 / 知识 / 治理 / **客户与商务**）；默认视图改对话；`?view=` 零破坏                               | 前端       |
|           | B | **对话页三区**                                                                              | 会话列 + 对话流（消息 + 过程折叠条）+ 右侧舞台（运行概览 / 过程时间线 / 审批）；窄屏舞台折叠为抽屉                                                    | 前端       |
|           | C | **流消费（SSE 读端）**                                                                        | `fetch` + 读流；`Last-Event-ID` 真增量续播；心跳忽略；终态关流；退避重连；切换会话 / 离开视图即 `abort`                                            | 前端       |
|           | D | **发送路径路由**                                                                             | 结构化调用 ⇒ 带键 `messages:stream`（真实执行 + 开流）；纯文本 ⇒ 不带键（桩、无流）——修复「纯文本必 422」不一致                                        | 前端       |
|           | E | **内联审批卡 + 收尾检查（展示型）**                                                                  | 审批在对话内决议（复用既有接口、权威态回流）；运行收尾展示「进度档」（未达标记「未完成」，**不改状态、不退回**）                                                     | 前端       |
|           | F | **性能与状态纪律**                                                                            | 流状态隔离 + 帧 ≤100ms 合批 + 时间线窗口（≤500 行）+ 跟随阈值；状态词沿用既有标签，未知 kind/字段不猜测                                               | 前端       |
| **P2c-2** | G | **契约修订：内容级回传（有界）**                                                                     | `cmd.run` 输出与文件变更以**有界摘录**回传（默认 16 KiB/次、二进制不回传、过 `redact_payload`、随帧 7 天保留）；**修订 Q9**（仍不落全文）              | 后端 + 契约  |
|           | H | **审批后推进的过程事件**                                                                         | resume（决议后推进）路径接入帧写入 ⇒ 「决议后继续执行」也实时可见                                                                        | 后端       |
|           | I | **终端输出面板 + 文件 diff 面板**                                                                | 右舞台新增两个面板（数据 = G 的回传），可展开、可截断告知                                                                              | 前端       |
| **P2c-3** | J | **`fs.*` 容器执行补完 + 文件变更记录**                                                            | 段二-3 遗留：`fs.read/list/stat/write/overwrite/delete` 在容器内落地（路径闸门 ③④ 原样）；执行时产出**变更记录**（虚拟路径 / 类型 / 字节 / sha256 / 有界 diff 摘录） | 后端       |
|           | K | **产物登记 + 产出 chip**                                                                    | 新表登记产物（run 级、跨执行可查、保留期）+ 只读端点；对话流内产出 chip → 展开 / 跳转                                                            | 后端 + 前端  |
| **P2c-4** | L | **每会话模式（Ask / Plan / Goal / Craft）**                                                   | 新列 + 与自治三档**取更严**合成（`ask` 拒执行 / `plan` 强制待批 / `goal`·`craft` 不放松）；默认 `craft`＝现状                                  | 后端 + 前端  |
|           | M | **模型 / 工具选择器**                                                                         | 新增两个**只读**候选端点（`super_admin`）；「不可用项给原因」；**推翻契约 Y1**（留痕）                                                     | 后端 + 前端  |
|           | N | **个人数据导出 / 物理删除（合规）**                                                                    | 导出本人会话与消息（**库内实际存在的字段**）；删除 = **真删消息 / 帧 / 流状态 / 幂等行** + 会话软删与标题清空；运行与审计保留（不含正文）；复删幂等                                          | 后端 + 前端  |
|           | Q | **自动验收 + 一键重做**                                                                          | 收尾检查升级：**结构判定**（步骤全完成 + 无未决审批 + 正常终态）标「达标 / 未达标」；未达标给**一键重做**（页面持有原件时以新幂等键重发）；**不调模型、不自动重跑**；判定不改运行状态                          | 后端 + 前端  |
| **P2c-5** | O | **PWA 对话面板（含流）**                                                                       | PWA **新建**对话页：列表 / 消息 / 发送 / 过程折叠条（简化版，无右舞台）；复用既有登录与审批页                                                       | PWA      |
|           | P | **桌面端核对**                                                                              | Electron 外壳加载 admin-web ⇒ 继承；核对 `fetch` 流式读与 CSP（未验证项 §6）                                                  | 核对       |
| **P2c-6** | R | **会话分享（本租户指定用户 · 只读）**                                                              | 成员表（`read` / `write` 两档）+ 增删查端点；读路径统一「**本人 ∪ 成员**」；仅点名、仅本租户；撤销写审计                                       | 后端 + 前端  |
|           | S | **多端协同（受邀成员可发言）**                                                                      | `write` 成员可在会话发言与**以其本人身份**触发执行（不放松任何既有闸门）；消息新增 `sender_id`；参与者列表 + 最近活动（**不做实时在线态**）                            | 后端 + 前端  |

### 1.3 不做什么（明确排除）

> **2026-09-17 二次裁决后**：原第 1、2 条（自动验收 / 分享 / 协同 / 物理删除）**已纳入**（见 §1.2 的 Q / R / S 批与 §1.5 留痕）。本节保留项**全部是边界**（安全 / 架构 / 合规），不是功能砍伐。

1. **自动验收只做结构判定**：**不做 LLM 判分**（无 rubric 真源、有幻觉与成本风险）；**不做自动重跑**（消耗执行额度、存在循环风险）；退回一律**人工触发**，判定**不改运行状态**。
2. **重跑不新增正文留存**：原始参数按既有口径**不落库**（消息只落脱敏摘要，工具动作只落 `args_digest`）⇒ 一键重做**仅在本页仍持有原件时可用**；跨页 / 刷新后**如实告知**「原始参数未留存，请重新输入」。**不新增加密参数留存例外**（`027` 密文列仍是唯一受控例外）。
3. **协作边界**：**不做部门级 / 全租户共享**（无组织 / 部门树，无维度来源）；**不做跨租户分享与公开链接**；**不做实时在线态 / 协同编辑**（无 WebSocket 底座，消息 append-only）；**成员不得放松任何既有判定**（审批 / 自治三档 / `critical` 仅 CEO 超管 / 发起人不得自审原样生效）。
4. **物理删除只删内容行**：**只允许本人删自己的会话**；真删范围 = 消息行 + 帧行 + 流状态行 + 该会话幂等行；**会话行不物理删**（软删 + 标题清空，保运行 / 审计引用链）；**运行记录与审计不删**（不含正文）；**无管理端代删 / 批量删**。
5. **不落全文、不落二进制**：内容级回传始终是**有界摘录**（G 批的默认 16 KiB / 次、单文件 diff 8 KiB），非文本内容只留字节数与摘要；**不进审计、不进消息表**（消息表仍为 U23 摘要口径）。
6. **不放宽容器边界**：`--network none`（内网桥 `internal=True`）、root 只读、非 root（65534）、`noexec,nosuid,nodev` tmpfs、镜像 digest 钉死——**一律不动**；`fs.*` 落地不得绕开 ③ realpath 与 ④ 黑名单闸门。
7. **不做第二套权限判定**：所有新端点复用既有 `current_user` / 归属判定 / 审计；**「成员资格」是唯一新增授权轴**（落库、可审计、可撤销，不产生新角色），前端按钮显隐**不构成授权**。
8. **不搬运外部产品的界面 / 代码 / 文案**（调研清单 §5；PolyForm / 商标边界）。
9. **不为「模式」新增第三套轴**：模式只与自治三档合成，**不引入**权限模型改写；`critical` 仍仅 CEO / 超管、发起人不得自审——模式**不得放松任何既有判定**。
10. **不做 `artifact.export` 的默认开启**：导出仍 `WORKBENCH_ARTIFACT_EXPORT_ENABLED=false` fail-closed；产出 chip 只读「登记产物」，不触发导出。

### 1.4 影响什么（改动面）

| 层            | 影响                                                                                                                    |
| ------------ | --------------------------------------------------------------------------------------------------------------------- |
| 迁移           | 实号开工取（按批切分；**2026-09-17 落定**）：② 产物登记表 = `037_run_artifacts`（P2c-3 已交付）；① 会话 `mode` 列（含 CHECK 默认 `craft`）+ ③ 会话 `deleted_at` 软删列（**无墓碑列**：消息走真删）= **`038_conversation_mode_and_soft_delete`**（P2c-4）；④ 会话成员表（`read` / `write`）+ ⑤ 消息 `sender_id` 列（可空，存量 `NULL` ⇒ 归属发起人）留 P2c-6 取 `039+` |
| 后端           | `app/conversation/*`（模式判定、**真删清理（引用图级联）**、导出、**成员与可见性判定**、**验收结构判定**）、`app/tool_execution/executor.py`（输出有界读取、`fs.*` 入口、变更记录）、`app/conversation/stream_writer.py`（payload 扩展）、resume 路径接帧、产物登记存储、两个只读候选端点、导出/删除端点、**成员端点** |
| 契约           | `api-contract.md`：**修订** P2b 章节（帧 payload 扩展 + resume 写帧 + Q9 边界修订）、P1 章节（模式 / 导出 / **物理删除语义** / **成员与协作**）、工具执行章节（Y1 推翻 + 目录端点）、新增产物端点、**新增成员端点**；`P2b 规格` §1.3/§6 回改留痕           |
| 前端 `admin-web` | `app/*`（分组、路由默认值）、`features/conversation/*`（三区 + 流 + 路由 + 审批卡 + 收尾检查与重做 + **分享 / 成员**）、新增 `features/stage/*`、`features/workforceSettings/*`（选择器）、样式                |
| 前端 `companion-pwa` | 新增 `features/conversation/*`（对话面板 + 简化流）                                                                              |
| Worker       | 产物登记保留期清理（并入既有清理任务口径，逐租户）                                                                                             |
| 清单           | `feature-inventory.md`（§2 P2c 行 + 六要素 + §5 欠账）、`change-record.md`                                                        |

### 1.5 变更留痕（本规格推翻 / 修订的既有决议，开工前须逐条确认）

| # | 既有决议                                     | 本规格处置                                    | 依据                  |
| - | ---------------------------------------- | ---------------------------------------- | ------------------- |
| 1 | **Q9**「工具结果只落摘要 + `args_digest` + `sha256`，永不落正文」（P2a 定死，安全关键） | **修订**：新增「执行输出 / 文件变更的**有界摘录**」通道；**仍不落全文、不落二进制、不进审计** | §2.6；用户裁决 2026-09-17 |
| 2 | **P2b**「审批后推进的过程事件本期不做」                    | **推翻**：resume 路径接入帧写入（批次 G/H）            | §2.8                |
| 3 | 契约 **Y1**「不加工具目录只读端点」                     | **推翻**：新增模型 / 工具候选只读端点（仅 `super_admin`）  | §2.10               |
| 4 | P2b §1.3-6「`027` 密文列是唯一受控例外，其解密内容不得外溢到帧」  | **保留**（密文不外溢不变）；新增例外**只作用于执行输出与文件变更摘录** | §2.6                |
| 5 | P1「消息表 append-only，不提供编辑 / 删除」            | **修订（二次裁决收紧）**：删除走**物理删除内容行**（消息 / 帧 / 流状态 / 幂等行；会话行软删 + 标题清空，运行与审计保留）；**仍无通用 update / delete 接口**，仅此受控入口    | §2.11；二次裁决 |
| 6 | 立项 §17.3「文件改动 diff / 终端输出」面板           | **从"按阶段"兑现**（原列表已含，缺的是数据源，由 G/H/J 补齐）     | §2.6/§2.7           |
| 7 | 本规格 §1.3-1（原文）「收尾检查只展示，不改状态、不退回」        | **修订**：升级为**结构判定 + 一键人工重做**（判定不改运行状态；重做＝一次新的正常调用，不自动重跑）             | §2.5；二次裁决        |
| 8 | P1 / P2b §1.3-8「不做会话分享与多端协同」               | **推翻**：纳入 P2c-6（本租户指定用户只读分享 + 受邀成员可发言）；**「不做实时在线态」保留**；`P2b 规格` §1.3 回改随 P2c-2 契约修订一并落 | §2.16；二次裁决       |

***

## 2. 设计

### 2.1 侧栏重组（事项 A · Q10 落地）

| 分组        | 入口                     | 与 §17.2 的关系                                                          |
| --------- | ---------------------- | --------------------------------------------------------------------- |
| **对话**    | 对话（**默认视图**）           | 采纳                                                                    |
| **任务与项目** | 概览（原「首页」）、内容工作台、历史草稿、协同动态 | 采纳 + 首页归档为「概览」（零改动）；「任务中心」页面不存在 ⇒ **不建空入口**                          |
| **员工**    | 员工与岗位、数字员工设置           | 采纳；「数字员工工作看板」前端不存在 ⇒ 本期不建                                             |
| **资产**    | —（本期不建组）               | 偏离：记忆与画像 / 技能与工具前端页面不存在 ⇒ 不建空入口                                      |
| **知识**    | 知识权限管理                 | 采纳（「知识库」页面不存在）                                                        |
| **治理**    | 安全与审计、通知、用量与费用         | 采纳；「审批待办」无独立页面（审批落收件箱 / 运行详情 / 对话内联卡）⇒ 不建独立入口                        |
| **客户与商务** | 客户、商机、报价、合同、进度概览       | **新增**（§17.2 起草时 CRM 前端尚不存在；P5a 五视图已交付）                              |

* `SECTIONS` 改为「分组 = 入口数组」显式结构；默认视图 `home` → `conversation`；`?view=home` 仍可用。
* 导航点击、常驻挂载、未读角标机制原样保留；**每条入口必须指向已交付页面**（本表即全集核对）。

### 2.2 对话页三区（事项 B）

| 区         | 内容                                                                       | 数据源                                 |
| --------- | ------------------------------------------------------------------------ | ----------------------------------- |
| ① 会话列（左）  | 现有列表（筛选 / 分页 / 新建 / 归档）原样保留                                              | `GET /conversations`                |
| ② 对话流（中）  | 消息 + **过程折叠条**（运行中：当前步 / 计数；终态：收为一行）                                    | 消息 = 会话详情；过程 = 帧                    |
| ③ 右侧舞台（右） | **运行概览** / **过程时间线** / **工具调用流水**（= 时间线工具视图）/ **终端输出**（I 批）/ **文件改动**（I 批）/ **产物**（K 批）/ **审批** | 运行指标、帧、产物登记、run 审批接口                |

* 舞台「当前 run」= 发送响应 / 帧流优先，否则会话**最新 run**；无 run ⇒ 空态文案（不摆假面板）。
* **面板按批次出现**（P2c-1 出前三块；I / K 批补齐终端、diff、产物）；未落地前**不预置空面板**（§17.3 纪律）。
* 保留期降级：帧 7 天 / 产物登记保留期（§5）到期后，对应面板显示「已过期」如实告知；运行概览与审批（既有接口）不受影响。
* 窄屏（<1024px）：舞台折叠为抽屉（默认收起）。

### 2.3 流消费（事项 C）

**为什么不用 `EventSource`**：认证与租户态走自定义请求头（§0 事实 4）⇒ `fetch` + `response.body.getReader()`；解析用 **`eventsource-parser`**（MIT、无依赖、只做 SSE 行协议解析）或等价自建（二选一，§5）。

| 时机     | 口径                                                                                            |
| ------ | --------------------------------------------------------------------------------------------- |
| 打开（发送） | 结构化调用发出后**立即并发打开**（`run_id` 缺省 ⇒ 服务端自动发现新 run；保证边执行边看）                                        |
| 打开（回放） | 进入会话页对「最新 run」回放：不带 `after_seq` ⇒ 从 `seq 1` 补发已落帧，终态即关流                                      |
| 续播     | 重连带 `Last-Event-ID: <已收最大 seq>`（服务端取 `max(头, after_seq)`）                                    |
| 重连     | 断网 / `503` ⇒ 指数退避（1s→2s→4s→8s，上限 15s）+ 抖动；`401/403/404/422` ⇒ 不重连，进错误态                                |
| 空转上限   | 连续多轮无新帧且 run 非活跃 ⇒ 停止并显示「无可用过程数据」                                                             |
| 关流     | `is_terminal` 帧 ⇒ 关流并重取「详情 + 列表 + 运行概览」；`stream.unavailable` 帧 ⇒ **显式告知行**后关流                    |
| 主动关闭   | `202` 待批返回后关流（待批后无终态帧）；切会话 / 视图 `hidden` / 卸载 ⇒ `AbortController.abort()`；回来自动续播             |

**状态隔离**：帧流状态（`frames[]` / `lastSeq` / 连接态）独立于主 state；帧 ≤100ms 合批入 state。

* **run 解析的当前缺口（P2c-2 补齐）**：帧内不含 `run_id`，`GET .../stream` 也未回传 ⇒ 舞台的**运行概览 / 审批**目前只在「本次发送产生了运行」时可用（`X-Stream-Run-Id`）；**进入历史会话**只回放过程时间线，概览与审批显示空态（如实告知，不摆假面板）。**P2c-2 的契约修订条目（已写入 `api-contract.md`，2026-09-17）**：SSE 读端**只增** ① 响应头 `X-Stream-Run-Id`（连接建立时已解析到 run 才出现）与 ② **每帧 `data` 内 `run_id`**（覆盖「连接建立时无 run、稍后新 run 出现」与多客户端场景）——届时历史会话的概览与审批一并可用。
* **无运行时如实告知**：结构化调用返回**没有运行**（后端未装配真实执行 ⇒ 回落桩路径）时，前端**关流并给出「本次没有过程流」提示**——不得留下永远「执行中」的假过程条（已实现，见 §0 交付记录）。

### 2.4 发送路径路由（事项 D）

| 输入形态                    | 路径                                     | 结果                                                    |
| ----------------------- | -------------------------------------- | ----------------------------------------------------- |
| 结构化工具调用 JSON（`tool_key` + `params` 对象） | `POST .../messages:stream` + 新幂等键      | 真实执行；`201/202/拒绝码/504` 原样；取 `X-Stream-Run-Id`；开流         |
| 纯文本                     | `POST .../messages` **不带键**             | 桩回复（不写帧、无流）；界面显式提示「未触发真实执行」                          |

* 判定只是**路径选择**，不是权限判定；服务端仍唯一权威。修复 §0 事实 5 的不一致。

### 2.5 过程与审批呈现（事项 E）

* **帧 → 行映射**：复用 `RUN_EVENT_LABELS` 十种 + `message.*` + `stream.unavailable`；payload **只渲染白名单字段**（既有 `RUN_EVENT_PAYLOAD_FIELDS` + I / J 批新增的受控字段）；未知键 / 未知 kind **不渲染、不猜测**。
* **过程折叠条**：运行中一行摘要可展开；终态收为一行；`message.*` 帧不渲染正文（只触发一次详情重取）。
* **内联审批卡**（三条判据借调研 H，来源已更正）：
  1. 决议入口唯一：`POST /runs/{run_id}/approvals/{approval_id}/approval`（**不新增契约**），请求体 `{"approved": bool}`；
  2. 权威态服务端回流：**无本地乐观更新**，决议后重取；`409` ⇒ 重取展示最新；
  3. 卡类型由结构字段判定（`kind='approval.requested'` + 审批 `status`），不由文案猜。
* **角色口径**：仅 `ceo`/`super_admin` 且非发起人显示决议按钮；其他显示只读说明；服务端仍 `403`（按钮隐藏 ≠ 权限）。
* **收尾检查（自动验收 + 一键重做 · 二次裁决）**：运行终态后，折叠条与舞台展示「进度档」= 完成步骤数 / 总步骤数 + 未决审批 + `finish_reason`，并给出**结构判定结论「达标 / 未达标」**——三条件**全满足**＝达标（步骤全部完成 + 无未决审批 + `finish_reason` 为正常终态），**不调模型、只读运行已有字段**。未达标时提供**一键重做**：**仅当本页仍持有原结构化调用**时以**新幂等键**重发（＝一次新的正常调用，与原运行无状态耦合、不改写原运行）；页面已不含原件（刷新 / 跨端）时按钮降级为提示「原始参数未留存（安全口径），请重新输入」。**判定不改运行状态；不做自动重跑。**

**实现期裁定（2026-09-17 · P2c-4）**：
1. **判定落点 = 服务端只读端点** `GET /api/v1/runs/{run_id}/acceptance`（纯读：不调模型、不写库、不改运行状态）——前端**不自行复算规则**，只渲染结论与三个 `checks`；判定落服务端才能被真库用例覆盖「不调模型」与「不改运行状态」两断言。
2. **「正常终态」的受控取值 = `run_completed`**（唯一）；`cancelled_by_user` / `step_failed` / `approval_rejected` 均判**未达标**；非终态运行（无 `finish_reason`）返回 `unmet`（如实，不谎报）。
3. **步骤口径沿用既有前端展示口径**：`step_count = 0` 视为满足（`completed >= total` 的退化情形），避免「无步骤的空运行」被误判未达标。
4. **一键重做是前端行为**：`ConversationPage` 在发送后保留本次结构化调用原文（**仅内存态**，刷新即失），未达标且持有原件时按钮可用；重发走同一发送路径 + **新幂等键**（新 run）；不落库、不新增留存例外。

### 2.6 内容级回传（事项 G · Q9 边界修订）

**新增的受控通道**（修订 Q9，仍不落全文）：

| 字段（`tool.result` payload 扩展） | 内容                                                                  |
| --------------------------- | ------------------------------------------------------------------- |
| `output_excerpt`            | `cmd.run` / `fs.read` 的**文本输出摘录**（截断到上限）                              |
| `output_truncated` / `output_bytes` | 是否截断 + 原始字节数（截断必须**显式告知**）                                        |
| `file_changes`              | 文件变更数组：`{virtual_path, change_kind, bytes, sha256, diff_excerpt?}`（最多 N 条，超出截断告知） |

**硬边界（不可协商）**：

1. **有界**：`WORKBENCH_OUTPUT_EXCERPT_MAX_BYTES`（默认 **16 KiB**，范围 0–256 KiB，`0` = 关闭回传）；单文件 `diff_excerpt` 默认 **8 KiB**；`WORKBENCH_FILE_CHANGES_MAX`（默认 **50** 条/步）。
2. **非文本不回传**：非 UTF-8 / 二进制只留 `bytes` + `sha256`（不落内容）。
3. **脱敏**：一律过 `redact_payload`（键名 + 值形状；掩码幂等）；宿主真实路径**不得**出现（只用虚拟路径）。
4. **不进审计、不进消息表**：审计仍为最小集；消息仍为 U23 摘要。
5. **保留期随帧（7 天）**；帧字节熔断（4 MiB/run）**继续生效**——大输出会更快触熔断（登记为运维可调参数，§5）。
6. **回传失败 / 超限不影响执行结果**（流是视图）。
7. **`027` 密文列仍不外溢**：解密内容不得进帧（原口径保留）。

**实现注意（登记给实现期）**：容器输出必须在 `remove_container()` **之前**读取（`container.logs()`，有界读取）；工作卷 tmpfs 即毁 ⇒ 变更记录必须在执行时由执行链路产出（§2.7）。

### 2.7 `fs.*` 落地与产物登记（事项 J / K）

* **`fs.*` 容器执行补完**（段二-3 遗留，事实 9）：`fs.read/list/stat/write/overwrite/delete` 在容器内落地；**路径闸门 ③ realpath + ④ 黑名单原样生效**；`artifact.export` 保持默认不装配。
* **文件变更记录**：`fs.write/overwrite/delete` 执行时产出 `file_changes`（§2.6），随 `tool.result` 帧回传；**不依赖事后扫描**（tmpfs 即毁）。
* **产物登记（新表）**：`workbench_run_artifacts`（`tenant_id` / `run_id` / `artifact_id` / `virtual_path` / `change_kind` / `bytes` / `sha256` / `created_at` / `expires_at`），写进复合外键（跨租户拒写同既有手法）+ 只读端点 `GET /api/v1/runs/{run_id}/artifacts`（归属判定同运行接口）；保留期与清理并入 worker 周期任务（逐租户）。
* **产出 chip**：对话流内由 `file_changes` 聚合成 chip（点击展开 diff 摘录 / 跳运行详情）；跨运行查询走产物端点。

**实现期裁定（2026-09-17 · P2c-3 开工取证后，逐条留痕）**：

1. **落地形态取证结论（§6-5 收口）**：执行镜像 = `python:3.12-slim@sha256:7838…`（钉死，段二-3 已取证）⇒ 容器内**保证存在 `python3`**；`fs.*` 采用**自建内联脚本**（`python3 -c <脚本> --op …`，结构化 argv，不经 shell），**不依赖 coreutils 变体差异**（`file` 等命令在该镜像中不保证存在）。
2. **内容传递**：`fs.write` / `fs.overwrite` 的 `content`（body 类参数）以 **base64 经 argv** 传入（不经 env / 不经卷）；唯一入口 `messages:stream` 的**消息长度上限 8000 字符**，故 argv 量级安全；脚本侧对超限（>96 KiB）**fail-closed 拒绝**（不截断内容）。
3. **「空工作卷」下的工具语义**（事实 11 的直接后果：**文件不跨执行留存**，故「覆盖既有」「删除既有」在跨执行场景不可达）：
   * `fs.write` = 新建（目标已存在 ⇒ 拒绝）；
   * `fs.overwrite` = 覆盖语义写入（存在 ⇒ 替换记 `overwritten`；不存在 ⇒ 新建记 `created`）——即「允许目标存在的写入」；
   * `fs.delete` = 幂等删除（存在 ⇒ 删除记 `deleted`；不存在 ⇒ 成功且**不产出变更记录**，不伪造变更）。
   口径已写入契约「内容级回传」硬边界第 7 条；**不因该语义放宽容器边界**（tmpfs / 只读根 / 非 root / 无外网一律不动）。
4. **端点与清理口径**：`GET /api/v1/runs/{run_id}/artifacts` 归属判定**复用运行接口口径**（`workbench_run_records` + 承载任务可见性 ⇒ 跨租户 / 不可见 `404`）；**保留期已到的条目不再返回**（保留期外如实降级）；保留期 `WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS`（默认 30）、清理间隔 `WORKBENCH_RUN_ARTIFACT_PURGE_INTERVAL_SECONDS`（默认 3600s）。
5. **截断告知字段**：`file_changes` 超 `WORKBENCH_FILE_CHANGES_MAX` 时置 `file_changes_truncated=true`（**只增**字段，缺省不出现 ⇒ 既有帧逐字节不变）。

### 2.8 审批后推进的过程事件（事项 H）

* resume（决议后推进）路径接入**同一** `StreamWriter`：写 `tool.call` / `tool.result` / `step.started` / `run.completed|failed` 等既有 kind（不新增 kind）；同一 run 的 `seq` 继续单调递增（状态行已终态时**先重开**——`status` 置回 `streaming` 并清 `expires_at`，或按 §5 的备选以「新 run」呈现）。
* 仍**先落库、再推送**；熔断与保留期口径不变；`202` 后的推进帧与「首次结果帧」同属一个 run 序列。

### 2.9 每会话模式（事项 L）

* **落库**：`workbench_conversations.mode TEXT NOT NULL DEFAULT 'craft' CHECK (mode IN ('ask','plan','goal','craft'))`。
* **语义与合成（只收紧、不放松）**：

| 模式      | 语义                 | 与自治三档合成                     |
| ------- | ------------------ | --------------------------- |
| `ask`   | 只问答：**拒绝一切真实执行**   | 覆盖（最严）：执行入口受控拒绝 + 审计        |
| `plan`  | 先计划后执行：**一律先落待批**  | 强制 `requires_approval=true`（等价 `approval_for_all`） |
| `goal`  | 目标驱动：执行照常 + 收尾检查可见 | 不放松（按自治三档）                  |
| `craft` | 完整执行（**默认**，＝现状）   | 不放松（按自治三档）                  |

* **判定位置在服务端**：`ask` / `plan` 在**发起与推进两处**都生效（fail-closed）；前端只做选择与提示。
* **谁能改**：会话**发起人**（本人）；`ceo` / `super_admin` 对他人会话**只读**（与「修改他人会话 `404`」一致）。变更写审计 `conversation.mode.changed`（受控枚举，不落自由文本）。
* 与 D3 的关系：回答「两轴关系」——自治三档决定「要不要人批」，模式决定「本次会话允不允许执行 / 是否先计划」；**合成取更严**。

**实现期裁定（2026-09-17 · P2c-4）**：
1. **改动端点 = `POST /api/v1/conversations/{conversation_id}/mode`**（请求体 `{"mode": ...}`，`extra=forbid`）；仅本人（他人 / 跨租户 `404`）；归档会话 `409`；**设为同一值无副作用**（不写审计）；变更写审计 `conversation.mode.changed`（`from_mode` / `to_mode` 受控枚举）。
2. **`ask` 拒绝码 = `409`**「该会话为只问答模式，已拒绝执行」（与「归档发消息 `409`」同一「状态不允许」语义；不是 403——操作者并无权限问题）；拒绝时**不创建承载任务 / 运行 / 消息**，但按 §4.1.3 四态口径写 `rejected` 幂等行 ⇒ 重放返回同一 `409`；审计 `conversation.execution.rejected`（`conversation_id` / `mode` / `reason=mode_ask`）。
3. **推进处拦截点 = 决议入口**（`POST /runs/{run_id}/approvals/{approval_id}/approval` 的处理器**最前**）：会话模式为 `ask` ⇒ 返回 `409` 并**不做任何决议写入**（待批动作保持 `pending`，切回模式后可再决议）——fail-closed：宁可拒绝决议，也不产生「已批准但被模式挡住」的悬挂授权位。运行经幂等行（`find_by_run`）反查会话；查不到会话（如非对话触发的运行、或会话内容已物理删除）⇒ 不拦截（已知边界，见契约同节）。
4. **`plan` 的推进天然不放松**：强制待批在发起处已置 `requires_approval=true`；推进只能经 `find_approved`（未授权一律 `409`），故无需新增判定分支。
5. **`ask` 不影响「缺键桩路径」**：`ask` = 只问答 ⇒ 纯文本问答（桩回复）仍可用；只有**带键的真实执行**被拒。

### 2.10 模型 / 工具选择器（事项 M）

* 新增**只读**端点（仅 `super_admin`，均不返回任何凭据 / 内部地址）：
  * `GET /api/v1/workforce/model-candidates` → `registered_model_keys(settings)` 的候选键列表；
  * `GET /api/v1/tools/catalog` → 工具键 + 风险档 + 是否需审批 + 简介（来自 `ToolSpecCatalog`）。
* 前端：数字员工配置页的 `model_key` 由自由文本改为**候选下拉**，`tool_allowlist` 改为**目录多选**；不可用 / 停用项**灰显并给原因**（借调研 F 形态：聚焦动作 + 原因）。
* **推翻 Y1 留痕**（§1.5-3）；后端校验不变（非法键仍 `422`），前端只是提示。

**实现期裁定（2026-09-17 · P2c-4 开工取证后）**：
1. **取证结论：`tool_allowlist` 存在两个不同集合，端点必须如实分开表达**——① **执行工具目录**（`ToolSpecCatalog`，**实测 13 键**：`fs.list/read/stat`、`cmd.run`、`fs.write/overwrite/delete`、`artifact.export`、CRM 读 ×4 + `crm.activity.log`，含风险档与审批要求；§0 事实 8 起草期记的「16」为笔误，已回改实测值）；② **保存闸门集合**（`AgentConfigService.allowed_tools` = `WORKBENCH_PLANNER_TOOLS` 声明的键，与 ① **不是同一批名字**，见攻击面报告里的 `content.publish` / `knowledge.search`）。若只回 ①，界面会把「点了能存」与「存了会被 422」混为一谈（宪法禁止「把能点当能用」）。故 `GET /api/v1/tools/catalog` 返回 **`items`（执行目录，含风险档 / 审批 / 参数角色）+ `allowlist`（保存闸门键名）** 两个列表，前端据此灰显并给原因；**保存仍以服务端校验为准**（不改变后端校验强度）。
2. **模型候选端点与配置保存闸门同源**（`registered_model_keys(settings)`），候选为空即本部署未注册模型键——界面明说「只能使用默认模型」，不摆假下拉。
3. 两个端点都**只读 + 仅 `super_admin`**：与既有 `GET /workforce/agents/{agent_key}/config` 同权限（配置面本就是超管面）；`employee` / `ceo` 一律 `403`。

### 2.11 个人数据导出 / 删除（事项 N · 合规）

* **导出**：`GET /api/v1/conversations/exports/mine`（本人全部会话 + 消息 + 归档状态；含既有字段，**不含他人数据、不含审计明细**）；导出动作写审计。**如实说明**：用户原始输入自 U23 起只落**脱敏摘要**，导出返回的是库中实际存在的字段。
* **删除（物理删除内容行 · 二次裁决修订）**：`POST /api/v1/conversations/{id}/delete`（仅本人；跨租户 / 他人一律 `404`；复删**幂等**）：
  * **真删**（引用图已静态核对：[023](file:///d:/徐徐AI学习/公司工作台/migrations/023_conversational_agent.sql#L30-L45) 消息行 → [036](file:///d:/徐徐AI学习/公司工作台/migrations/036_conversation_stream.sql#L17-L55) 帧行 / 流状态行 → [027](file:///d:/徐徐AI学习/公司工作台/migrations/027_dsh_tool_execution.sql#L107-L133) 该会话幂等行；**先删幂等行**——它同时引用消息行与会话行）：`workbench_conversation_messages` / `workbench_conversation_stream_frames` / `workbench_conversation_stream_state` / `workbench_execution_idempotency`（该会话全部键）；
  * **会话行不物理删**：置 `deleted_at`（软删，列表 / 详情 / 流 / 发消息一律 `404`）+ **标题清空**（`title=''`，防残留敏感信息）；
  * **保留**：运行记录（`workbench_run_records`，经任务关联，无会话外键）、待批动作（[027](file:///d:/徐徐AI学习/公司工作台/migrations/027_dsh_tool_execution.sql#L50-L86) 只挂运行不挂会话）、审计（不含正文）、产物登记（**运行级、仅元数据**）；
  * **无管理端代删 / 批量删**；删除为**同步**操作（单会话内容行量级小）；删除与导出均写审计（受控键，不落正文）。
* **合规边界**：本期只做「本人会话」；租户级导出 / 删除仍走既有租户生命周期口径（不在本期）。

**实现期裁定（2026-09-17 · P2c-4）**：
1. **导出分页与上限落定**：页单位 = **会话**（`limit` 1–500 默认 500，按 `created_at` 降序）+ `offset`；**条目上限 50000**（本人在库「会话数 + 消息数」合计）——超限**不静默截断**：`truncated=true` + `limit_reason="total_items_exceeded"`（单页装配同样受该上限保护）。上限为**模块常量**（测试可注入更小值以覆盖截断路径，生产默认不变）。
2. **导出审计**：`conversation.exported`（`conversation_count` / `message_count` / `truncated`，**不落正文**）；每次成功调用写一条。
3. **删除端点 = `POST /api/v1/conversations/{conversation_id}/delete`**（同步；返回四个删除计数 + `deleted: true`）；**复删幂等且不重复写审计**（真正无副作用：不再删、不再记）。
4. **删除顺序与原子性（取证结论：三张表分属不同仓储，故按序两步、各自原子）**：① **幂等行 → 帧 → 流状态**（各自仓储删除；幂等行必须最先删——它同时引用消息行与会话行）；② **消息 + 会话行软删 + `title=''`（同一事务）**。失败语义：**会话在最后一步完成前保持可见**（不出现「看不见但内容还在」）；各步可安全重试；帧清理失败不回滚删除结果（孤儿帧由保留期清理兜底，且已不可见）。
5. **删除后的可见性**：`deleted_at IS NOT NULL` 的会话在**所有读路径与写路径**统一 `404`（列表 / 详情 / 流 / 发消息 / 改模式）；删除**不影响**运行记录、待批动作、审计、产物登记（运行级元数据）。
6. **前端导出形态**：客户端**逐页拉取并合并**为一个 JSON 文件下载（客户端循环上限 = 服务端上限 100 页 × 500 会话），到顶或 `truncated` 即停止并在界面如实告知；不是服务端打包接口。

### 2.12 多端（事项 O / P）

* **PWA**：新增对话面板（列表 / 消息 / 发送 / 过程折叠条简化版）；复用既有登录态与审批页；**不做**侧栏重组与右舞台；流消费复用同一读端实现（抽公共模块或复制最小实现，§5）。
* **桌面端**：Electron 外壳加载 admin-web ⇒ **零改造**；需核对 `fetch` 流式读在 Electron 下的行为与 CSP（§6 未验证）。

### 2.13 性能 / 可访问性 / 状态纪律（事项 F）

* 帧入 state ≤100ms 合批；过程时间线渲染窗口 ≤500 行；消息沿用现有分页（不改无限滚动）；底部跟随阈值 120px + 「有新内容」按钮。
* 时间线 `role="log"` + `aria-live="polite"`；连接状态用文本；流更新不改焦点。
* 状态词沿用既有中文标签；未知取值原样显示。

### 2.14 借鉴清单裁定（P2c 相关条目；来源以 2026-09-13 更正后为准）

| #                                   | 裁定                    | 落点 / 理由                                                          |
| ----------------------------------- | --------------------- | ---------------------------------------------------------------- |
| A 内联审批卡（OpenMausBot）                 | 纳入（形态适配）              | §2.5：不新增 respond 端点；不采用「接管输入区」                                   |
| B 一行流 + 可展开卡                        | 纳入                    | §2.5 + §2.6（新增内容级字段仍走白名单 + 截断告知）                                |
| C 产出 chip（实为 OpenWorkBuddy）         | **纳入**（本轮范围扩张后具备数据源）  | §2.7                                                             |
| D 权限可解释口径                           | 纳入（文案级，开工先核对）         | §2.10 选择器 + 员工配置页说明                                              |
| E 收尾「未打勾退回」（实为 OpenWorkBuddy）       | 部分纳入（**展示型**，不退回）     | §2.5 收尾检查                                                        |
| F 模型选择器灰显给原因                        | 纳入（端点落地后）             | §2.10                                                            |
| G 性能判据（数字未复现）                       | 纳入（判据自定）              | §2.13                                                            |
| H 审批 UX 三判据                         | 纳入                    | §2.5                                                             |
| J 不卡顿结构手法                           | 纳入（最小集）               | §2.13                                                            |
| K 状态命名纪律                            | 纳入                    | §2.13                                                            |
| （调研 I）SSE supervisor                 | 契约由 P2b 承载；读端按 §2.3 实现 | —                                                                |

### 2.15 并发与异常边界（设计口径）

| 场景                              | 口径                                                     |
| ------------------------------- | ------------------------------------------------------ |
| 同会话连续两次发送                       | 各自 run 独立；舞台跟随最新 run，旧 run 帧组按 `run_id` 分组保留             |
| 发送后切会话 / 离开视图                   | abort；回来自动续播（`lastSeq` 按会话隔离，内存态，刷新从 0 回放）                |
| 断网 / 后端重启                       | 退避重连 + `Last-Event-ID` 续播；空转上限后停止并告知                      |
| 决议后推进（H 批）                      | 同一 run 续写帧；读端重新命中该 run 继续尾随                             |
| 熔断 / 悬挂                         | `stream.unavailable` 显式告知；执行结果以消息 / 运行 / 审计为准              |
| 内容级回传超限                         | 截断 + 显式告知（`truncated`/`original_bytes`）；继续执行不中断          |
| `mode=ask` 收到结构化调用              | 服务端受控拒绝 + 审计；前端提示「该会话为只问答模式」                           |
| 删除后访问                           | 列表 / 详情不可见（`404`）；复删幂等；审计仍可查                           |
| 导出超大数据集                         | 上限与分页口径（§5）；超限如实告知，不静默截断                               |
| 成员并发发言（R/S 批）                   | 消息 append-only 无写冲突；**同一会话多 run 并存的既有口径不变**（各自独立、按 `run_id` 分组）——**不新增 409 串行化**（守住零破坏） |
| 分享撤销（R 批）                       | 已读内容不可撤回（如实告知）；撤销后新读请求 `404`；撤销写审计                       |
| 一键重做（Q 批）                       | 未达标 ⇒ 用户触发的新一次调用（新幂等键、独立 run）；与原运行无状态耦合；页面不含原件时降级为提示 |
| 物理删除（N 批）                       | 同步真删内容行；删除后所有读路径 `404`；复删幂等；审计行数不变                        |

### 2.16 会话协作：分享与多端协同（事项 R / S · P2c-6 · 二次裁决新增）

* **成员表**（迁移 `037+`）：`workbench_conversation_members`（`tenant_id` / `conversation_id` / `member_id` / `permission`（`read` / `write`）/ `added_by` / `created_at`；主键 `(tenant_id, conversation_id, member_id)`；复合外键引用会话表）；成员必须**同租户、已审批、非 `customer_admin`**（对话入口本就是 `403`）。
* **可见性判定（唯一新增授权轴）**：会话列表 / 详情 / 消息 / 帧流 / 运行概览 / 审批的**读路径统一为「本人 ∪ 成员」**；`ceo` / `super_admin` 既有只读口径不变（**未被点名就不是成员**，不因角色自动可见他人会话）。
* **端点**（仅会话本人可增删；成员可读列表；**复用既有 `current_user` / 归属判定 / 审计**）：
  * `POST /api/v1/conversations/{id}/members`（`permission` 缺省 `read`）——`201`；非本人 `404`（与「修改他人会话 `404`」一致）；成员不合法（跨租户 / 未审批 / `customer_admin`）`422`；重复添加幂等；
  * `GET /api/v1/conversations/{id}/members`——本人或成员可见；
  * `DELETE /api/v1/conversations/{id}/members/{member_id}`——`204`；复删幂等；
  * 审计动作：`conversation.member.added` / `conversation.member.removed`（受控键，不落正文）。
* **协同（`write` 成员）**：可发言（含结构化调用）并触发执行——**执行一律以其本人身份走既有全部闸门**（工具白名单 / 自治三档 / 审批 / `critical` 仅 CEO 超管 / 发起人不得自审）；消息新增 `sender_id`（存量行 `NULL` ⇒ 展示回退为发起人 / 系统，**零破坏**）。
* **呈现**：消息气泡显示发言者（`sender_id` → 姓名 / 角色）；舞台显示**参与者列表 + 最近活动时间**——**不做实时在线态**（无 WebSocket 底座，不引入新实时组件，与 P2b §1.3-7 一致）。
* **边界**：跨租户 / 部门级 / 全租户 / 公开链接**均不做**；被分享者**不能**归档、改模式、删会话、增删成员（管理动作仍仅本人）。

***

## 3. 六要素（feature-inventory 回填稿）

| 要素        | 内容                                                                                                                                                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **谁用**    | 对话入口岗位（`employee` / `department_lead` / `ceo` / `super_admin`）；审批决议仅 `ceo`/`super_admin` 且非发起人；选择器与工具目录端点仅 `super_admin`；`customer_admin` 对话入口 `403`                                                                       |
| **输什么**   | 对话输入（纯文本 / 结构化调用）；会话模式（`ask/plan/goal/craft`）；删除 / 导出触发；**成员增删（分享 / 邀请）**；**一键重做触发**；舞台「当前 run」；PWA 同左（简化）                                                                                                |
| **得什么结果** | 三区可见；过程 / 终端 / diff / 产物按批次出现；审批内联决议服务端回流；模式与删除 / 导出 / **成员增删**写审计；**收尾给「达标 / 未达标」结构判定**；产物登记与帧按保留期治理；**前端零新增落点**（除流游标内存缓存）                                                                        |
| **角色与权限** | `401` 未认证；`403`（`customer_admin`、非审批角色决议、非 `super_admin` 访问候选端点、`read` 成员发言）；`404`（跨租户 / 他人会话 / 已删除会话 / 非本人增删成员）；`409`（归档发消息、已决议、运行终态、模式冲突）；`422` 非法参数 / 不合法成员；**「成员」是唯一新增授权轴，模式与成员均不得放松既有判定**                                                       |
| **正常流程**  | ① 打开即对话 → ② 选 / 建会话（可设模式）→ ③ 结构化调用 ⇒ `messages:stream` + 开流 → ④ 过程折叠条 / 时间线 / 终端 / diff / 产物逐步出现 → ⑤ 终态关流 ⇒ 重取详情 + 收尾检查（达标 / 未达标 + 一键重做）→ ⑥（如需）内联审批 ⇒ 决议后推进继续可见 → ⑦ 需要时导出 / **物理删除**本人会话 → ⑧（需要时）**分享给指定成员 · 成员发言协作**                                     |
| **异常与边界** | 纯文本走桩（无流）；流错误四态 + 退避重连 + 续播；内容回传截断显式告知、二进制不回传；`ask`/`plan` 服务端强制；熔断 / 悬挂显式告知；保留期外如实降级；**删除为真删（审计保留、复删幂等）**；**重做跨页降级为提示（原件不落库）**；**分享撤销后新读 `404`、已读不可撤回**；PWA 与 web 同语义 |

***

## 4. 测试与判据（先红后绿；风险分级：权限 / 数据外溢 > 数据正确性 > 交互 > 体验）

**P2c-1（前端）**：① SSE 解析（分块 / 中文跨块 / 心跳 / 坏 JSON）；② 读端（起点 0、重连带 `Last-Event-ID`、终态关流并重取、`401/403/404` 停连、`503` 退避、切会话 abort、空转上限）；③ 发送路由（结构化 ⇒ `messages:stream`；纯文本 ⇒ 无键）；④ 舞台白名单渲染 + **注入敏感键 ⇒ 不渲染**；⑤ 审批卡（`ceo` 可决议 / `employee` 只读 / 无乐观更新 / `409` 重取）；⑥ 侧栏 6 组 + 默认视图 + `?view=home` 兼容。

**P2c-2（后端 + 契约）真库用例**：① 输出回传有界（超限截断 + `truncated`/`original_bytes`；配置 0 = 关闭）；② 非 UTF-8 / 二进制不回传（只 `bytes`+`sha256`）；③ 脱敏（注入 `Bearer` / `sk-` / 凭据键 ⇒ 掩码且幂等）；④ 帧字节熔断仍生效（大输出 ⇒ `unavailable` 告知帧 + 审计）；⑤ resume 写帧（决议后推进产生帧、`seq` 单调、终态收口）；⑥ **零破坏哨兵**：旧 `POST /messages` 帧表计数仍为 0；⑦ 审计不被内容污染（`tool.executed` 明细键不变）。

**P2c-3（fs.\* + 产物）真库用例**：① `fs.write/overwrite/delete` 执行成功且变更记录入帧（虚拟路径 / 类型 / 字节 / sha256）；② 路径闸门 ③④ 仍拦（黑名单路径 ⇒ 拒绝 + `tool.blocked`）；③ `file_changes` 超上限截断告知；④ 产物登记写入 + 端点归属（跨租户 `404`）；⑤ 容器回归不变（`--network none` / 只读根 / 非 root / 工作卷销毁，既有容器用例原样重跑）。

**P2c-4（产品项）真库用例**：① `mode=ask` ⇒ 结构化调用受控拒绝 + 审计；② `mode=plan` ⇒ 强制待批；③ 合成取更严（`full_auto` + `plan` ⇒ 待批；任何模式不放松 `critical` 仅 CEO）；④ 模式变更审计 + 仅本人可改（他人 `404`）；⑤ 候选端点权限（`super_admin` 200 / `employee` 403；响应无凭据）；⑥ 导出只含本人数据（跨租户不可见）+ 审计；⑦ **物理删除**：删除后消息 / 帧 / 流状态 / 幂等行计数为 0、会话行仍在且 `title=''`、列表 / 详情 `404`、**审计行数不变且不含正文**、复删幂等、他人删除 `404`；⑧ **自动验收**：三条件各造一例（步骤未完成 / 有未决审批 / 非正常终态 ⇒ 未达标；全满足 ⇒ 达标）、**判定不调模型**（无模型调用断言）、判定不改运行状态；⑨ **一键重做**：重发按新幂等键成为新的正常调用，**原运行零变化**。

**P2c-5（PWA）**：对话面板组件测（登录态 / 列表 / 发送 / 简化流 / 错误四态）；既有审批 / 收件箱测试**零改动**。

**P2c-6（协作）真库用例**：① 分享：添加成员 ⇒ 成员可读（列表 / 详情 / 流）、非成员 `404`；② 撤销后新读 `404`、已读不可撤回（如实口径）；③ `read` 成员发言 ⇒ `403`；`write` 成员发言 ⇒ 成功且 `sender_id` 正确；④ 成员触发执行**按其本人身份**判闸门（`employee` 成员触发 `critical` ⇒ 拒绝；审批仍不得自审）；⑤ 不合法成员（跨租户 / 未审批 / `customer_admin`）⇒ `422`；非本人增删 ⇒ `404`；⑥ 审计动作 `conversation.member.added` / `.removed` 键名正确且不含正文；⑦ 存量消息 `sender_id=NULL` 的展示回退**零破坏**。

**反假测试（必须变红）**：① 回传不做上限 ⇒ P2c-2 用例 ① 红；② `mode=ask` 只在前端拦（后端放行）⇒ P2c-4 用例 ① 红；③ 删除只做软删 / 墓碑（消息行仍在）⇒ P2c-4 用例 ⑦ 红；④ 读端重连起点固定 0 ⇒ P2c-1 用例 ② 红；⑤ `file_changes` 不做路径白名单 ⇒ P2c-3 用例 ① 红；⑥ 成员判定只写前端 / 后端不限权 ⇒ P2c-6 用例 ③ 红；⑦ 验收判定改接 LLM ⇒ P2c-4 用例 ⑧「不调模型」断言红。

**一键全量**：`pytest`（全量 + 新文件，含 `compileall`）+ `admin-web`（vitest run + build）+ `companion-pwa`（vitest + build）+ `desktop`（node --test）+ 迁移从零应用（新迁移增量应用到本机测试库）；CI 6/6 job 全绿后销账（§0 补写回归记录）。

**手工走查（浏览器，≥1 次/批）**：三区布局与窄屏抽屉；结构化调用全流程（含 `202` → 决议 → **推进可见**）；终端 / diff / 产物面板；`mode=ask` 与 `plan` 实际行为；导出 / 删除闭环；断网重连续播；PWA 对话面板。**熔断告知不可人为造** ⇒ 未取证则标未验证。

***

## 5. 待裁决项（评审时答复）

| #   | 事项                                      | 推荐                                                                     | 备选 / 理由                                                                        |
| --- | --------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 1   | **五批结构**（P2c-1…5）与实施顺序                  | **按 §7 顺序**（前端交互 → 内容回传 → 工具面 → 产品项 → PWA）                             | 一次性全做（无法逐批验收）                                                                  |
| 2   | **内容级回传边界**                             | 16 KiB/次、diff 8 KiB/文件、变更 50 条/步、二进制不回传、过 `redact_payload`、随帧 7 天      | 更小（4 KiB）/ 更大（64 KiB）；**不落全文**这条不动                                             |
| 3   | 帧字节熔断上限（4 MiB/run）                     | **维持默认**，登记为运维可调（回传放大了帧体积）                                           | 上调到 8/16 MiB（须同步清理与压测）                                                        |
| 4   | 产物登记保留期                                 | **30 天**（与运行事件对齐）                                                      | 与流一致 7 天 / 更长 90 天                                                             |
| 5   | `mode` 语义与合成规则（§2.9）                    | **取更严**：`ask` 拒执行 / `plan` 强制待批 / `goal`·`craft` 不放松；默认 `craft`；发起与推进都生效 | 允许模式放松判定（**不允许**：与宪法「自治等级不决定绕开权限」冲突）；模式改动频率限制                                  |
| 6   | 谁能改 `mode`                              | **仅会话本人**（管理角色只读）                                                      | 允许 `super_admin` 代改（须另立审计口径）                                                    |
| 7   | 选择器端点权限与 Y1 推翻                         | **仅 `super_admin`**、只读、无凭据；`tool_allowlist` 由自由文本改目录多选                   | 保留自由文本（放弃选择器）                                                                  |
| 8   | 导出 / 删除语义                               | **导出 = 本人全部会话（库内字段）**；**删除 = 软删 + 内容墓碑 + 审计保留（不含正文）**；复删幂等            | 物理删除（**不做**：与审计 / 溯源冲突）；仅导出不删除                                                 |
| 9   | 导出规模上限                                  | 分页导出（每页 500 条）+ 总量上限（如 5 万条）超限如实告知                                     | 单次全量（大租户会拖垮）                                                                   |
| 10  | PWA 范围                                 | **新建对话面板（含简化流）**，不做侧栏 / 舞台                                             | 仅做审批内联（不做对话）                                                                   |
| 11  | 前端技术栈                                 | **路由维持 `?view=`（不引路由库）**；**SSE 解析引入 `eventsource-parser`（MIT）**        | 引入 `react-router`（改动面大、收益低）；完全自建解析（约百行，边界自担）                                   |
| 12  | PWA 流读端复用方式                             | 抽**共享模块**（同仓 workspace 或复制最小实现）                                         | 各自实现（重复代码）                                                                     |
| 13  | 内容级回传是否也回传 `crm.*` 工具结果                | **不回传**（CRM 已有受控出口与掩码口径）                                               | 回传（口径扩散，不建议）                                                                   |
| 14  | `mode` 与既有会话的兼容                         | 存量会话 `DEFAULT 'craft'`（＝现状，零行为变化）                                 | 回填其它值（**不做**）                                                                   |
| 15  | **自动验收判定源与退回方式（二次裁决）**              | **已裁决：结构判定**（步骤全完成 + 无未决审批 + 正常终态）+ **一键人工重做**（判定不改状态、不自动重跑） | LLM 判分（无 rubric 真源、幻觉与成本）/ 自动重跑（额度循环）——均**不做**                                |
| 16  | **分享范围与权限（二次裁决）**                    | **已裁决：本租户指定用户 · 只读（`read`）+ 可撤销 + 审计**；`write` 仅经「邀请协作」显式授予          | 部门级（无组织 / 部门树）/ 全租户 / 公开链接——均**不做**                                                   |
| 17  | **物理删除范围（二次裁决）**                     | **已裁决：真删消息 / 帧 / 流状态 / 幂等行；会话行软删 + 标题清空；运行与审计保留**                | 墓碑化（原方案，作废）；连会话行一起真删（断引用链，**不做**）                                                     |
| 18  | **协作并发口径（二次裁决）**                     | **已裁决：成员可发言；同会话多 run 并存的既有口径不变（不新增 `409` 串行化）；不做实时在线态**     | 严格串行（改动既有行为，零破坏优先故不做）；在线态（无实时底座）                                                   |
| 19  | 重做的可用边界（原件不落库）                        | **已裁决：页面内一键重发（新幂等键）；跨页 / 刷新后如实告知「请重新输入」**                    | 新增加密参数留存例外（**不做**：与「有界摘录」口径冲突，`027` 仍是唯一受控例外）                                          |

***

## 6. 未验证登记（如实）

1. **P2c-1 / P2c-2 / P2c-3 / P2c-4 已交付**（见 §0 交付记录）；**其余批次（P2c-5 / P2c-6）尚未实现**（未验证）。
2. **反代下 SSE 缓冲**未实测（P2b §6-2 同项）；**长连接资源画像**未压测。
3. **Electron（桌面端）下 `fetch` 流式读与 CSP** 未核对（§0 事实 18；P2c-5 核对项）。
4. **`container.logs()` 有界读取在超长输出下的行为**（内存 / 截断点）：**常规输出已由真容器用例覆盖**（P2c-3）；
   **超长输出（> 硬上限）与极端截断点的内存画像**仍未实测（须 staging / 压测取证）。
5. **`fs.*` 容器内落地的具体实现形态**：**已取证并落地**（P2c-3）——执行镜像保证 `python3`，采用自建内联脚本（§2.7 实现期裁定 1–2）；**coreutils 命令集在该镜像中不保证齐备**（`file` 等），故不依赖它们。
6. **内容级回传对帧体积与熔断触达率的影响**未量化（§5-3 参数须在 staging 校准）。
7. **PWA 现状无对话能力**（§0 事实 17）⇒「PWA 消费流」实为新建面板，工作量按新建计（不得读作"接一下流"）。
8. **调研来源更正**（C/E/G 实为 OpenWorkBuddy、G 数字未复现）已按 2026-09-13 回填写入 §2.14；引用不得混用。
9. **一键重做的可用边界**：原始参数不落库（`redact_message_content` 只落摘要）⇒ **跨页 / 刷新后不可重建**（已定为产品口径，非缺陷）；「页面内持有原件」的前端判定与降级提示**已实现并组件级取证**（`unmet` + 无原件 ⇒ 降级提示；有原件 ⇒ 新幂等键重发），**真实运行数据下的端到端留 staging**。
10. **物理删除的引用图**：静态核对（[013](file:///d:/徐徐AI学习/公司工作台/migrations/013_run_records.sql#L1) / [023](file:///d:/徐徐AI学习/公司工作台/migrations/023_conversational_agent.sql#L30-L45) / [027](file:///d:/徐徐AI学习/公司工作台/migrations/027_dsh_tool_execution.sql#L107-L133) / [036](file:///d:/徐徐AI学习/公司工作台/migrations/036_conversation_stream.sql#L17-L55)）**已在真库跑通**（P2c-4：`tests/test_conversation_lifecycle_postgres.py` ⇒ 删除 → 各表计数 → 复删幂等 → 保留项仍在）；**「幂等行引用消息行」的复合外键正是「先删幂等行」的实测依据**。
11. **成员并发发言 / 并发执行**的资源画像未压测（P2c-6 开工前登记）。
12. **消息 `sender_id` 存量为 `NULL` 的展示回退**未实测（P2c-6）。

***

## 7. 实施顺序（评审通过后，**逐批独立验收**；每批先写失败测试）

| 批次        | 步骤                                                                                                                          | 前置       |
| --------- | --------------------------------------------------------------------------------------------------------------------------- | -------- |
| **P2c-1** | ① 侧栏重组 + 默认视图（含 `?view=home` 兼容）→ ② 对话页三区骨架（不接流，回归哨兵先绿）→ ③ 流读端（parser + hook）→ ④ 发送路由 + 流驱动刷新 → ⑤ 舞台（概览 / 时间线 / 工具流水）+ 内联审批卡 + 收尾检查（**已交付**，见 §0） | 无        |
| **P2c-2** | ① 契约修订条目（帧 payload 扩展 + Q9 边界 + resume 写帧 + **SSE 响应头 `X-Stream-Run-Id`**）写入 `api-contract.md` **先行** → ② 执行器输出有界读取 + 脱敏 + 落帧（真库用例先红）→ ③ resume 接帧 → ④ 前端终端面板与 diff 面板（帧驱动）+ 历史会话的概览/审批（用新响应头）    | P2c-1 验收 |
| **P2c-3** | ① `fs.*` 容器执行补完（先只读取证实现形态）→ ② 变更记录入帧 → ③ 产物登记表 + 端点 + 清理任务 → ④ 前端产物面板与 chip                                  | P2c-2 验收 |
| **P2c-4** | ① 迁移（`mode` 列 / 会话 `deleted_at` 软删列）→ ② 模式判定与合成（发起 + 推进）→ ③ 候选端点 + 选择器 UI → ④ 导出 / **物理删除**端点与 UI（引用图级联 + 审计 + 复删幂等）→ ⑤ 收尾检查接产物与模式 + **结构判定「达标 / 未达标」与一键重做** | P2c-3 验收 |
| **P2c-5** | ① PWA 对话面板 + 简化流 → ② 桌面端核对（流式读 / CSP）→ ③ 全量走查                                                             | P2c-4 验收 |
| **P2c-6** | ① 迁移（成员表 + 消息 `sender_id`）→ ② 成员端点与可见性判定（读路径统一「本人 ∪ 成员」）→ ③ 成员发言与发件人呈现（执行按本人身份）→ ④ 参与者列表 + 分享 UI → ⑤ 全量走查 | P2c-5 验收 |
| **收尾**    | `feature-inventory`（§2 P2c 行 / §3 六要素 / §5 欠账）+ `change-record` + 契约回改核对 + 一键全量 + CI 6/6 全绿 + §0 回归记录；**交用户确认后推送**                    | 全部批次     |