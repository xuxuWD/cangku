# P2a 段二（dsh 接入段）开工前置核查清单

> **性质**：**开工门禁**，不是建议清单。**全部条目必须有证据才能开工**；任一条未过，段二不得动第一行代码。
> **上位真源**：[立项文档](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §14.1 P2a-2 前置、§15 #9（🔴 风险最高决策）、§2.3（dsh 静态勘察）、§15 #11/#13；[段一规格](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-governance-closure-design.md) §8.5。
> **日期**：2026-09-12
> **状态**：**待逐条过闸**。段二自身**还没有规格**（§C1），因此本清单只解决「能不能开工」，不解决「怎么建」。

---

## 0. 已就绪（段一交付，段二直接接）

| 项 | 状态 | 段二要做的衔接 |
| --- | --- | --- |
| 执行授权位机制（`authorization.py` + 迁移 `026`） | ✅ 已交付 | **每次执行副作用工具前**调用 `ensure_execution_authorized`；这是段一登记的唯一缺口 |
| 风险刻度四档 + `needs_approval` 唯一判定入口 | ✅ 已交付 | 工具目录必须给每个工具定风险档，并让闸门消费它 |
| 前端常驻外壳 / `risk_threshold` 接入判定 | ✅ 已交付 | 无 |

---

## A. 决策答复（**2026-09-12 已答复**）

| # | 问题 | 答复 | 状态 |
| --- | --- | --- | --- |
| **A1** | **Q9：过程事件是否允许落文件内容原文？** | **不允许落原文**。分三层定：① **落库**只落摘要 + `args_digest` + `sha256` + 字节数，**永不落正文**；② **送模型**当轮上下文可有原文，但持久化只落摘要（「给模型看」与「存下来」是两件事）；③ **对象存储也不是无条件可落**——只有该文件本身属工作台受控对象存储范围、且租户隔离与权限受控时才落，否则连对象存储也不落（把不可信文件搬进可信边界＝放大风险） | **已定**（用户，2026-09-12） |
| **A2** | 隔离容器的部署形态 | **开发期**用本机 Docker（仅验证机制）；**生产必须与工作台分主机**（不同宿主、不同 Docker 网络/编排域）。**关键口径**：同机容器**不构成安全边界**，真正的边界是「**主机边界 + 最小挂载 + 无凭据**」三者叠加，容器只是其中一环（依据：dsh 自述未过安全审计、沙箱只约束写不约束读/网络/进程可见性）。两者之间只经**一个受控执行接口**通信，不共享文件系统与网络命名空间 | **口径已定**；**成本安排（多一台主机）待你落地时确认** |
| **A3** | 文件/命令工具的作用域 | 每次运行一个**专用空工作目录**映射到容器内固定路径（如 `/workspace`）；输入按需走**只读卷**且只挂白名单目录。**禁止映射**：仓库根、`$HOME`、`.env*`、`~/.ssh`、`~/.aws`、桌面、本项目根。容器内**不得写回宿主任何路径**；产物须**显式导出**并经内容安全检查才可进对象存储；**不挂 `docker.sock`**、不挂宿主设备节点；路径**虚拟化** + 输出**反向脱敏** | **已定**（用户，2026-09-12） |
| **A4** | 工具进程是否允许出网 | **不允许**：`--network none`，任务结束即销毁。出网同时是数据外泄、供应链下载执行（`curl | sh`）、内网探测三条通道；联网需求由**工作台侧的受控抓取/知识适配器**归口。工具确实需联网时**由工作台代理**，**凭据不进容器**；**模型调用由工作台侧发起**，容器不持有模型密钥 | **已定**（用户，2026-09-12） |
| **A5** | 危险命令黑名单口径 | **机制优先于列表**（列表永远不全）。三条机制（**不可被 `grant_all` 覆盖**）：① 黑名单**先于授权判定**执行，且执行前**二次校验参数**（防「批准 A 执行 B」）；② 命令**只允许结构化形式**（程序 + 参数数组），**禁止 shell 解释**（`sh -c`、`;`、`|`、`&&`、重定向、命令替换）；③ 参数中的路径必须落在 A3 允许目录内（**realpath 后**校验，防 `../` 与符号链接逃逸）。最小黑名单：删根、`mkfs*`、`dd of=/dev/*`、关机重启、递归改权限/属主、容器内装包、下载即执行、读凭据文件、扫描类、提权、逃逸类。**黑名单是第二道**，第一道是「工具白名单 + 结构化参数 + 路径约束」，不得把黑名单当唯一防线 | **机制已定**；**具体条目由我方起草 → 你确认后进段二规格** |

> 以上答复已落进 [段二专项规格](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-dsh-integration-design.md)。

---

## B. 技术前置（可自测，逐条给判据）

### B1 依赖版本必须钉死 —— ⚠️ 已查出真实隐患

- **实测事实**：探针目录 `d:\徐徐AI学习\_dsh-verify\` 里 `package.json` 写的是 `^0.1.5-rc.1`（**范围，不是精确版本**）。
- **实测事实（更严重）**：lockfile 里主包解析为 `@deepseek-ai/dsh@0.1.5-rc.1`，但**其余 245 个 `@deepseek-ai/*` 子包全部是 `0.1.5-rc.2`** —— **锁了主包并不等于锁住整套 harness**。
- **判据**：段二的依赖清单必须(a) 主包写**精确版本**；(b) 逐项核对 `@deepseek-ai/*` 是否存在跨版本混用，并在规格里**如实记录**混用事实与影响；(c) 升级只能是「一个升级单元」一次。

### B2 运行时版本必须钉死

- **实测事实**：`@deepseek-ai/dsh` 的 `package.json` **没有 `engines` 字段** → 上游对 Node 版本**没有任何承诺**；本机 Node 为 `v26.1.0`。
- **判据**：容器内固定 Node 版本并在规格中记录；不得依赖「本机能跑」。

### B3 四条契约的**运行时复验**（静态结论 → 运行期证据）

§2.3 的四条结论是**静态勘察**（未起服务、未接模型），§15 #5 明确要求运行期复验：

| 契约 | 静态结论 | 运行时复验要拿到什么 |
| --- | --- | --- |
| ① 外部审批回调 | ❌ 标准嵌入路径做不到 | 起 `dsh --profile sdk`，记录协议交互**原始报文**，确认无审批方法 |
| ② 会话级工具白名单 | ✅ `restrict({allow,deny})` | 实际限制生效的证据（越权工具被拒的原始报错） |
| ③ 租户 / trace 透传 | ❌ 无开放字段 | 确认透传必须由**我们自己**在适配器层完成 |
| ④ 沙箱 | ⚠️ `windows-acl: partial` | **🔴 新发现：这条只在 Windows 上看过**。段二跑在 **Linux 容器**里，**Linux 侧沙箱结论完全未勘察**，必须补 |

**判据**：每条给出可复现命令 + 原始输出，写进段二规格；**不得用「静态结论」代替运行时复验**。

### B4 隔离容器能力实测（本机环境已确认可用）

- **实测事实**：本机 Docker `OSType=linux`、Server `29.7.2`、cgroup v2、overlayfs → Linux 容器与 `--network none` / `--read-only` / `--cap-drop` 均适用。
- **判据**：逐条做**负向**验证（要求「应当失败」的必须真的失败）：
  - `--network none` 下解析/连通外网**失败**
  - `--read-only` 下写文件**失败**
  - `--cap-drop ALL` 后特权操作失败；进程**非 root**
  - `--pids-limit` / `--memory` 生效
  - **不挂** `docker.sock`、不挂宿主敏感目录
  - 容器内**看不到** Postgres / Redis / MinIO（网络与卷双向验）

### B5 工具风险分级必须能产出 `critical`

段一 §15 #13 已登记的硬约束：风险刻度扩到四档只是「有尺子」，**工具目录必须真的给工具定档**。
**判据**：段二的工具清单里每个工具都有风险档，且规格说明「什么动作算 `critical`」；若某档无工具，须写清兜底口径（不得留空档）。

### B6 授权位必须真的接进工具执行器

**判据**：工具执行前调用 `ensure_execution_authorized`；并有**反假测试**（去掉比对必须变红），与段一同口径。

### B7 `agent_key` 校验收紧（§15 #11 登记的 P2 收口项）

**判据**：`agent_key` 开始路由到真实执行前，必须校验其在本租户目录中**存在且启用**（复用 `ensure_agent_binding_available`），并保留「已停用员工的历史会话仍可读」。

### B8 模型出网与密钥边界

- **判据**：dsh **不得持有长寿命密钥**；模型调用若由工作台侧发起，凭据不进容器；若不得不进容器，必须用短期凭据并写清轮换与失效方式。

### B9 会话存储与格式迁移

- **实测事实**：`dsh-session-format-v0-to-v1 / v1-to-v2 / v2-to-v3` 三代迁移包**已存在** → 破坏性变更是**已发生的事实**（§2.3）。
- **判据**：定清「dsh 会话存在哪、由谁拥有、版本如何钉、升级时谁来做迁移」；并且**任何 dsh 类型都不得进入本项目领域模型**（§15 #1）。

### B10 可观测与审计

- **判据**：工具调用写 append-only 审计（谁批了哪个工具，明细走白名单，**不含自由文本**）；过程事件的落库口径与 A1 一致（不落原文）。

### B11 可回滚

- **判据**：段二必须能靠**配置**一键关回 `MockRuntime`，且关回后全量用例仍全绿（当前基线：后端 1417 / 管理台 147 / 伴侣端 37 / 桌面 19）。

### B12 成本熔断是否纳入段二

调研报告 §2.1 第 4 条建议吸收「单轮预算」维度。**判据**：明确「段二做 / 不做」，不做也要写进规格的「不做什么」。

### B13 许可证逐包核对

- **已核实**：`@deepseek-ai/dsh` 主包 **MIT**。
- **未核实**：其余 **245 个 `@deepseek-ai/*` 子包**的许可证（含 `cordis`、`cosmokit`、`schemastery` 等非 dsh 前缀包）。
- **判据**：逐包核对是否可商用 / 是否要求开源 / 是否需署名（宪法第九章）；**不整项目全升**，也不靠「主包 MIT」推断全树。

---

## C. 文档前置

| # | 事项 | 判据 |
| --- | --- | --- |
| **C1** | **段二规格（专项评审）** | 段二新增「工具执行链路 + 容器 + 危险命令」，属**地基级**改动，必须先有规格并通过评审（与段一同流程） |
| **C2** | `docs/api-contract.md` 新增工具/执行章节 | 契约先改文档再改代码 |
| **C3** | 「禁止事项」与验收标准写清（三类用例 + 反假测试 + 真实容器回归） | 否则无法验收 |

---

## D. 明确不做（防范围蔓延）

不做实时流与过程事件（**P2b**）、不做右侧舞台与侧栏重组（**P2c**）、不做记忆层（**P3**）、不做技能市场与 MCP 服务端（**P4**）、不做自我进化闭环（**P6**，且 §13 Q6 未答复前不具备开工条件）。

---

## E. 本清单自身尚未核实之项（如实登记）

1. **dsh 在 Linux 容器里的实际可运行性未测**：本机是 Windows，容器是 Linux；静态勘察的沙箱/审批结论**可能不适用**（见 B3 ④）。
2. **245 个子包许可证未核**（B13）。
3. **A5 的机制已定，具体黑名单条目尚未起草**（由我方起草 → 你确认后进段二规格）；**A2 的成本安排（多一台主机）待落地时确认**。
4. **Q7/Q8/Q10 与段二无关**（分别拦 P2b / P2b / P2c），本清单不涉及。
5. **本文件不构成任何「段二可开工」的结论**：§A 决策已答复，但 **§B 十三项未取证、§C 三项文档未完成之前，段二不得开工**。

---

## F. 取证结果（**2026-09-12 实测，本机**）

> 环境：Windows 宿主 + Docker `29.7.2`（`OSType=linux`、cgroup v2、overlayfs）；容器镜像 `node:22-slim` 与 `valkey/valkey:8-alpine`。**以下均为原始输出，不是推断。**

### F1 B1 版本钉死 —— ✅ 已取证（查出真实隐患）

| 项 | 实测 |
| --- | --- |
| 探针声明 | `"@deepseek-ai/dsh": "^0.1.5-rc.1"` → **是范围，不是精确版本** |
| 包数量 | `@deepseek-ai/*` 条目 **246 个** |
| 版本分布 | `0.1.5-rc.2` **230 个**；`0.1.5-rc.1` **1 个（主包）**；其余为 `node-addon-system*@0.1.2`（5 个）与 `cordis/cosmokit/schemastery` 等自有版本线 |
| 结论 | **主包 rc.1 / 子包 rc.2 → 锁主包 ≠ 锁整套 harness**（本清单 §B1 的怀疑被实测坐实） |

**落进段二的要求**：主包写**精确版本**；跨子包版本不一致要**如实记录**并评估；升级一次只动一个升级单元。

### F2 B2 运行时钉死 —— ✅ 部分取证

| 项 | 实测 |
| --- | --- |
| dsh 是否声明 `engines` | **未声明**（`package.json` 无该字段）→ 上游对 Node 版本零承诺 |
| 本机 Node | `v26.1.0` |
| **容器内 Node** | `node:22-slim` → **`v22.23.2`**（这是段二要钉住的运行时；须在规格中固定并记录） |

### F3 B3 四条契约运行期复验 —— ⏳ 部分取证（**本轮最重要的发现**）

**已取得**：

| 项 | 实测 |
| --- | --- |
| dsh 能否在目标 Linux 环境运行 | **能**：`node bin.js --help` → `exit=0`，输出 37 行；`--profile sdk --dump-default-config` → `exit=0`，352 行 |
| 安装规模 | 容器内 `npm install` → **added 522 packages in 2m**（Linux 侧 `@deepseek-ai` 目录 241 个，含嵌套） |
| `sdk` 剖面的**实际插件组成**（摘录） | `dsh-subprocess-local`、`dsh-sandbox-local`、`dsh-sandbox-policy`、`dsh-bash-sandbox`、`dsh-pwsh-sandbox`、**`dsh-user-approval`**、`dsh-permission-presets`、`dsh-tool-bash`、`dsh-tool-pwsh`、`dsh-tool-fs`、`dsh-tool-fs-search`、`dsh-web`、`dsh-web-search-deepseek`、`dsh-web-fetch-http`、`dsh-tools`、`dsh-fs-sandbox` |

**由此坐实的四件事（都直接改变段二设计；已按 `disabled` 逐条核对，不是凭 grep 列表推断）**：

1. **审批确实是「进程内插件」**：`dsh-user-approval` 挂在剖面里且**未禁用**，其 `policy` 是表达式 `(DSH_PERMISSION_MODE ?? 'workspace-write') === 'danger-full-access' ? 'never' : 'ask'` → 与 §2.3 契约①一致：**进程内可用、跨进程不可用**。**路线 A 的判断成立**。
2. 🔴 **`DSH_PERMISSION_MODE` 是整个剖面的总闸（比"预设存在"更精确）**：
   - `sandbox-policy.config.mode` = `process.env.DSH_PERMISSION_MODE ?? 'workspace-write'`（**默认 `workspace-write`**）
   - `sandbox-policy.config.workspaceRoot` = **`process.cwd()`**（沙箱根就是**当前工作目录**）
   - `permission-presets` 里定义了三个具名预设，其中 **`danger-full-access: {sandbox: danger-full-access, approval: never}`**
   - ⇒ **把该环境变量设成 `danger-full-access` 就等于同时关掉沙箱与审批**。段二必须**显式设为 `read-only`**（不能放任默认值），并在启动时断言；同时必须以**我们指定的工作目录**为 cwd，不得以 `/` 或宿主目录启动。
3. 🔴 **Linux 上默认启用 `tool-bash` + `bash-sandbox`**（配置里按平台禁用：`dsh-tool-bash` → `disabled: process.platform === 'win32'`；`dsh-tool-pwsh` → `disabled: process.platform !== 'win32'`）。
   ⇒ 段二在 **Linux 容器**里必须**显式禁用 `tool-bash`**（Windows 侧对应 `tool-pwsh`），否则绕过「结构化命令、禁止 shell 解释」的闸门。
4. 🔴 **联网工具默认启用**：`dsh-web`（`fetchProvider: http`）、`dsh-web-search-deepseek`（**读 `DEEPSEEK_API_KEY` 环境变量**）、`dsh-web-fetch-http`、`dsh-tool-web`（`fetch: true`）**均未禁用**
   ⇒ 与 **A4（不出网）** 直接冲突，**必须显式禁用**。**特别注意**：只要容器里存在 `DEEPSEEK_API_KEY`，它就能**自行联网搜索**——这既是「绕过工作台联网归口」，也是「密钥进容器」的实证风险。

**另外两项待复验（不写成结论）**：
- `dsh-subprocess-local` 未禁用 → 禁用 bash/pwsh 工具后，子进程能力是否仍可被其他插件触达，需评估。
- `approval.policy` 默认为 `ask`，而 SDK 协议**没有审批方法** → 运行期可能出现「工具调用等待一个不存在的审批通道」；**该行为必须用一次真实调用复验**（可能与 `dsh-sdk-jsonrpc-server` 的 dead capability 冲突）。

### F3.2 会话级运行期取证（**2026-09-12，无凭据干跑**）

> 方法：自写最小 stdio 客户端驱动 `dsh --profile sdk`，跑完一个完整 turn，**逐帧落盘**（27 帧）。
> 环境：`node:22-slim` 容器、`DSH_PERMISSION_MODE=read-only`、cwd=`/work/workspace`。因未提供模型凭据，**模型调用未成功**（`toolCalls=0`），但协议层与装配层证据已完整取得。

| # | 判据 | 实测结果 |
| --- | --- | --- |
| 1 | **契约① 运行期**：会话期间「服务端→客户端**请求**」数量 | **`serverToClientRequests = 0`**（含一次完整 turn）→ **运行期坐实：不存在任何反向请求，"审批回调"不可能** |
| 2 | **契约③ 运行期**：报文里是否存在租户/trace 字段 | 整段会话检索 `tenantId` / `tenant_id` / `traceId` / `trace_id` / `orgId` / `org_id` / `workspaceId` / `workspace_id` → **全部 absent**。比静态 grep 更强的证据：**透传必须由我们在适配器层做** |
| 3 | **配置解析运行期** | `permission/preset=read-only`、`sandbox/mode=read-only`、`approval/policy=ask` → 证明 **`DSH_PERMISSION_MODE` 确实是总闸**，且默认审批策略是 `ask` |
| 4 | **会话流程可用性** | 事件分布 `turn/start → step/start → assistant/attempt → step/end → turn/end`，最终回到 `idle`，`shutdown` 返回 `{}` → **协议可用、无凭据时不崩**（只是模型调用失败） |
| 6 | **模型错误回传通道（重要）** | 供应商错误经 `session.event` 回传：`assistant/attempt.stream[0].chunk.finish.reason = {kind:'error', failure:{message, code, status}}`，且 `turn/end.reason = {kind:'error', failure:{…}}`。实测样例：`code=AUTH`、`status=401`、`message="Authentication Fails, Your api key: ****1fa0 is invalid"`（**供应商已对密钥做掩码**）⇒ 段二可据此把错误映射为受控状态，并**只记 code/status、不记 message 原文** |
| 7 | **模型路由解析** | `request/context = {provider:'deepseek-official', model:'deepseek-flash', contextWindow:1000000, systemPromptUpdate:'in-history'}` → 剖面与模型路由确实按 `initialize.params` 解析 |
| 5 | **工具清单（契约② 的实际面）** | `sdk` 剖面默认暴露 **25 个工具**（见下） |

**实测的 25 个工具（带参数名）**：

```
bash(command, description, timeoutMs, workdir, run_in_background, sandbox_permissions, justification)
write(file_path, content, sandbox_permissions, justification)
edit(file_path, old_string, new_string, replace_all, sandbox_permissions, justification)
read / read_image / glob / grep
web_fetch / web_search
skill / subagent / subagent_fork / workflow / ralph
todo_write / exit_plan_mode / create_goal / get_goal / update_goal
job_list / job_output / job_kill / list_agents / send_message / interrupt_agent
```

🔴 **由此得出的新高危设计点（必须进段二规格）**：

- **`bash` / `write` / `edit` 三个工具都内建「沙箱升级通道」**：参数里带 `sandbox_permissions ∈ {workspace-write, danger-full-access}` + `justification`，描述明写「仅作为被沙箱拒绝后的一次性重试；需要说明理由并经**用户批准**」。
  实测计数：`danger-full-access` 出现 **3** 次、`sandbox_permissions` **8** 次、`justification` **7** 次。
  ⇒ **只设 `DSH_PERMISSION_MODE=read-only` 挡不住它**：模型可以发起升级请求。而**跨进程审批通道不存在**（判据 1），所以该请求要么被自动拒、要么挂住——**必须复验并显式阻断**。
- **联网工具默认在**（`web_fetch` / `web_search`）→ 与 A4 冲突，必须显式禁用。
- **`subagent` / `subagent_fork` / `workflow` / `ralph` 默认在** → 可自行派生更多 agent，**逃逸面与成本面都被放大**；必须显式禁用（我们的"数字员工"层级由控制平面决定，不由 dsh 自行派生）。
- **`skill` 默认在** → 与 §15 #3「技能生态是攻击面」叠加，必须显式禁用。

**仍未取到（需模型凭据）**：
- **升级通道的真实行为**：`approval/policy=ask` + 无审批通道时，`sandbox_permissions` 升级请求到底是**自动拒绝、挂住、还是被静默放行**——这是**最高优先级**的待验项。
- 真实模型驱动下的 `restrict` 拦截效果（契约②）。
- 沙箱在**实际读写动作**上的表现（Linux 侧结论）：读 `canary.txt`、写文件、执行 `id` 三件事的实际结果。
- 工具结果的回传形状（是否含宿主路径，用于评估"输出反向脱敏"的必要性）。

### F4 B4 隔离容器能力实测 —— ✅ 已取证（含一次探针设计错误的纠正）

| # | 检查 | 对照（默认） | 实验（加固） | 结论 |
| --- | --- | --- | --- | --- |
| 1 | 联网 | `NET_OK` | `--network none` → `NET_FAIL`（`bad address 'example.com'`） | ✅ 真断网 |
| 2 | 路由表 | — | `--network none` → **路由表为空**（连默认路由都没有） | ✅ 无法触达任何网络 |
| 3 | 触达宿主 | — | `http://host.docker.internal:8000` → `HOST_FAIL` | ✅ 连宿主也够不到 |
| 4 | 写根 | `WRITE_OK` | `--read-only` → `Read-only file system` / `WRITE_FAIL` | ✅ 真只读 |
| 5 | 临时可写 | — | `--read-only --tmpfs /tmp` → `TMP_OK` | ✅ 只读 + 受控可写并存 |
| 6 | 非 root | root（0） | `--user 65534:65534` → `uid=65534 gid=65534` | ✅ 可非 root 运行 |
| 7 | 能力集 | `CapEff: 00000000a80425fb` | `--cap-drop ALL` → `CapEff: 0000000000000000` | ✅ 能力全剥夺 |
| 8 | 特权操作 | `chown → CHOWN_OK` | `--cap-drop ALL` 且改到**不同** uid → `Operation not permitted` | ✅ 真的拦得住 |
| 9 | `pids` 限额 | — | `--pids-limit 20` → `pids.max=20` | ✅ 生效 |
| 10 | 内存限额 | — | `--memory 32m` → `memory.max=33554432` | ✅ 生效 |
| 11 | `docker.sock` | — | `SOCKET_ABSENT` | ✅ 未挂 |
| 12 | **组合剖面是否可用** | — | 全套加固参数下 `node --version` → **`v22.23.2`**；`pids.max=64`、`memory.max=268435456`、`docker.sock=ABSENT`、`/etc/hosts` 无宿主条目 | ✅ **加固后仍可用**（不是加固过度） |

> ⚠️ **一次探针设计错误的教训（已纠正）**：第 8 项最初写成 `chown 0:0`，结果**加固组也返回 `CHOWN_OK`**，一度像是「cap-drop 无效」。真实原因：文件本就属 `0:0`，Linux 对**无实际变更**的 chown 会短路权限检查。改成「改到不同 uid」后两组结果立刻分化。**结论：负向测试必须设计成「不带加固就一定成功」的对照，否则会得出反向结论。**

### F5 B13 许可证逐包核对 —— ✅ 已取证（查出非宽松许可证）

| 许可证 | 数量 |
| --- | --- |
| MIT | 459 |
| Apache-2.0 | 75 |
| BSD-3-Clause | 19 |
| **LGPL-3.0-or-later** | **10** |
| ISC | 10 |
| **Apache-2.0 AND LGPL-3.0-or-later** | **3** |
| **Apache-2.0 AND LGPL-3.0-or-later AND MIT** | **1** |
| BSD-2-Clause / 0BSD / Unlicense / Python-2.0 | 各 1–2 |
| **缺 `license` 字段** | **0** |

**非宽松许可证的具体包（逐个列出，共 14 个，全是 `sharp`）**：
`@img/sharp-libvips-{darwin-arm64, darwin-x64, linux-arm, linux-arm64, linux-ppc64, linux-riscv64, linux-s390x, linux-x64, linuxmusl-arm64, linuxmusl-x64}@1.3.3`（LGPL-3.0-or-later）、`@img/sharp-{wasm32, win32-arm64, win32-ia32, win32-x64}@0.35.4`（Apache-2.0 AND LGPL-3.0-or-later[ AND MIT]）。

**判断**：
- **无 GPL / AGPL 等强传染性许可证** → 不与 [D1](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) 冲突。
- **LGPL 全部来自 `sharp`（图像处理）**：**服务端自用（不分发）义务很轻**；但**一旦对外分发容器镜像或打进桌面产物，就触发 LGPL 义务**（需可重链接 + 声明 + 源码获取途径）。段二若把 sharp 打进交付镜像，必须产出 `THIRD-PARTY-NOTICES`。
- **顺带发现（供应链瘦身）**：默认安装把**10 个平台**的 libvips 二进制全装进来了（我们只需目标平台一个）→ 安装时应用 `--os`/`--cpu`/`--libc` 过滤或 `--omit=optional`，否则镜像体积与攻击面都被放大。

### F6 §B 剩余项的状态

| 项 | 状态 |
| --- | --- |
| B1 / B2（部分）/ B4 / B13 | ✅ **已取证** |
| B3 | ⏳ **部分**：环境可运行性与剖面组成已取证；三条契约的完整运行期复验**需模型凭据或自写 stdio 客户端** |
| B5–B12 | 属**段二实施期**的判据（不是开工前置取证），其中 B5/B6/B11 在段二-2/段二-3 落地时验证；B12 属决策项（规格 §7 X4） |
