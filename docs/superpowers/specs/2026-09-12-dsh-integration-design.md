# P2a 段二：dsh 接入段 设计

> **性质**：**阶段规格（唯一真源）**。本文定义「P2a 段二」做什么、怎么做、怎么验收。
> **上位真源**：[立项文档](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §4（D8/D20/D22/D23）、§14.1 P2a-2、§15 #1/#2/#9/#11；[段一规格](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-governance-closure-design.md)（已交付的授权位与四档风险刻度）。**功能清单 = [`docs/feature-inventory.md`](file:///d:/徐徐AI学习/公司工作台/docs/feature-inventory.md)**（宪法 2.1 真源三件套六要素；**2026-09-13 裁决 R8 新建**——**推翻** 2026-09-12「以立项 §14.1 充当、不另建文档」的裁决，原裁决自该决议起失效；对应 §8 U9 已闭环）。
> **开工门禁**：[dsh 接入前置核查清单](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-preflight-checklist.md)。**本规格通过评审 ≠ 可开工**；§B 中**除 B12（决策项，已闭环）外**的开工前置未取证前不得动代码。
> **日期**：2026-09-12
> **状态**：**已评审（附记录） · 2026-09-13**。演进：首轮评审「不予放行」→ 一轮修订 → 重审仍「不予放行」（B2/B4/B5「表面闭合」）→ 二轮修订 → **第三轮独立复核仍「不予放行」**（`027` 地基变更评审信息不足、正文残留旧口径，5 阻断 / 16 重要）→ 三轮修订 → **第四轮独立复核仍「不予放行」**（`§4.1` 本体存阻断级缺陷：DDL 语句顺序、漏并草稿 §2 的签名变更、枚举不一致、规范化自相矛盾、幂等表可插入性、`approval_id` 映射缺失，共 **8 阻断 / 9 重要**）→ 四轮修订 → **第五轮独立复核仍「不予放行」**（**§4.1 数据模型本体首次由未参与其撰写的视角独立确认**：`args_json` 参数落点缺失 / 幂等表缺结果码 / 规范化判据无编号 / 新增语义无 §5 用例 / 变更记录漏登新表 / 许可证据链 / 跨文档状态漂移 / 新增文档互斥 / 规约与契约行为冲突，共 **9 阻断 / 18 重要**）→ 五轮修订（J1 按**甲案**）→ **第六轮独立复核仍「不予放行」**（R6-1「从工作卷读」与 §3.3 生命周期矛盾且 `fs.write`/`fs.overwrite` 的 `content` 无事实源；R6-2 `control`/`body` 声明无落点；R6-3 ① 步结果码冲突 → **甲案本体不可实现**）→ **用户裁决 J7 = 丙案** + J8/J9 定死 → 六轮修订 → **第七轮「定点复核」：未通过（部分闭合）**——**R6-3 真闭合**；**R6-1 / R6-2 表面闭合**（`param_roles` 默认值 **fail-open**、加解密组件与密钥/清理周期**无配置落点**、加解密失败语义与密钥轮换未定、用例 32② **不可判定**），另 **8 处状态漂移** + 门禁 §C3「31 条」**事实错误** → **用户裁决 P1 / P3 / P11 + 其余 8 条 → 第七轮补丁已完成**（见 §9.6）。记录见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md)（§2–§6 首轮、§7 重审、§8 第三轮、§9 第四轮、§10 第五轮、§12 第六轮、§13 第七轮修订、§15 第七轮定点复核、§16 补丁留痕、§17 补丁确认、§19 再次补丁确认、**§21 最后一次补丁确认：R1/R2/R3 全部真闭合**）→ **本规格状态推进为「已评审（附记录）」**（2026-09-13）。
> ⚠️ **通过评审 ≠ 可开工**：**门禁 §B（除 B12 外）的开工前置未取证前，段二仍不得动第一行代码**；下一步是**段二-1**（运行时复验 + 容器能力取证，**只读勘察**）。
> **前置事实**：P1 已交付；段一已交付（后端 **1434**（2026-09-12 CI 实测）/ 管理台 147 / 伴侣端 37 / 桌面 19，CI 四个 job 全绿；后三项为文档原值，本次未复核）。

---

## 1. 范围

### 1.1 做什么

| # | 事项 | 一句话 |
| --- | --- | --- |
| A | **运行时复验** | 把 §2.3 的四条静态契约结论转成运行期证据（含**补 Linux 侧沙箱勘察**） |
| B | **隔离容器执行环境** | 按 A2/A3/A4 落地：分主机、**网络面 = 仅内网桥且仅网关可达（无外网出口，2026-09-13 裁决路径①）**、只读根、**容器内只放短期网关令牌（不放供应商密钥）**、工作目录卷 |
| C | **工具目录 + 九步闸门** | 结构化参数、风险定档（能产出 `critical`）、白名单双重强制、黑名单先于授权、授权位接入 |
| D | **dsh 适配器接入** | dsh 隔离在适配器之后；`restrict` 收窄工具面；会话归 dsh 所有 |
| E | **对话入口路由** | 现有非流式对话页可触发真实工具执行（**不引入流**，流属 P2b） |
| **F** | **模型网关（2026-09-13 新增 · 裁决路径①）** | **容器外**持有供应商密钥；容器内 `baseURL` 指向网关、`apiKeyEnv` 放**每 turn 新铸的短期令牌**；使「容器内不持供应商密钥」真正成立（依据：门禁 §F8.2/§F8.4） |

### 1.2 不做什么（明确排除）

1. **不做实时流与过程事件**（D15/D16 属 **P2b**）；本段只保证「执行完能查到」。
2. **不做右侧舞台、不做侧栏信息架构重组**（D14 属 **P2c**）。
3. **不做记忆层**（P3）、**不做技能市场与 MCP 服务端**（P4）、**不做自进化闭环**（P6）。
4. **不允许任何 dsh 类型进入本项目领域模型**（§15 #1）；dsh 只能出现在适配器内部。
5. **不新建「为 P2b 预留」的列或表**（段一已确立：不为假想需求预留）。**同理不为「将来可能有任务列表」预留 `origin` 之类字段**（见 §3.7）。
6. **不做单轮预算与成本熔断**（X4 **已定**，2026-09-12）：成本三级熔断的完整口径属 **P6**；本段不新增预算维度，也不引入新的成本计量。
7. **不做执行后台任务化**（P2 **已定**，2026-09-12）：保持**同步 + 单次执行硬上限**（§3.3），并发/排队属 P2b。
8. **不引入**调研报告 §3「明确不采纳清单」任何一条。

### 1.3 影响什么

| 层 | 影响 |
| --- | --- |
| 运行时 | 新增工具执行链路（本项目**自建**，不是 dsh 的审批链路）；dsh 仅作为「模型+循环」的宿主 |
| 容器 | 新增一个**与工作台分主机**的执行环境（A2）；新增镜像与运行时版本钉死要求 |
| 配置 | 新增容器/工作目录/超时/资源限额/总开关等配置项（外置，切环境不改代码） |
| 审计 | 新增工具执行的审计动作（append-only、明细走白名单、**不含自由文本**；`reason` 为受控枚举码） |
| 权限 | `agent_key` 开始路由到真实执行 → **必须收紧校验**（§15 #11 登记的 P2 收口项）；**收紧与真实执行同子段落地（段二-3）**，不得落后到段二-4（评审 G7） |
| 契约文档 | `docs/api-contract.md` 新增工具/执行章节 |

### 1.4 子段划分（**已定**：2026-09-12 用户确认采纳，见 §7 X1；D20 措辞已同步追加该决议）

段二体量与段一相当且风险更高，拆为可独立验收的四段：

| 子段 | 内容 | 独立验收判据 |
| --- | --- | --- |
| **段二-1** | 运行时复验 + 容器能力取证（只读勘察，**不写业务代码**） | 前置清单 §B1–B5 逐条有原始输出；**含 P1 待核实项（dsh 进程位置与模型凭据来源）的实测回填** |
| **段二-2** | 工具目录 + 九步闸门（**离线可验收**，用假执行器） | 闸门用例全绿 + 反假测试全红过 |
| **段二-3** | 容器执行器 + dsh 适配器接入 + **`agent_key` 校验收紧** | 端到端：一次真实工具执行 + 一次被拦 + 审计可查；**且「真实执行已存在」与「路由校验未收紧」不得跨子段并存**（评审 G7）。若段二-3 不接任何用户入口（仅内部离线触发），该项可后移，但必须在子段说明中写明 |
| **段二-4** | 对话入口路由 | 从对话页走通主流程，且关回 mock 后全量全绿 |

---

## 2. 立在什么事实之上（先纠正一处原始计划的前提错误）

### 2.1 🔴 D20 原文写「回调审批」，但该契约实测**不可用**

§2.3 契约①的静态结论：`dsh-sdk-protocol` 只有 `initialize` / `session.prompt` / `shutdown` 三个请求 + 4 个通知，**没有任何审批方法**；服务端**从不发反向请求**（README 自述 "Server→client requests are a dead capability"）。

> 该枚举来自静态勘察，**仓库内无 dsh 源码/协议文件可核对**，运行期实测只取到 `serverToClientRequests = 0`；若要把它作为设计前提，须在前置清单补附**原始协议报文**，否则按「待核实」处理（评审附录 B#15）。

**推论（必须写进规格，否则会按错误前提设计）**：段二的审批**不可能**由 dsh 承担，**只能**由 **D8 路线 A**——文件与命令由**我们自己实现成受控工具**，审批挂**我们自己的闸门**。因此本规格的 §3.2 九步闸门**就是**原来的「回调审批」位置。

> 本条同时是 §15 #9 硬门禁的落地：**路线 A 未实现之前，文件与命令能力不得开启**。

### 2.2 其余三条契约对设计的影响

| 契约 | 结论 | 对设计的影响 |
| --- | --- | --- |
| ② 工具白名单 | ✅ `restrict({allow, deny})` 可用 | 作为**第二道**强制（第一道是我们自己的白名单校验）；不依赖它作为唯一防线 |
| ③ 租户 / trace 透传 | ❌ 无任何开放字段 | 租户与 trace **由我们在适配器层注入与回收**；不得指望 dsh 透传 |
| ④ 沙箱 | ⚠️ 仅勘察过 **Windows**（`windows-acl: partial`） | **Linux 侧未勘察**（段二跑 Linux 容器）→ 复验必做；且无论结论如何，**沙箱都不是安全边界**（§15 #2） |

### 2.3 版本现实（已实测）

- 主包 `@deepseek-ai/dsh@0.1.5-rc.1`，**MIT**；**无 `engines` 字段**（上游对 Node 版本零承诺）。
- **lockfile 实测（前置清单 §F1）**：`@deepseek-ai/*` 条目共 **246 条**，其中 **rc.2 为 230 条**、主包 1 条（rc.1）、另有 5 条 `node-addon-system*@0.1.2` 等自有版本线 → **锁主包 ≠ 锁整套 harness**。
  > 原稿「其余 245 个子包为 rc.2」为笔误，已按清单实测口径更正（评审 M4/M9）。**lockfile 不在本仓库内**，精确计数属**待核实**，以清单实测原始输出为准。
- 三代会话格式迁移包已存在 → 破坏性变更是**已发生的事实**。

**因此**：依赖写**精确版本**；容器内运行时版本钉死并记录；解析结果里的版本混用要**如实写进规格**而不是假装没有。

---

## 3. 设计

### 3.1 工具规格目录（`ToolSpecCatalog`）

> **命名与落点（**第七轮 P11 定死，2026-09-13**）**：本节的目录类命名为 **`ToolSpecCatalog`**，**新建独立模块**。
> ⚠️ **与既有同名类的关系**：仓库内**已存在** `app/planner/models.py` 的 `class ToolCatalog`——那是**规划器白名单**（`Tool` 仅 `name`/`kind`/`description`，由 `from_config(settings.planner_tools)` 构造，用途是"生成器只能从白名单选工具"）。两者**同名不同构、不同用途**（第七轮复核指出该同名冲突会让实现者无从判断）。→ **定死**：**不得复用该名、不得扩该既有类**；本节的 `ToolSpecCatalog` 与它**互不影响**（前者管"工具怎么执行"，后者管"计划器可选哪些工具"；若将来要统一，须另立专项评审）。

每个工具一条声明，缺一不可：

| 字段 | 说明 |
| --- | --- |
| `key` | 工具标识（小写、稳定、不可改） |
| `params_schema` | **结构化参数 schema**；**未知字段一律拒绝**（白名单） |
| `param_roles` | **参数角色声明**（**J8 定死、P1 修订为 fail-closed，2026-09-13**）：`{参数名: "control" \| "body"}`。⚠️ **无默认值**——**必须为 `params_schema` 的每一个参数显式声明角色**；**任一参数未声明即视为配置错误 → 拒绝装配**（启动期断言 + 测试守护，见 §4.1.6-3 与 §5 用例 34）。**用途**：决定 ⑥ 落库时哪些参数进 `args_json`（`control`）、哪些进**受控正文密文列**（`body`）——见 §3.4 唯一受控例外与 §4.1.1 边界。**逐工具标注见 §3.1.1**。<br>**P1 说明**：原口径为"**默认 `control`**，漏声明属实现缺陷（仅口头兜底）"——因漏声明会使**正文以明文进 `args_json`**（与 §3.4 红线方向相反），且**无任何可检出手段**，第七轮复核判为 **fail-open**，故改为**必须显式声明 + 未声明即拒绝装配** |
| `risk_level` | 风险档（`low`/`medium`/`high`/`critical`）——**必须能产出 `critical`**，否则段一的兜底仍是空转 |
| `has_side_effect` | 是否产生副作用；**有副作用必须 `requires_approval`**（与段一授权位闸门的前提一致） |
| `requires_approval` | 是否需审批（由风险档与副作用派生；**重审补入字段表**——原表称"缺一不可"却漏列此字段） |
| `reversible` | 是否可逆（不可逆档位不得低于 `high`） |

**风险定档规则（已定，2026-09-12 随本轮修订定稿）**：

| 档 | 判据 |
| --- | --- |
| `low` | 只读、无副作用、可逆 |
| `medium` | 只写**专用工作卷**、可逆、不触达外部系统 |
| `high` | 删除 / 覆盖 / 改权限等**不可逆**操作（不可逆 ⇒ **不得低于 `high`**） |
| `critical` | **触达外部系统、公开发布、权限变更、涉资金、跨租户**，以及**任何离开执行域的导出** |

定档规则**不允许在实现时逐工具即兴定档**；新增工具必须按本规则定档并**同步写入 §3.1.1 附录**。

#### 3.1.1 工具清单与定档（附录，随本规格评审确认）

> 起草说明：原稿只有字段定义、**没有具体工具与定档**，导致清单 B5「每个工具都有风险档、并说明什么动作算 `critical`」无法验收、§5 用例 5 无所指（评审 G3）。本节补齐。**本表是新增内容，请评审一并确认。**

| 工具 `key` | 用途 | `params_schema` 要点 | `risk_level` | `has_side_effect` | `reversible` | `requires_approval` |
| --- | --- | --- | --- | --- | --- | --- |
| `fs.list` | 列工作卷目录 | `{path}`（**虚拟化路径**，默认 `/workspace`） | `low` | 否 | 是 | 否 |
| `fs.read` | 读工作卷文件（受 §3.2.1 C 类路径约束） | `{path, max_bytes}` | `low` | 否 | 是 | 否 |
| `fs.stat` | 文件元信息（大小/时间/类型） | `{path}` | `low` | 否 | 是 | 否 |
| `cmd.run` | 运行**白名单内单条只读命令**（§3.2.1 Q2 集；**禁管道**） | `{executable, args[]}`（**结构化数组，非字符串**） | `medium` | 否 | 是 | 否 |
| `fs.write` | 在工作卷**新建**文件（**目标已存在则拒绝，不覆盖**） | `{path, content（**body**）}` | `medium` | 是 | 是 | 是 |
| `fs.overwrite` | **覆盖**工作卷已有文件 | `{path, content（**body**）}` | `high` | 是 | **否** | 是 |
| `fs.delete` | 删除工作卷文件 | `{path}` | `high` | 是 | **否** | 是 |
| `artifact.export` | 把工作卷产物**导出到工作台**（对象存储），并过内容安全检查 | `{path, target}` | **`critical`** | 是 | **否** | 是 |

**`critical` 的承担工具 = `artifact.export`**（触达外部系统 + 不可逆 + 离开执行域）。§5 用例 5 与用例 19 以它作样本；**不得**为了凑出 `critical` 而虚设工具。

**`param_roles` 逐工具标注（J8 定死；P1 修订为 fail-closed）**：**本规格内仅 `fs.write` 与 `fs.overwrite` 含 `body` 类参数**——`{path: "control", content: "body"}`；**其余工具全部为 `control`**（`fs.list`/`fs.read`/`fs.stat`/`fs.delete` 的 `path`、`cmd.run` 的 `executable`/`args[]`、`artifact.export` 的 `path`/`target` 均属控制参数）。**每个参数都必须显式列出**（上列即完整标注）；**新增工具必须同步本标注**；**任一参数漏声明 → 拒绝装配**（不是"默认按控制参数入库"——该 fail-open 口径已作废，P1 / §3.1 `param_roles` / §4.1.1 边界第 1 条三处一致；判据见 §5 用例 34）。

**重审更正（2026-09-12 第二轮）**：

1. **原 `fs.write` 的"同工具双档"已拆分**：`ToolSpecCatalog` 字段只有单一 `risk_level`，无法表达"新建 medium / 覆盖 high"；若靠运行时按目标是否存在提档，等于把定档塞进实现（违反 §3.1「不允许实现时即兴定档」）。故**拆为 `fs.write`（新建，拒绝覆盖）与 `fs.overwrite`（覆盖，`high` + 需审批）**，定档在目录里静态可查。
2. **`artifact.export` 的闸门落点（重审补）**：它是**我方自建工具、不经容器执行**（⑧ 只覆盖容器内执行），因此必须明确：**③ 路径校验适用**（`path` 必须 realpath 在工作卷内）；**④ 不适用**（无结构化命令）；**⑤/⑦ 适用**（`critical` ⇒ `requires_approval`，逐项授权）；**⑨ 适用**（结果落摘要 + 审计）。**`restrict` 只作用于 dsh 工具面，不覆盖自建工具**——自建工具的准入由 ① 我们自己的白名单负责。
3. **导出侧的校验口径（重审补，宪法 4.7）**：`artifact.export` 须对导出内容做**类型白名单 + 大小上限 + 数量上限 + 内容嗅探（防可执行/脚本伪装）+ 目标命名净化**，并记录审计；不得只写"过内容安全检查"。

### 3.2 执行流水线：**九步闸门**（唯一执行入口）

```
① 白名单（组装工具面时过滤一次 + 执行入口再校验一次）
② 参数结构化校验（schema，未知字段拒绝）
③ 路径校验（realpath 后必须落在允许目录内，防 ../ 与符号链接逃逸）
④ 危险命令闸门（三个子判定，顺序固定，任一命中即拒）
   ④-0 可执行文件来源：必须解析自「受信任且不可写」的固定根（配置项 WORKBENCH_EXEC_TRUSTED_ROOTS，
        默认如 /usr/bin；**不使用 PATH 解析**）；realpath 落在该根内、属主 root、非 group/world-writable；
        拒绝 shebang 脚本与非 ELF；工作卷不得出现在该根内
   ④-1 可执行名白名单（§3.2.1 Q2 最小只读集，**fail-closed**：不在集合内即拒，无失败语义豁免）
   ④-2 危险命令黑名单（§3.2.1 的 A / B / C 三层）
⑤ 风险定档 → **`spec.requires_approval` OR `needs_approval(自治等级, 风险档, 阈值)`**   ← 段一的唯一判定入口
   〔2026-09-13 用户裁决：采**更严的复合口径**。理由：`requires_approval` 是工具**静态声明**的副作用标志（§3.1.1 定档表中 4 个有副作用工具全为「是」），若只信 `needs_approval`，则「**有副作用但风险档未达阈值**」的调用会**绕过审批**。本行原只写 `needs_approval`，与 §3.1.1 及契约闸门表 ⑤ 行冲突，现更正为复合判定。〕
⑥ 需要审批：**先落库、再阻塞**（**待批动作**落进迁移 `027` 的授权项表；未落库不得进入等待，否则 UI 变 orphan）
⑦ 授权位校验：ensure_execution_authorized（计划摘要 **+ 参数摘要** 比对）+ **逐项校验**：本批待批动作
   是否都有对应授权项 ← 段一已交付、本段接上；授权项由迁移 `027` 承载
   **〔2026-09-13 用户裁决（U19·方案 b）〕审批后「重跑路径」的运行级比对已豁免**（只做逐行 027 校验）——理由与边界见 §4.1.6-4 调用链注；**首次执行路径不变**。
⑧ 容器内执行（§3.3 的约束）；**非容器工具（`artifact.export`）按 §3.1.1 第 2 条落点处理**
⑨ 结果只落**摘要**（A1）+ 审计（append-only，明细走白名单）
```

> **④-0 为什么必须存在**（评审 B3）：原稿只按 `basename` 判定且不限制可执行文件来源 → 工具调用 `executable=/workspace/ls`（真实内容是带 shebang 的脚本，basename 命中 Q2 白名单）即可拉起 `sh` 执行任意命令，**A7/A8/Q1/Q3 同时失效**，而 ③ 路径校验还会放行该路径。

**四条不可协商的口径**：

- **②③④ 先于 ⑤⑦**：先做「能不能执行」，再做「该不该执行」。若顺序颠倒，被批准的动作仍可能带上 `../` 或黑名单命令。
- **审批通过后必须重跑全套闸门**（评审 B4）：审批通过后，由**审批决议端点在同一请求内**从迁移 `027` 的**待批动作**取回**冻结的动作与参数**，并**从 ① 重跑**（含 ②③④）再进入 ⑧。**禁止**任何「已校验」缓存或跳过 ②③④ 的续跑；**禁止**以「重新发消息」作为推进方式——那会产生新 run 与新授权位，⑦ 将永不可达。⑤/⑥ **不得**直接接 ⑧。
- **不依赖 dsh 任何审批能力**（§2.1）：dsh 只是执行宿主，闸门全在**我们这一侧**。
- **执行幂等**（评审 B5，第二轮按实测更正）：**以请求头 `Idempotency-Key` 为执行幂等键**——同一 `Idempotency-Key` 重放**必须返回既有结果**（不新增消息、不新增承载任务、不新增运行、不二次执行）。**原稿用 `message_id` 不可行**：该值由服务端在 `append_message` 内每次 `uuid4` 新建（`app/conversation/store.py:135`、`:333`），重放会得到新值，幂等永不命中；且请求体 `extra=forbid`，客户端无法提供。**作用域**：`Idempotency-Key` 按 `(tenant_id, 操作者, 会话, 键值)` 唯一，冲突一律返回首次结果并记审计。**必填性与缺省语义（2026-09-13 用户裁决 R6，定死）**：请求头**可选**；**带键** ⇒ 真实执行且幂等；**不带键** ⇒ **不触发真实执行**，沿用既有 `stub=true` 语义（不创建承载任务、不创建运行、不产生任何真实副作用）。**缺键必须 `stub=true`**——实现**不得**把「无键」理解为「幂等关闭后照常真实执行」（该口径与宪法 4.2 相悖，评审 R3-4 已否）。

**两条必须收窄的既有实现**（评审指出，规格不得沿用其 fail-open 行为）：

- **启动期断言（fail-closed）**：真实执行器装配时必须**断言 `run_records` 已装配**。现有 `ensure_execution_authorized` 在 `run_records is None` 时直接 `return`（闸门整体不生效），段二**不得**沿用该行为（**2026-09-13 已落实现：改为 `raise ExecutionNotAuthorized`**）。⑦ 的**授权位比对**仅适用于「⑤ 判定需审批」的路径，其调用前提是「⑤ 判定需审批且 ⑥ 已落库」；`authorization is None` **只允许**出现在「⑤ 判定**无需审批**」分支。**〔2026-09-13 用户裁决〕该分支完成 ②③④ 后直接进入 ⑧**（依契约闸门表「九步闸门 → HTTP 语义」）；本行原写「该分支**不得触达 ⑧**」，与契约闸门表冲突，**该表述作废**——否则「无需审批」的工具将永远无法执行。
- **逐项授权（第二轮改为可实现口径）**：授权位必须与**被批准的审批项及其对应步骤子集**绑定。原稿把"逐项授权"与"单一 `authorized_plan_digest` 列"并列，**自相矛盾**（单一三元组无法表达逐项）——故本轮改为：**新增迁移 `027`**，以**授权项**为单位持久化（每条含：待批动作、规范化参数摘要、批准人、批准时间、计划摘要），⑦ 在执行前**逐项校验**；未批准的步骤不得执行。**迁移 `027` 同时承载 ⑥ 的待批动作**，这是 B2/B4 的共同落点（2026-09-12 用户裁决）。
- **授权权威与事务边界（2026-09-13 用户裁决 R7，定死）**：**`027` 是工具执行的唯一授权权威**——执行放行判定**只读 `027` 的逐项行**；`026` 三列**保留、不删、不回填**，语义**降级为「运行级授权快照」**（仅服务段一既有读路径与「该运行是否曾被授权过」的粗判，**不得单独作为工具执行放行依据**）。`decide_approval` 的「写 `027` 决议状态 + 写 `026` 快照 + 适配器决议」**必须在同一事务内**，任一失败全部回滚。⑦ 的 `authorization is None` 分支**只允许**出现在「⑤ 判定无需审批」路径；**〔2026-09-13 用户裁决〕该路径完成 ②③④ 后直接进入 ⑧**（依契约闸门表）——原「该路径**不得触达 ⑧**」表述**已作废**。

### 3.2.1 危险命令黑名单（**已定**，2026-09-12；口径经用户确认，本轮按评审补强）

**判定口径（四条，缺一即可绕过）**

| # | 规则 |
| --- | --- |
| R1 | 判定对象是**结构化命令**（`executable` 的 basename + 规范化后的参数序列），**不是 shell 原始字符串**。参数规范化至少覆盖：去引号；**短选项粘连**（`-rf` → `-r -f`）；**长选项 `=` 形态**（`--in-place=.bak` → 选项 `--in-place` + 值 `.bak`）；解析 `--` 终止符（其后为纯操作数）；**大小写归一** |
| R2 | basename 先做 **realpath 解析**（防 `/usr/bin/rm`、符号链接改名 `myrm`），再**剥离可执行扩展名**（`.exe`/`.cmd`/`.bat`/`.ps1`），最后**大小写不敏感**比较 |
| R3 | **命中即拒，先于风险定档与授权位**（④ 先于 ⑤⑦）；**不提供「审批后放行」豁免**——用例 4 就是这个不变式 |
| R4 | **本段的执行环境限定为 Linux 容器**：Windows 侧可执行名（`pwsh`/`powershell`/`cmd`/`wsl`）仍列入 A7 作纵深防御，但**不得**以「已兼容 Windows」作为已堵住的理由（评审附录 A#16） |

**A. 可执行名黑名单（命中即拒）**

| 类 | 条目 | 理由 |
| --- | --- | --- |
| A1 文件系统破坏 | `rm` `rmdir` `shred` `dd` `truncate` `mkfs*` `mke2fs` `wipefs` `fdisk` `parted` `sgdisk` `mkswap` `swapon` `swapoff` `chattr` `setfattr` | 不可逆破坏；工作卷内容属交付物 |
| A2 提权与身份 | `sudo` `su` `doas` `pkexec` `runuser` `setcap` `usermod` `useradd` `groupadd` `passwd` `chsh` `visudo` `newgrp` `chown` `chgrp` | 越权与身份语义变更；容器内本就非 root |
| A3 进程/服务控制 | `kill` `killall` `pkill` `systemctl` `service` `crontab` `at` `batch` `nohup` `screen` `tmux` `shutdown` `reboot` `halt` `poweroff` `init` `telinit` | 生命周期只能由容器层控制（§3.3：超时=拒绝并终止容器） |
| A4 网络与外联 | `curl` `wget` `nc` `ncat` `netcat` `socat` `telnet` `ssh` `scp` `sftp` `ftp` `tftp` `ping` `traceroute` `dig` `nslookup` `host` `ntpdate` `iptables` `nft` `ip` `ifconfig` `route` `tcpdump` | 与 `--network none` 冲突；联网只能由工作台侧发起，任何外联即绕过归口 |
| A5 逃逸原语 | `docker` `podman` `nerdctl` `ctr` `crictl` `kubectl` `nsenter` `unshare` `chroot` `mount` `umount` `losetup` `pivot_root` `modprobe` `insmod` `rmmod` `sysctl` `systemd-nspawn` `machinectl` | 禁挂 `docker.sock` / 禁 `--privileged` 的兜底 |
| A6 包管理 | `apt` `apt-get` `dpkg` `yum` `dnf` `rpm` `apk` `pacman` `zypper` `pip` `pip3` `npm` `yarn` `pnpm` `cargo` `gem` `composer` `conda` `brew` | 安装即引入不可控供应链；依赖由镜像构建期钉死（§4 精确版本） |
| A7 shell 解释 | `sh` `bash` `zsh` `dash` `ksh` `pwsh` `powershell` `cmd` `wsl` | 直接违反「禁止 shell 解释」，并堵住 `bash -c "任意"` |
| A8 解释器内联代码 | `python -c` `node -e` / `-p` `perl -e` `ruby -e` `php -r` `lua -e`；`awk` 在可写文件时 | 等于把结构化闸门降级为字符串执行 |
| A9 调试与注入 | `gdb` `lldb` `dlv` `strace` `ltrace` `ptrace` `valgrind` | 可读写其它进程内存；调试能力应与执行环境分离 |
| A10 资源耗尽 | `yes`、fork bomb（`:(){...}`）、`while true` 无限输出 | 容器有 pids/内存限额，仍需拒明显耗尽模式以保可观测 |
| **A11 包装器**（本轮新增） | `env` `busybox` `toybox` `timeout` `setsid` `nice` `ionice` `stdbuf` `xargs` `find`（作执行器时） | **R1 只看顶层可执行名**，包装器会把真实命令藏在参数里：`env rm -rf /workspace/x`、`busybox rm -rf /` 可间接触发任意命令（评审 G1） |
| **A12 裸解释器**（本轮新增） | `python` `python3` `node` `perl` `ruby` `php` `lua` `tclsh` `Rscript` | 落实 Q1「本段整体禁止脚本执行」；原稿 A/B/C 三层**没有**裸解释器条目，导致 Q1 锁定值与 §5 用例 12 的 `python app.py` **无落实点**（评审附录 B#7） |

**B. 参数级黑名单（可执行名合法，参数命中即拒）**

| 规则 | 理由 |
| --- | --- |
| `find` + `-delete` / `-exec` / `-execdir` | 绕过 A1 与任意命令执行 |
| `sed` + `-i` / `--in-place`（含 `=` 形态） | 原地改写文件 |
| `tar` / `unzip` / `7z` / `cpio` / `bsdtar` + `-P` / `--absolute-names` / `-C /` / 含 `..` 的路径 | 解包逃出工作卷；**解包默认不得跟随符号链接**（防「先释放符号链接、再经该链接写出」） |
| `git` + `config --global` / 写 `remote` / `alias` 以 `!` 开头 | 持久化配置注入与命令执行 |
| 任意命令 + 重定向 / `tee` 写入允许目录之外 | 与 ③ 同源，④ 再兜一次 |
| 任意参数 realpath 后落在允许目录外 | 同上 |
| `chmod` + `777` / `0777` / `666` / `a+rwx` / `+s` / `--reference=` | 权限放宽与 setuid；**数值与等价形态须一并覆盖**（评审 G2） |

**C. 路径黑名单（读或写均拒）**

**匹配算法（本轮补齐，评审附录 A#15）**：对 ③ 得到的 **realpath 绝对路径**做「前缀匹配」，同时对**基名**做 glob 匹配（两者**任一命中即拒**）；按平台做**大小写归一**；`~` 必须先展开为绝对路径再判定。

| 条目 | 理由 |
| --- | --- |
| `/etc/shadow` `/etc/sudoers` `/root/**` `/proc/*/environ` | 凭据与提权配置 |
| `~/.ssh/**` `~/.aws/**` `~/.config/gcloud/**` `/var/run/secrets/**` | 凭据目录（§3.3：容器内不得持有任何长寿命密钥） |
| `/proc/self/maps` `/proc/self/mem` `/proc/sys/**` `/sys/**` `/dev/**` | 随本轮补齐：进程内存窥探、内核参数写入、设备节点（评审附录 A#15） |
| `.env` `.npmrc` `.pypirc` `.docker/config.json` `*.pem` `*.key` `id_rsa*` | 密钥文件（基名 glob） |

**四个口径开口的锁定值（保守分支，2026-09-12 用户确认）**

| # | 开口 | 锁定 |
| --- | --- | --- |
| Q1 | 是否允许脚本执行（`python app.py`、`node script.js`） | **本段整体禁止**。否则黑名单看不到脚本内部，A/B/C 三层形同虚设。**落实点 = A12（裸解释器）** |
| Q2 | 只读工具是否保留 | **只保留白名单最小只读集**（`ls` `cat` `head` `tail` `wc` `stat` `file`），且受 C 类路径约束；`grep` / `rg` / `find` 本段不开放。**该集合必须写进 ④-1 并 fail-closed**（原稿只写在 Q2 里、未进闸门也无失败语义，评审 G1） |
| Q3 | 管道 / `xargs` | **整体禁止**：一次工具调用只接受**一条**结构化命令，不支持管道组合 |
| Q4 | 黑名单维护形态 | **代码常量 + 启动期断言**（与 §3.5 剖面口径一致）；不作外置热改配置 |

**如实登记的局限（不得据此放宽其它防线）**

1. 黑名单**看不到脚本内部**：一旦允许执行脚本，参数级判定即失效——这是 Q1 锁为「禁止」的原因。
2. 语言运行时自带文件与网络能力（python / node 标准库）→ 允许运行脚本等于放弃 A/B/C 三层。
3. 别名与符号链接须经 R2 的 realpath 归一，否则改名即绕过。
4. 黑名单是**兜底**，主防线仍是白名单 + 容器边界；**安全性不得寄托在它上面**。
5. **同名替换**（本轮登记）：`basename` 白名单挡不住「工作卷内放一个与白名单同名的脚本/ELF」。**由 ④-0 堵住**，并以工作卷 `noexec` 作为第二道（§3.3）。
6. **TOCTOU 与硬链接**（本轮登记）：③ 的校验与 ⑧ 的打开之间存在时间窗；**硬链接不改变 realpath**，若敏感文件与工作卷同设备即可绕过 ③ 与 C 类。对策 = 校验→打开**原子化**（fd 传递 / `openat2 RESOLVE_BENEATH`）+ 工作卷与容器根**不同设备**（§3.3）。**该对策当前未做实验验证 → 待核实**（评审附录 A#17）。

### 3.3 容器执行环境（照 A2/A3/A4 落地）

| 项 | 要求 |
| --- | --- |
| 位置 | **生产：与工作台分主机**（不同宿主、不同 Docker 网络/编排域）；两者之间只经一个受控执行接口。**开发期允许本机 Docker，但仅用于机制验证，不得据此声称隔离达成**（评测附录 B#14，与清单 A2 对齐） |
| 网络 | **仅内网桥（`--internal`，无外网出口）+ 仅模型网关可达**（2026-09-13 裁决路径①；**原 `--network none` 口径与 dsh 架构不相容**，见门禁 §F8.2）；模型调用**经工作台侧模型网关**发起（**真实供应商密钥只在网关**，容器内仅短命令牌——见 §3.5） |
| 文件系统 | 根**只读**；只挂一个**专用空工作目录**到 `/workspace`，挂载选项 **`nosuid,nodev,noexec`**；**工作卷与容器根不同设备**；**不挂 `docker.sock`**、不挂宿主设备节点。**〔2026-09-13 用户裁决·实现口径〕落点 = 容器内 `tmpfs`**（`rw,noexec,nosuid,nodev`）。**理由**：Docker **不支持**在 bind / volume 上设置 `nosuid,nodev,noexec`（实测 `-v vol:/w:noexec,nosuid,nodev` → `invalid mode`），而 **tmpfs 是同时满足**「三项挂载选项 + 与容器根不同设备 + 生成即空 + 随容器销毁」的**唯一原生手段**。**影响**：工作卷**不再落在宿主目录**（产物导出仍走 `artifact.export`）；宿主侧 `WORKBENCH_EXEC_WORKSPACE_ROOT` 保留，语义收窄为「③ 路径闸门的宿主锚点」。**登记**：变更记录「执行工作卷落点」条 |
| 路径原子性 | ③ 的校验与 ⑧ 的打开必须**原子化**（fd 传递 / `openat2 RESOLVE_BENEATH`），消除 TOCTOU 与硬链接绕过 |
| 权限 | **非 root**；`--cap-drop ALL`；禁止 `--privileged`；**`--security-opt no-new-privileges`** |
| 资源 | `--pids-limit` / `--memory` / **`--cpus`（重审补，宪法部署检查要求 CPU 上限）** / **单次执行硬上限（超时，默认值见 §4）**；**超时语义 = 拒绝并终止容器**（fail-closed）；`/tmp` 与 `/dev/shm` 须限额并置 `noexec`（若实测某工具必需例外，须在本规格登记理由） |
| 镜像 | **按 digest 钉死**，不使用浮动 tag |
| 工作目录 | **per-run 唯一**、生成即空；运行结束销毁；**销毁失败必须告警并登记**（残留清理） |
| 生命周期 | 每次运行一个容器，正常路径**任务结束即销毁**；**超时/崩溃路径必须有孤儿容器回收**（按 run 标签清扫：启动时 + 周期） |
| 同步语义 | 执行在请求链路内**同步**完成（P2 **已定**），因此**必须有单次执行硬上限**；并发与排队不在本段 |
| 输出 | 路径**虚拟化** + **反向脱敏**（不暴露宿主路径）；产物须**显式导出**（= `artifact.export`，`critical`）并过内容安全检查 |
| 凭据 | 容器内**不得持有任何长寿命密钥**（**已定口径，2026-09-13 裁决路径①**）：**容器内唯一注入物 = 我们签发的短期网关令牌**；**供应商密钥只在容器外的模型网关**。短期令牌**六条**见 §3.5 |

### 3.4 结果与审计（A1 的落地）

- **落库（文件级）**：`摘要 + args_digest + sha256 + 字节数` 的**唯一落点 = 导出时的对象存储元数据**（`artifact.export`）；**未导出的中间文件只落摘要，不落 `sha256`/字节数**。原稿写「只落四项」却没有落点，且与 Y3「不落这些」冲突——本轮明确落点，消除矛盾（评审 G4）。
- **正文落库口径（**2026-09-13 用户裁决 J7 = 丙案**）**：
  - **默认（不变）**：**永不落正文**——送模型时当轮上下文可有原文，**持久化只落摘要**。
  - **唯一受控例外（受控正文密文列）**：**仅当**「工具动作**需审批**且其参数含 `body` 类」时，`body` 原文允许落**受控密文列**（列名 `body_ciphertext` + `body_expires_at`，见 §4.1.1；**文档层已定案；实现未落地——见 §8 U15**。**Q3 更正**：原文写"2026-09-13 已实施"，与 U15 矛盾，已改）。**五条约束缺一不可**：
    1. **密文**：由 **`BodyCipher`**（§4.1.6-1）执行应用层 AEAD 加密；**算法定死（Q2，2026-09-13）：AES-256-GCM**——**nonce 12 字节、tag 16 字节 → overhead 恒为 28 字节**；`body_ciphertext` 的字节布局 = **`nonce(12B) ‖ ciphertext ‖ tag(16B)`**（实现与测试须一致，且长度断言据此推导）；**密钥不落库、不进仓库**——来自**新增独立配置 `WORKBENCH_BODY_ENCRYPTION_KEY`**（§4；**不复用** `backup_encryption_key`，单一职责，宪法 4.10）；**明文不得**出现在日志、审计、错误信息或堆栈中。**密钥轮换（P4 定死）**：采用**双密钥窗口**——新密钥加密、旧密钥**仅用于解密**；**窗口长度 = 最大审批超时 + 清理周期**，窗口结束后旧密钥方可销毁；窗口内**不得**因轮换导致解密失败。失败语义见 §4.1.6-1.1。**nonce 与密钥格式（R3 定死，2026-09-13）**：① **每次加密随机生成 12 字节 nonce（CSPRNG），严禁重用**——**不得**由计数器、时间戳或密钥派生充当（**AES-256-GCM 下 nonce 重用致命**：同时破坏机密性与完整性）；nonce 随密文一并存储（见上布局）。② **密钥格式**：`WORKBENCH_BODY_ENCRYPTION_KEY` = **32 字节原始密钥、以 `base64` 编码放入环境变量**；**启动期校验「解码后长度必须为 32 字节」**，否则**拒绝启用真实执行并告警**（与 §4.1.6-3 同口径）。
    2. **TTL 与审批同寿**：到期时刻 = **该动作的审批超时时刻**；**审批落定（`approved` / `rejected` / `expired`）即清空**（同一事务）；**到期即清**；清理由**启动时 + 周期**执行；**清理失败必须告警并登记**（与 §3.3 的孤儿容器回收、工作卷销毁同口径）。落点与判据见 §4.1.5。
    3. **不导出**：**不得**进入任何业务导出或对外通道（`artifact.export`、报表、账单、通知、接口响应体）；备份沿用既有运维保留口径，但**不参与**业务读取。
    4. **审计不落**：审计明细仍为最小集（见下条），**不含**正文与 `args_digest`。
    5. **不参与摘要、不用于输出**：`args_digest` 仍在 ⑥ 按**完整参数**一次算定；密文**只服务**"审批通过后的重跑还原"，**不得**反算摘要、**不得**对外输出。**并明文定死（P5）**：占位常量 `"«body»"` **不参与任何比较、判定与响应重建**——读取方一律**按键**（依 `param_roles`）区分 `control`/`body`，**不得按值判定**；该常量**不得**进入 `args_digest` 的输入。判据见 §5 用例 32⑥。
  - **红线范围声明**：本例外**不放宽任何其他路径**——**未进入审批等待的 `body` 一律不落库**（同请求内完成的动作不落密文）；**非 `body` 类参数**仍按 §4.1.1 只落 `control` 副本。**判据见 §5 用例 32 / 33**（P8 双向引用）；**跨文档口径见契约「审批通过后的推进」段与「落库口径」节**。
- **对象存储**：仅当该文件本身属工作台受控范围且租户隔离/权限受控时才落；否则**连对象存储也不落**。
- **审计动作（硬要求）**：**必须新增** `AuditAction` 的 `tool.executed` / `tool.blocked` 两个动作码（原稿写「建议」，与契约不符，改为必须；**漏扩则 `GET /api/v1/audits?action=tool.executed` 会 422**，评审 M2）。
- **审计明细 = Y3 最小集**：新增 `tool_key`、`risk_level`，复用 `run_id` / `runtime_key` / `status` / `reason`；新增键须**同步扩 `ALLOWED_DETAIL_KEYS` 并配测试**。
- **`reason` 必须是受控枚举码**（`path_denied` / `blacklisted` / `param_invalid` / `not_authorized` / `not_in_catalog` / `timeout` / `runtime_error` / `approval_denied` / `approval_expired`——**共 9 值，与 §4.1.1 的 `reason_code` 同一集合**；第四轮修订 R4-3 已统一，原 6 值集合作废），**不得写入自由文本**——否则命令串、路径、异常 message 会随 `reason` 落进审计（评审 G5）。**作用域（重审更正）**：该约束**仅作用于 `tool.executed` / `tool.blocked` 两个动作码**，**不得**在 `ALLOWED_DETAIL_KEYS` 层做键级枚举——既有非工具动作（`app/accounts/service.py`、`app/content/service.py`、`app/workforce/config.py`、`app/planner/service.py`、`app/orchestration/service.py`）会把 `str(exc)` 写进 `reason`，全局收窄会误伤既有写入。
- **不建「工具调用记录表」**（X5 **已定**，2026-09-12）：工具调用进既有 append-only 审计，**不建第二事实源**。**第三轮更正**：原稿此处写作「**本段不新建表**（…授权位已有迁移 `026`）」，与 §4 的「**新增迁移 `027`**」（2026-09-12 用户裁决 R1）直接冲突——本段**确实新增迁移 `027`**，其承载**待批动作 + 逐项授权项**（执行闸门所需），**不是**工具调用记录表。

### 3.5 dsh 适配器

- dsh 全部细节**封在适配器内部**；对外只暴露本项目的 `AgentRuntimeAdapter` 契约。
- 用 `restrict` 收窄到**本模式允许的最小工具集**。**空交集 = fail-closed，作用域收窄（第二轮裁决）**：**拒绝装配真实执行、禁用真实执行并告警**（记 error）；**不得拒绝整个服务进程启动**——`tool_allowlist` 默认即为 `[]`（`migrations/023`），拒绝进程启动会让"一处配置错误打挂整个工作台"；恢复路径 = 修正配置或显式切 `WORKBENCH_AGENT_RUNTIME_BACKEND=mock`。**不得**回落为 dsh 默认最小集（其内容由上游定义，回落等于给出比预期更多的能力，评审 G6）。⚠️ **另注意**：`restrict` 的**运行期拦截效果尚未取证**（前置清单 §F3 自认"仍未取到"）→ 见 §8 U10；**取证前不得把 `restrict` 当作「第二道已成立」**。
- 会话：**归 dsh 所有**，我们只存引用；版本钉死，升级时**由我们显式执行迁移**（三代迁移包已存在）。
- 子进程宿主：`dsh --profile sdk`（stdio），**注意其无 cancel / 无 session-close / 无版本协商**（§2.3），因此超时与终止必须由**我们**在容器层实现。
- **dsh 进程位置与模型凭据来源（P1，2026-09-13 已定口径 —— 裁决路径①「自建模型网关」）**：实测确认**模型调用由容器内的 dsh 进程自己解析并发出**（剖面含 `dsh-llm`/`dsh-agent-default-model`；请求上下文含 `provider`/`model`，错误回传带 `code=AUTH`/`status=401`），且**SDK 握手不接受任何凭据字段**、`dsh-credentials-local` 明写预期密钥经**容器 `-e`** 传入（门禁 §F8.1）。**故必须新增「模型网关」组件**，口径如下：
  1. **位置**：网关跑在**容器外**（工作台侧）；**供应商密钥只在网关**，**任何情况下不进容器**（env / argv / 镜像层 / 文件 / 日志）。
  2. **容器内注入物**：`baseURL` 指向网关；`apiKeyEnv` 指向的凭据 = **我们签发的短期网关令牌**（**不是**供应商密钥）。
  3. **短期令牌六条（硬要求）**：① **每 turn 新铸**；② **绑死租户 / 会话 / 代次**；③ **服务端为准**（不信任容器内声明）；④ **constant-time 比对**；⑤ **终态同步吊销**；⑥ **孤儿上限**。**禁止**任何"开机固定的共享令牌"。
     **② 与 ④ 的校验点（2026-09-13 用户裁决 · 新增口径）＝「工作台控制面」**：即**执行侧回调工作台**（导出产物 / 请求授权）时，由工作台按令牌**反查**其 `(tenant, session, generation)` 并与当前执行比对（**constant-time**），不匹配即拒。**网关数据面不做绑定校验** —— 容器经网关的模型调用**只判「令牌存在且未过期」**；网关侧记录的 `bound` **仅作审计元数据、不构成安全边界**（原型实测见门禁 §B14 F 行与 `_dsh-gateway-verify\out\30-binding-gw.log`）。**理由**：网关是**透明转发面**，无从得知调用方声称的执行身份，而**调用方本身即不可信侧** ⇒ 在网关做比对**只能防误用、不能防伪造**；只有**服务端权威记录处**的比对才是真边界。⚠️ **本条为新增口径，须随本规格下一次评审确认。**
     **〔2026-09-13 补充口径（U17-②④ 收口，用户裁决）〕**
   - **`generation`（代次）定义** ＝ **会话内 turn 序号**（单调递增整数，**从 1 开始**；**每铸一次令牌 +1**）—— 与 F①「每 turn 新铸」天然对齐，故**「旧代次令牌」＝ 上一 turn 的令牌**。
   - **反查数据来源** ＝ **工作台侧自持绑定**：令牌由**我们（工作台）签发**（见 P1 之 2），签发时即在本地落一份 `(tenant_id, session_id, generation, token)`；控制面**直接本地反查**、**不新增「工作台→网关」调用链**；「**服务端为准**」成立（工作台即签发方）。**失效 / 吊销时两处副本须同步清**（网关侧的 `tokens` Map 与工作台侧这份绑定）。
   - **落点与时机** ＝ **实现挂在段二-4 的对话入口 / 回调面**（2026-09-13 用户裁决选 (a)）—— 因为规格所述的两个回调场景（**导出产物**、**请求授权**）**当前都不存在**：`artifact.export` 是**自建工具、不经容器**（§3.1.1 注 2），对话入口属段二-4。**⇒ 当前无调用方，故不实现**（避免造出"没人调用的校验"—— `/__revoke` 的前例）。判据见 §5 **用例 35**。**在实现之前，不得声称「②④ 已强制」。**
  4. **网关职责**：只做**凭据注入 + 转发 + 计量/限流 + 审计**；**不得**改写模型语义；**超时/重试上限必须显式配置**（归口在此，不在容器内）。
  5. **网络面**：容器**无外网出口**，**仅可达网关**（§3.3）。原"`--network none` 下 turn 仍成功"的口径**正式作废**——它与 dsh 架构不相容；**改判为 C′：容器内不存在指向供应商域名的连接**（见门禁 §B14）。
  6. **取证要求**：B14 判据 A/B/E/F 与 **C′** 须用**真实 turn** 取证；**取证前不得声称「容器内不持有模型密钥」**。

**🔴 剖面必须锁死（2026-09-12 运行期实测得出，见[前置清单](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-preflight-checklist.md) §F3）**：

实测 `dsh --profile sdk --dump-default-config`（352 行，`exit=0`），并按 `disabled` 逐条核对：

| 实测项 | 实测值 | 段二必须做什么 |
| --- | --- | --- |
| **`DSH_PERMISSION_MODE`（总闸）** | `sandbox-policy.mode` = `env ?? 'workspace-write'`；`approval.policy` = `mode === 'danger-full-access' ? 'never' : 'ask'`；`permission-presets` 定义了 `danger-full-access: {sandbox: danger-full-access, approval: never}` | **显式设为 `read-only`**（不得放任默认值），启动时**断言**；**设成 `danger-full-access` 就等于同时关掉沙箱与审批** |
| `sandbox-policy.workspaceRoot` | **`process.cwd()`** | 必须以**我们指定的工作目录**为 cwd 启动；**不得**以 `/` 或宿主目录为 cwd |
| **`tool-bash` + `bash-sandbox`** | Linux 上**未禁用**（按平台：`disabled: platform === 'win32'`） | **显式禁用**（Windows 侧对应 `tool-pwsh`）；否则绕过「结构化命令、禁止 shell 解释」的闸门 |
| **联网工具** | `dsh-web`（`fetchProvider: http`）、`dsh-web-search-deepseek`（**读 `DEEPSEEK_API_KEY`**）、`dsh-web-fetch-http`、`dsh-tool-web`（`fetch: true`）**均未禁用** | **全部显式禁用**（与 A4 冲突）。注意：容器里只要存在 `DEEPSEEK_API_KEY`，它就能自行联网——既是**绕过联网归口**，也是**密钥进容器**的实证风险 |
| 🔴 **遥测插件（§F7.3 新发现，2026-09-13 补 D-A）** | `dsh-session-telemetry-otel` **未禁用**；`config.mode = env DSH_TELEMETRY_MODE \|\| 'FEEDBACK_ONLY'`；`exporter.url = env DSH_TELEMETRY_OTLP_URL ?? 'https://harness-telemetry.deepseeksvc.com/v1/logs'`。**§F8.1④ 补充**：上游另有专用开关 **`process.env.DSH_TELEMETRY_DISABLED`** | **首选手段：设 `DSH_TELEMETRY_DISABLED`**（上游自带开关，比禁用插件轻）；**并以「禁用该插件」为兜底**。两者之一必须进**启动期断言**（与 §3.5 其余禁用项同口径）。**理由（2026-09-13 实测更正，门禁 §F10）**：与 **A4（不出网）** 相关；但对照实验显示——**设 `DSH_TELEMETRY_DISABLED` 与不设该变量，两轮本地假 OTLP 端点均收到 0 个请求** ⇒ **本场景并无可观测的遥测外发**（`mode` 默认 `FEEDBACK_ONLY` 的合理含义是"**仅反馈路径才发**"），**故原"web 之外的第二条默认出网通道 / 即使禁掉联网工具仍会出网"的表述不成立**。**保留该开关作为兜底仍合理**（成本极低、上游自带），**但不得再表述为"默认外发"** |
| `dsh-user-approval` | 未禁用，`policy` 默认 `ask` | 不依赖它做跨进程审批（§2.1）；但**`ask` + SDK 无审批方法**可能导致工具调用挂住 → **必须用一次真实调用复验该行为** |
| `dsh-subprocess-local` | 未禁用 | **显式禁用（2026-09-12 第二轮裁决）**：与 `tool-bash` 同等对待——若模型可经它自行起子进程，则 **④-0 / ④-1 / ④-2 整段结构化命令闸门被整体绕过**（重审发现）。必须与 `tool-bash`/`tool-pwsh`、`web_*`、**`dsh-session-telemetry-otel`（2026-09-13 补）**、`skill`、`subagent*` 一起进禁用清单并在**启动时断言** |
| 🔴 **`bash` / `write` / `edit` 的「沙箱升级通道」** | 三个工具的参数里都有 `sandbox_permissions ∈ {workspace-write, danger-full-access}` + `justification`，描述写「沙箱拒绝后的一次性重试，需用户批准」（实测计数：`danger-full-access`×3、`sandbox_permissions`×8、`justification`×7） | **必须显式阻断**：只设 `DSH_PERMISSION_MODE=read-only` **挡不住**它——模型可主动申请升级；而跨进程审批通道**不存在**（实测反向请求 = 0），故升级请求要么被自动拒、要么挂住。**这三个工具整体禁用**，改由我们自建工具承担文件与命令能力。⚠️ 该升级通道的**真实行为（自动拒 / 挂住 / 静默放行）仍是清单自认的「最高优先级待验项」**，须在段二-1 用真实调用取证，并在 §5 有用例（评审附录 C#8） |
| **默认暴露 25 个工具** | 实测清单：`bash, write, edit, read, read_image, glob, grep, web_fetch, web_search, skill, subagent, subagent_fork, workflow, ralph, todo_write, exit_plan_mode, create_goal, get_goal, update_goal, job_list, job_output, job_kill, list_agents, send_message, interrupt_agent` | **白名单要显式开**：`subagent*`/`workflow`/`ralph`（可自行派生 agent、放大逃逸与成本面）、`web_*`、`skill` 一律禁用；数字员工层级由**控制平面**决定，不由 dsh 自行派生 |

> **口径**：剖面以「**默认全禁、按需显式开**」为准，而不是「默认全开、按需禁」。禁用清单与理由要进规格并在**启动时断言**（不是靠注释维系）。

### 3.6 开关与回滚

- **总开关（本轮明确配置项）**：`WORKBENCH_AGENT_RUNTIME_BACKEND`，取值 `mock`（**默认**）| `dsh`；**仅当显式设为 `dsh` 才启用真实执行**。设为 `dsh` 时，启动期必须断言 §3.5 的全套剖面（`DSH_PERMISSION_MODE=read-only`、禁用清单、`restrict` 非空工具面）。**断言失败的处置与 §3.5 的 `restrict` 空交集口径一致：拒绝装配真实执行并告警（记 `error`），不拒绝整个服务进程启动**——`tool_allowlist` 默认即为 `[]`（`migrations/023`），以抛异常终止进程会让「一处配置错误打挂整个工作台」（第三轮评审 P2，与裁决 R4 对齐）。
- 开关切回 `MockRuntime` 后，**全量用例必须仍全绿**（当前基线：后端 **1434**（2026-09-12 CI 实测）/ 管理台 147 / 伴侣端 37 / 桌面 19；后三项为文档原值，本次未复核）。
- 本段不做「灰度」；灰度属 P6 口径。

### 3.7 落地口径补充（Y1–Y3 已定，2026-09-12；本轮按评审更正）

| # | 决议 | 落地要点 |
| --- | --- | --- |
| **Y1** | **不加工具目录只读端点** | 沿用现有 `model_key` / `tool_allowlist` 惯例（前端自由文本 + 提示，后端 `422` 拒绝非法键）；符合 §1.2「不为假想需求预留」 |
| **Y2** | **对话触发执行时自动创建「承载任务 + Run」** | 复用既有 `/api/v1/tasks/{task_id}/runs` 与 `/runs/{run_id}/approvals/*`；**授权项与待批动作由新增迁移 `027` 承载**（2026-09-12 裁决 R1；`026` 降级为运行级快照，见 §3.2/§4.1）；`workbench_run_records.task_id` 保持 `NOT NULL` 不动；**幂等键 = 请求头 `Idempotency-Key`**（2026-09-12 裁决 R2；原「`message_id` 派生」方案实测不可行，见 §3.2）。**仅当带该键时才触发真实执行**（2026-09-13 裁决 R6） |
| **Y3** | **审计明细用最小集** | 新增 2 键 `tool_key`、`risk_level`，复用现有 `run_id` / `runtime_key` / `status` / `reason`；**不落** `args_digest`、虚拟路径、`sha256`、字节数；`reason` 为**受控枚举码**（§3.4） |
| **P1** | **dsh 进程位置与模型凭据来源** | **已定口径（2026-09-13 裁决路径①）**：**自建模型网关**——供应商密钥只在容器外网关，容器内仅短期令牌；网络面改「仅内网桥 + 仅网关可达」，**判据 C 作废、改 C′**（详见 §3.5） |
| **P2** | **执行同步 vs 后台化** | **保持同步 + 单次执行硬上限**（§3.3）；并发/排队属 P2b |
| **LGPL** | **许可证与 `THIRD-PARTY-NOTICES`** | **纳入本段交付物**：逐包核对许可证，并产出 `THIRD-PARTY-NOTICES`（§4） |

**承载任务字段口径（重审补，原稿只写"自动创建"未定字段级口径）**：

| 字段 | 取值 |
| --- | --- |
| `created_by` | **= 触发对话的操作者**（不得用系统账号，否则 `/tasks/{task_id}` 与运行可见性不一致） |
| `tenant_id` | 操作者租户 |
| `employee_key` | 会话绑定的 `agent_key`（**须已通过存在性与启用校验**） |
| `title` | 「对话触发：{会话标题或首条内容截断}」（**虚拟化，不含宿主路径**） |
| `risk_level` | 取该次执行中**最高**风险档（含 `critical` 工具 ⇒ `critical`） |
| `budget` | **0**（X4 已定：本段不做预算维度），并在审计登记该口径 |
| `idempotency_key` | 由 `Idempotency-Key` 派生（`conv-{conversation_id}-{key}`） |
| `request_fingerprint` | 对本批待批动作 + 规范化参数摘要取摘要 |
| `status` | 建时 `queued`；`pending_approval` 仅在 ⑥ 落库后置位（`001_initial.sql` 的 CHECK 只允许 `queued`/`pending_approval`/`cancelled`） |
| `ensure_can_create` | **必须复用**：`critical` 承载任务受「仅 CEO/超管可发起」约束（`app/domain.py:157-167`）→ 对话入口触发 `critical` 工具时，若操作者非 CEO/超管，**必须在 ① 之前以 `403` 拒绝**，不得"先建任务再拒" |

**Y2 的影响面（本轮按评审更正）**：原稿称承载任务「会出现在任务列表与任务维度指标中」，但评审已核实**系统并无任务列表接口**（仅 `POST /api/v1/tasks`、`GET /api/v1/tasks/{task_id}`、`POST /api/v1/tasks/{task_id}/approve`），运行指标只按 `runtime_key` 聚合。因此承载任务**无对外列表面**，原定的 `origin=conversation` 来源标记**予以撤销**（2026-09-12 用户裁决）——它与 §1.2 第 5 条「不为假想需求预留」冲突（原稿曾以「零新迁移」为由，该口径已被裁决 R1 推翻，**此处不再引用**；第四轮修订 R4-3）。**若将来新增任务列表接口，须在同一变更内定义承载任务的可区分口径，不得提前预留字段。**

---

## 4. 迁移与配置

| 项 | 内容 |
| --- | --- |
| 迁移 | **新增迁移 `027`**（2026-09-12 裁决 R1）：承载 ⑥ 的**待批动作**与 ⑦ 的**授权项**（逐项：待批动作 + **规范化参数摘要** + 批准人/时间 + 计划摘要），**并含对既有表 `workbench_run_records` 的 `UNIQUE (run_id, tenant_id)` 增补**（复合外键的父表侧约束）。**完整 DDL、字段规范对照、参数规范化算法、主从/事务、回退与前进兼容、装配与失败语义均见 §4.1 附录**（2026-09-13 裁决 R5：由「规格内一句话承诺」改为「规格内可评审定义」）。**属数据模型变更（地基）→ 须随本规格一并专项评审**。仍**不建「工具调用记录表」**（X5 不变：工具调用进既有 append-only 审计）；授权位 `026` 保留并**降级为运行级快照**（R7，见 §4.1.5） |
| 新增配置（外置） | `WORKBENCH_AGENT_RUNTIME_BACKEND`（默认 `mock`）、`WORKBENCH_EXEC_IMAGE_DIGEST`（**digest，非 tag**）、`WORKBENCH_EXEC_WORKSPACE_ROOT`、**`WORKBENCH_EXEC_TRUSTED_ROOTS`（重审补：受信任且不可写的可执行根，默认 `/usr/bin`）**、`WORKBENCH_EXEC_TIMEOUT_SECONDS`（**默认 `180` 秒** —— 2026-09-13 定值，见 §8 U11）、`WORKBENCH_EXEC_PIDS_LIMIT`（**默认 `256`**）、`WORKBENCH_EXEC_MEMORY_MB`（**默认 `2048`**）、**`WORKBENCH_EXEC_CPU_QUOTA`（重审补：宪法部署检查要求 CPU 上限；**默认 `2.0`**，对应 `docker --cpus`）**、**`WORKBENCH_EXEC_ORPHAN_LIMIT`（**⑥ 孤儿上限；**默认 `8`**；超限 → 拒绝新执行并告警（fail-closed，不打挂进程）；清扫 = 启动时 + 按 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 周期，跑在 API 进程内 —— 见 §8 U17）**、`WORKBENCH_DSH_VERSION`（精确版本）、`WORKBENCH_ARTIFACT_EXPORT_ENABLED`（**默认 `false`，fail-closed**：关闭时 `artifact.export` 不装配，请求被拒并记审计）、**`WORKBENCH_BODY_ENCRYPTION_KEY`（P3 新增：正文密文密钥；**必填且非空**；**格式 = 32 字节原始密钥的 `base64` 编码**（启动期校验解码长度，见 §3.4 约束 1 / R3）；配置外置、不进仓库；**不得复用** `backup_encryption_key`）**、**`WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`（P3 新增：TTL 清理周期；**默认 `60` 秒** —— 2026-09-13 定值，见 §8 U16；清理在**启动时 + 按此周期**执行，见 §4.1.5）**、**路径①「模型网关」六项（2026-09-13 裁决路径①新增，语义见 §3.5 P1 段；**§F8.6 第 6 项的"待补"就此闭合**）**：`WORKBENCH_MODEL_GATEWAY_BASE_URL`（**容器内 `baseURL` 指向的网关地址**，须在该内网桥内可达；**供应商域名不得出现在本项**）、`WORKBENCH_MODEL_GATEWAY_TOKEN_TTL_SECONDS`（**短期网关令牌有效期**；**默认 `300` 秒**；**每 turn 新铸**；**须 ≥ `WORKBENCH_EXEC_TIMEOUT_SECONDS`（§8 U11）**——两者默认值**已于 2026-09-13 一并定死**）、`WORKBENCH_MODEL_GATEWAY_UPSTREAM_BASE_URL`（**上游供应商端点**——**供应商域名只允许出现在网关侧/宿主侧**，**不得进入容器**）、`WORKBENCH_MODEL_GATEWAY_UPSTREAM_API_KEY`（**上游供应商密钥**：**必填非空、配置外置、不进仓库、不进容器**（env / argv / 镜像层 / 日志）；**启动期做与 `WORKBENCH_BODY_ENCRYPTION_KEY` 同口径的非空校验**，缺失则**拒绝启用真实执行并告警**）、`WORKBENCH_MODEL_GATEWAY_UPSTREAM_TIMEOUT_SECONDS`（**网关→上游超时**；**默认 `60` 秒**；**必须显式配置**，见 §3.5 P1 第 4 条）、`WORKBENCH_MODEL_GATEWAY_MAX_RETRIES`（**默认 `0`，fail-closed**：不隐式重试）** → **共 19 项**。**落点状态（2026-09-13）**：**19 项已全部进 `app/settings.py`**（含类型、默认值与 `ge/le` 边界；**不设裸名别名**，只认 `WORKBENCH_` 前缀）、**已全部进 `.env.staging.example`**，并由 **`tests/test_env_templates.py` 三个守护用例**覆盖（字段存在性 / 模板全覆盖 / 默认值钉死 + `TTL ≥ EXEC_TIMEOUT` 硬约束），**含反假测试**；⚠️ **"必填非空 / `base64` 32 字节"的启动期校验未实现**（归 §4.1.6-3 装配期）——见门禁 **§B15** |
| 环境分开（重审补） | 开发 / 测试 / 生产**分别登记**镜像与主机、工作卷根、凭据来源、开关取值：开发期允许**本机 Docker（仅验证机制，不得声称隔离达成）**；生产**分主机**且镜像按 digest 钉死。**不得把开发口径带进生产**（宪法 8.1） |
| 模板登记 | 新增配置项须同步 `.env.staging.example`。**注意**：现有 `tests/test_env_templates.py` **只覆盖** `sso_*` 与 5 个 Runtime 的 `endpoint`/`version`/`capabilities`/认证标记（评审 M3）——因此**本段必须同步扩该守护测试**，把上列新增配置纳入断言；**否则不得声称"已被守护"** |
| 依赖 | dsh 依赖写**精确版本**；**登记位置**为容器镜像构建文件 / 独立目录（**根目录无 `package.json`**，原稿未给落点，评审附录 B#13） |
| 许可证（**本段交付物**） | **逐包核对已完成（2026-09-12，前置清单 B13 + §F5）**：lockfile 口径 583 条目全量扫描并复现——`@deepseek-ai/*` **246 条 = 241 MIT + 5 BSD-3-Clause，全为宽松许可**；**全树无 GPL/AGPL**；**14 个 LGPL 条目全部来自 `sharp` 生态**（`@img/sharp-libvips-*` 10 个 + 组合式 `@img/sharp-win32-*`/`sharp-wasm32` 4 个）。**关键判定（2026-09-12 更正）**：`sharp` 是 **`dsh-base` 的普通（非 optional）传递依赖**（`dsh` → `dsh-base` → `dsh-attachment-local` → `sharp`），**因此 LGPL 义务无法靠"不启用附件功能"归零**；**当前已确认可行的减范围手段**是用 `--os`/`--cpu`/`--libc` 过滤非目标平台包，把随镜像的 **LGPL 条目从 14 个压到 1 个**（仅 `@img/sharp-libvips-linux-x64`；另一平台包 `@img/sharp-linux-x64` 是 **Apache-2.0**，不计入 LGPL——重审指出原稿「压到 2 条 LGPL」构成错误，已更正）。**必须产出 `THIRD-PARTY-NOTICES`**（含 LGPL-3.0-or-later 全文 + 可重链接说明 + 源码获取途径），并**在镜像内复跑一次同口径扫描**；"物理剔除 libvips 使义务归零"**属段二-1 实测项，未测前不得作为方案**。**决议（2026-09-12）**：**保留 `sharp`**，并**把随镜像的 LGPL 条目瘦身到 1 个**（随镜像的 `@img/*` 包共 2 个，其中 LGPL 仅 1 个）——镜像构建必须用 `--os`/`--cpu`/`--libc` 过滤非目标平台包；`THIRD-PARTY-NOTICES` 须含该 LGPL 条目的 **LGPL-3.0-or-later 全文 + 可重链接说明 + 源码获取途径**。两项列入 §6 验收。**口径更正（第三轮，评审 P14）**：上文「逐包核对已完成」**仅指按 lockfile 声明值完成的统计**；**逐包比对许可证正文（583 条目）、产出 `THIRD-PARTY-NOTICES`、镜像内二次扫描仍未完成** → 由段二-1 收口，见 §8 U13。**⚠️ 2026-09-13 实测更正（D-B，见前置清单 §F7.4）**：本行两处「LGPL 条目从 14 个**压到 1 个**」「随镜像 `@img/*` **共 2 个、LGPL 仅 1 个**」**与实测不符**——Linux 安装树实测为 **`@img/*` 4 个包、含 LGPL 2 条**（`@img/sharp-libvips-linux-x64`、`@img/sharp-wasm32`）⇒ **`THIRD-PARTY-NOTICES` 须含 2 条 LGPL**；**口径以 §8 LGPL 行为准**。 |

---

### 4.1 迁移 `027` 设计（附录，2026-09-13 随裁决 R5 并入）

> **性质**：本节即该迁移的**设计文件落点**（宪法 4.4 六步⑥「先出设计文件（`schema.sql` 或 migration）**再建表**」）。此前同内容位于 `docs/superpowers/plans/2026-09-12-dsh-foundation-design-draft.md`，该文件自述「不是阶段规格、状态：待评审」且**未被本规格引用**——第三轮评审据此判「地基变更评审不充分」（R3-1）。**按裁决 R5 并入本节，草稿文件转归档。**
> **⚠️ 本节仍未通过评审**：**评审通过前不得建表、不得写实现代码**；本节全部 DDL 为设计稿，实现时以 `migrations/027_*.sql` 为准并回改本节。
> **〔2026-09-13 更正：本横幅已过时，勿据此误判〕** —— **「评审」这一层门槛已解除**：本规格已于 2026-09-13 通过评审（状态「**已评审（附记录）**」）；评审记录 **§21「最后一次补丁确认」判 R1 / R2 / R3 全部真闭合**，且记录明确「通过后规格**方可**改为『已评审（附记录）』、门禁 §C1 视为过闸 —— **此后才可建 `migrations/027`**」（**但括注：仍受门禁 §B 其余条目约束**）。
> **🔴 但「可建表」≠「现在可以建」**：门禁清单自述「**尚未过闸**」（§B 取证须逐条完成，见其 §0 状态行与 §E 第 5 条），而 **§B14 的一项已挂起、§B15 判据 1 部分闭环** ⇒ **在门禁过闸之前，本节 DDL 仍不得落地**。
> **🔴 执行顺序（第四轮修订 R4-1，必须遵守）**：`migrations/027_dsh_tool_execution.sql` 单文件内**必须先执行 §4.1.2 的 `ALTER TABLE workbench_run_records … ADD CONSTRAINT … UNIQUE (run_id, tenant_id)`**，**再执行 §4.1.1 与 §4.1.3 的 `CREATE TABLE`**。否则复合外键引用不到父表唯一约束，PostgreSQL 在建表时即报 *there is no unique constraint matching given keys for referenced table*（`migrations/013` 只有 `PRIMARY KEY (run_id)`）。
> **父表侧唯一约束已核对**：`workbench_conversations` 为 `PRIMARY KEY (tenant_id, conversation_id)`、`workbench_conversation_messages` 为 `PRIMARY KEY (tenant_id, message_id)`（`migrations/023:24,39`）→ 本节复合外键**成立**；仅 `workbench_run_records` 侧需 §4.1.2 的增补（`migrations/013` 只有 `PRIMARY KEY (run_id)`）。

#### 4.1.1 表 `workbench_tool_actions`（待批动作 = 授权项，同行同表）

**设计取舍**：一个工具动作的生命周期是 `pending → approved / rejected / expired`，**待批动作与授权项是同一行的两个状态**。合成一行后，「批准的是哪个动作」不存在"另一行可比对"→ 从结构上消除「批准 A、执行 B」；也不产生第二事实源。

```sql
-- 文件名：migrations/027_dsh_tool_execution.sql
CREATE TABLE IF NOT EXISTS workbench_tool_actions (
    tenant_id         TEXT NOT NULL,
    action_id         TEXT NOT NULL,      -- 服务端生成（唯一标识不由客户端决定）
    approval_id       TEXT,               -- **决议入口键**（R4-6 新增）：⑤/⑥ 生成待批动作时一并写入；决议端点按 (tenant_id, run_id, approval_id) 唯一定位该行，从而取回冻结的动作与参数
    run_id            TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    step_id           TEXT NOT NULL,
    tool_key          TEXT NOT NULL,      -- 必须仍在工具组装面内，执行前复查
    args_digest       TEXT NOT NULL,      -- 规范化参数摘要（算法见 §4.1.4）；**覆盖完整参数**（含正文类参数）
    args_json         JSONB NOT NULL,     -- **规范化参数的受控落库副本**（**R5-1 新增**）：**仅**承载**控制参数**；正文类参数一律以占位常量 "«body»" 替代 → **正文不落本表**（边界定死，见下方「`args_json` 的正文边界」）
    body_ciphertext   BYTEA,              -- **受控正文密文列**（**J7 = 丙案，2026-09-13 定**）：**仅**「需审批且含 `body` 类参数」的动作非空；AEAD 密文，**密钥不落库**（§3.4「唯一受控例外」五条约束）
    body_expires_at   TIMESTAMPTZ,        -- 正文密文到期时刻 = **该动作的审批超时时刻**；与 `body_ciphertext` **同有同无**（见下 CHECK）；**审批落定即清空**
    plan_digest       TEXT NOT NULL,
    risk_level        TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
    requires_approval BOOLEAN NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired')),
    requested_by      TEXT NOT NULL,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by        TEXT,
    decided_at        TIMESTAMPTZ,
    decision_source   TEXT,               -- 决议来源：服务端判定并在白名单内校验，不来自请求体
    reason_code       TEXT,               -- 受控枚举码；自由文本一律不落（§3.4）
    PRIMARY KEY (tenant_id, action_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records (tenant_id, run_id),
    -- 决议字段全有或全无（与 026 的 CHECK 同一思路）
    CONSTRAINT workbench_tool_actions_decision_check CHECK (
        (status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    ),
    -- 正文密文与到期时刻「同有同无」（J7 = 丙案）：防「有密文无 TTL」（永不过期）与「有 TTL 无密文」（空清理）
    CONSTRAINT workbench_tool_actions_body_check CHECK (
        (body_ciphertext IS NULL AND body_expires_at IS NULL)
        OR (body_ciphertext IS NOT NULL AND body_expires_at IS NOT NULL)
    )
);

-- 同一运行同一计划步只允许一个待批动作（防重复落库；已决议的历史行不受限）
CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_pending_unique
    ON workbench_tool_actions (tenant_id, run_id, step_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_workbench_tool_actions_run
    ON workbench_tool_actions (tenant_id, run_id, requested_at DESC);

-- 决议入口键的唯一映射（R4-6）：同一运行内 approval_id 不得指向两行
CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_tool_actions_approval
    ON workbench_tool_actions (tenant_id, run_id, approval_id)
    WHERE approval_id IS NOT NULL;
```

`reason_code` 取值（受控枚举，**与 §3.4 的 `reason` 为同一集合、共 9 值**——第四轮修订 R4-3 已统一；该集合同时是审计 `reason` 的取值来源，其中 `not_in_catalog` 为 ① 步失败所必需）：`path_denied` / `blacklisted` / `param_invalid` / `not_authorized` / `not_in_catalog` / `timeout` / `runtime_error` / `approval_denied` / `approval_expired`。

**字段规范对照（宪法·数据层红线）**：

| 判据 | 落实 |
| --- | --- |
| 表名/字段英文+下划线 | ✅ `workbench_tool_actions` |
| 主键 | ✅ 复合 `(tenant_id, action_id)` |
| 租户隔离 | ✅ **写进约束**（复合外键 `(tenant_id, run_id)`），不只靠 `WHERE`，与 `migrations/023` 同思路 |
| 时间戳 | ✅ `requested_at DEFAULT now()`；决议时间 `decided_at` |
| 状态取值显式定义 | ✅ `status` / `risk_level` 均由 `CHECK` 枚举 |
| 幂等/防重复 | ✅ 部分唯一索引（同一 `run+step` 仅一个 `pending`） |
| 金额不用浮点 | 不适用（本表无金额字段） |
| 软删除 `deleted_at` | **不设**——本表**不提供 DELETE 路径**（重新审批 = 新行），软删除无适用对象；属**显式例外**，理由登记于此，清理策略见 §4.1.5。**注（R4-3 更正）**：本表**并非 append-only**——决议会**就地更新** `status` / `decided_by` / `decided_at` / `reason_code`，故按「状态表」口径管理；原「append-only」表述与事实不符，已更正 |
| 并发 | ✅ 部分唯一索引使同一 `run+step` 的并发落库**只有一行胜出**；**并发审批为「首写获胜」——重复决议返回 `409`**（与实码 `ApprovalAlreadyDecided` 一致；R4-3 已同步契约 `:592`，原「最后写入获胜」口径作废，见 §4.1.5） |
| **字段内容边界**（J7 = 丙案） | ✅ `body` 原文**默认不落库**；**唯一例外** = 「需审批且含 `body` 参数」的动作落**受控正文密文列**（`body_ciphertext` + `body_expires_at`）：AEAD 密文、**密钥不落库**、**TTL 与审批同寿**、**审批落定即清**、**不导出**、**审计不落**（§3.4 + 下方边界 + §4.1.5）。**`args_json` 仅落 `control`**（`body` 以占位常量 `"«body»"` 替代） |

**`args_json` 的正文边界（R5-1，定死；与 §3.4「永不落正文」的关系）**

> **背景**：§3.2 要求审批通过后「从 `027` 取回**冻结的动作与参数**并从 ① 重跑」，⑦ 要求「参数摘要比对」；而 §3.4 要求「**永不落正文**」。两者此前**无落点、互相矛盾**（第五轮阻断项 R5-1）。本列即该矛盾的**唯一落点**，边界如下——**六条，缺一不可**：

1. **参数二分类**：由**工具目录 schema 逐参数声明**——`control`（路径 / 命令 / 查询串 / ID / 数量 / 枚举等）与 `body`（**内容正文**，如 `fs.write` 的 `content`、待写入的消息或文档正文）。**落点**：`ToolSpecCatalog` 的 **`param_roles`** 字段（§3.1）；**逐工具标注见 §3.1.1**（本规格内仅 `fs.write` / `fs.overwrite` 的 `content` 为 `body`，其余均为 `control`）。⚠️ **无默认值（P1 修订，2026-09-13）**：**必须为每个参数显式声明角色；任一参数未声明 → 拒绝装配**（fail-closed）。原"默认 `control`、漏声明属实现缺陷"口径**已作废**——它会让正文以明文进 `args_json`，与 §3.4 红线**方向相反**（第七轮复核判为 fail-open）。**判据见 §5 用例 34（机制）与 32⑥ / 33①（后果）**（R1 补：连接"原因"与"后果"）。
2. **`args_json` 只落 `control`**：每个 `body` 类参数的值一律写为**占位常量** `"«body»"`（固定字面量，不含量级信息）。→ **`args_json` 与 `args_digest` 不是同一输入**：`args_digest` 在 ⑥ 落库时按**完整参数**（**含 `body` 原文**）一次算定。**该差异须写入实现注释；严禁据 `args_json` 反算 `args_digest`。** 判据见 §5 **用例 32⑥**（Q1 双向引用）。
3. **`body` 原文**默认**不落任何持久层**：不落本表、不落审计（§3.4 明细键最小集不变）、不落日志、不落幂等表。**唯一例外** = §3.4 的「唯一受控例外（受控正文密文列）」（**J7 = 丙案**）→ **§3.4 的「永不落正文」现为「默认 + 一处受控例外」，不再是绝对口径**（本条为 2026-09-13 更正）。判据见 §5 **用例 32⑤ / 33①**（Q1 双向引用）。
4. **重跑时 `body` 的来源（**第六轮 R6-1 更正；J7 = 丙案**）**：**从受控正文密文列解密还原**（五条约束见 §3.4）。**原口径「从各自的事实源重新读取——文件正文从工作卷读」作废**，理由（第六轮阻断 R6-1，A/B 两视角独立收敛）：① `fs.write` / `fs.overwrite` 的 `content` 是**模型待写入的新内容**，**不存在可复读的事实源**（前者目标文件尚不存在、后者工作卷里是旧内容）；② §3.3 `:254`/`:255` 规定工作目录「生成即空、运行结束销毁」、容器「任务结束即销毁」，而 ⑥ 是「先落库、再阻塞」——**跨请求审批等待期的存活语义无法支撑该口径**。重跑时**按还原后的完整参数重算 `args_digest` 并与本行比对**，不一致 → `409`（§4.1.6-5 ⑦）→ **「批准 A、执行 B」（含正文）仍被 ⑦ 拦住。** 判据见 §5 **用例 32① / 32③**（Q1）。
5. **⑤ 的例外关闭（**第六轮 R6-2/丙案 更正**）**：原「无可复读事实源的 `body` → 在 ⑥ **一律拒绝并返回 `422`**」**作废**——J7 采丙案后，此类动作**允许**落库等待（正文走受控密文列）。**⑥ 只保留一种失败：落库失败 → `503`，不进入等待。** **仍禁止**「把正文暂存内存等审批」（重启即丢，且产生第二事实源）——**只能走受控密文列**。判据见 §5 **用例 32**（Q1）。
6. **大小边界**：`args_json` 仅含 `control` → 受 schema 既有参数大小上限约束，**不会因正文膨胀**；**单行上限**（含"是否需在库层加长度约束"）留待段二-1 实测后定值（**登记于 §8 U14**）。

#### 4.1.2 对既有表的结构变更（**须一并评审**）

```sql
-- 复合外键需要父表侧唯一约束。013 只建了 PRIMARY KEY (run_id)，
-- 故补 UNIQUE (run_id, tenant_id)：否则只能用单列外键，丢租户维度（跨租户可达）。
--
-- 🔴 **写法更正（2026-09-13 真库演练发现；本节原口径作废）**：原写"与 024/025/026 同写法：
--    先 DROP IF EXISTS 再 ADD，可重复执行"——**该写法在 027 不成立**：两张新表
--    （workbench_tool_actions / workbench_execution_idempotency）持有指向该唯一约束的复合外键，
--    整组重跑时 DROP CONSTRAINT 会因依赖对象存在而失败：
--      ERROR: cannot drop constraint workbench_run_records_run_tenant_unique
--             because other objects depend on it
--    实现改用 **DO 块按 `pg_constraint` 判定后增补**（PostgreSQL 无 `ADD CONSTRAINT IF NOT EXISTS`），
--    且**不使用 CASCADE**（否则连带删掉两张表的复合外键）。
--    **落地文件 `migrations/027_dsh_tool_execution.sql` 为唯一实现来源。**
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workbench_run_records_run_tenant_unique'
          AND conrelid = 'workbench_run_records'::regclass
    ) THEN
        ALTER TABLE workbench_run_records
            ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id);
    END IF;
END
$$;
```

**影响面与回退**：只新增一个唯一约束，**不改列、不改既有查询语义**；`run_id` 本就是主键，既有数据在 `(run_id, tenant_id)` 上必然唯一，**无需回填**。回退见 §4.1.5（`DROP CONSTRAINT`）。**这是对既有地基表的变更，须在变更记录中登记（宪法 1.4）**，不得"偷偷用单列外键"。

#### 4.1.3 表 `workbench_execution_idempotency`（B5 的落点）

**为什么需要**：幂等键改为客户端可重放的请求头 `Idempotency-Key` 后，**必须有一处记录「该键对应哪一次执行的哪个结果」**，否则「重放返回既有结果」无法兑现。**只存指针、不存正文**：首次响应由 `message_id` 反查 append-only 消息表重建，避免与消息表形成第二份副本。

```sql
CREATE TABLE IF NOT EXISTS workbench_execution_idempotency (
    tenant_id       TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    message_id      TEXT,            -- 首次生成的助手消息（响应由此重建）；**可空**（R4-5）：闸门拒绝 / 首次执行即失败等场景可能不追加助手消息
    run_id          TEXT,            -- 首次派生的运行；未派生（如被拒）时为空
    approval_id     TEXT,            -- **J-4 新增**：首次返回 `202` 时的决议入口键——重放须原样重建 `202` 响应体（契约 `:642` 要求 `run_id`+`approval_id`），而**一个运行可有多个待批动作**、无法由 `run_id` 唯一反查，故必须落列；非 `pending_approval` 时为空
    outcome         TEXT NOT NULL CHECK (outcome IN ('executed','pending_approval','rejected','failed')),  -- R4-3：3 值 → 4 值（补 failed）
    http_status     INTEGER NOT NULL,  -- **R5-2 新增**：首次响应的 HTTP 状态码（唯一结果码来源）；重放原样复用
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 复合主键即去重机制：并发重放由 INSERT ... ON CONFLICT DO NOTHING 收敛为一行
    PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES workbench_conversations (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, message_id)
        REFERENCES workbench_conversation_messages (tenant_id, message_id),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES workbench_run_records (tenant_id, run_id),
    -- 结果码与 outcome 的合法组合（**J-5 新增**）：防「executed + 409」这类无法重建的非法组合入库
    CONSTRAINT workbench_execution_idempotency_result_check CHECK (
        (outcome = 'executed'          AND http_status = 201)
        OR (outcome = 'pending_approval' AND http_status = 202)
        OR (outcome = 'rejected'         AND http_status IN (403, 404, 409, 422))
        OR (outcome = 'failed'           AND http_status IN (502, 504))
    )
);

CREATE INDEX IF NOT EXISTS idx_workbench_execution_idempotency_run
    ON workbench_execution_idempotency (tenant_id, run_id)
    WHERE run_id IS NOT NULL;
```

- **作用域**：`(tenant_id, actor_id, conversation_id, idempotency_key)`——跨租户、跨会话、跨发起人互不影响；与 `001_initial.sql:18` 承载任务侧的 `UNIQUE (tenant_id, created_by, idempotency_key)` **不冲突**（两张表、两个用途，已登记为显式区分）。
- **并发重放**：`INSERT … ON CONFLICT (…) DO NOTHING`；冲突则以库中已存在行为准并返回首次结果 → **并发重放只执行一次**。
- **四态都写幂等行（R4-3 修订）**：`201`（`executed`）/ `202`（`pending_approval`）/ 拒绝码（`rejected`）/ **首次执行即失败（`failed`，对应 ⑧ 的 `504`/`502`）**，均**同事务**写入幂等行，保证重放与首次**完全一致**。**⑥ 例外（J-5 补齐）**：**⑥ 落库失败（`503`）不写本表**——⑥ 与本行属**同一事务**，⑥ 失败即事务回滚，故**不存在"首次 `503`"的行**；重放该键会**重新走一遍闸门**（此时未产生任何消息/任务/运行/副作用，**不违反幂等**）。**〔2026-09-13 用户裁决·实现口径登记〕落地为「显式补偿回滚」，非字面 DB 事务**：四类对象（承载任务 / 运行记录 / 会话消息 / 幂等行）分属**四个各自持有连接的独立仓储**，**无可挂靠的 Unit-of-Work / 共享连接层** ⇒ 按创建顺序**逆序补偿**（撤销 运行记录 → 进程内运行状态 → 承载任务；幂等行本就不写、消息在 ⑥ 成功后才追加 ⇒ 二者天然为 0）。**可观测结果与"同一事务"一致**（请求结束后四类对象均查不到，已由用例断言）。**若评审要求字面事务**，须另行引入 Unit-of-Work（**未做**）。**Postgres 分支的补偿路径未经真实库验证**（登记为未验证）。
- **响应重建（R4-5；R5-2 修订为可兑现）**：重放一律**直接复用本行保存的首次结果**——① **`http_status`（必填，存首次响应的 HTTP 状态码）为唯一结果码来源**，`201`/`202`/`403`/`404`/`409`/`422`/`502`/`504` 原样返回；② `message_id` 非空时由其反查消息表重建响应体；③ **`message_id` 为空时**（被拒 / 首次即失败）仅由 `outcome` + `http_status` 重建确定响应，**不得**因缺 `message_id` 而返回不确定结果；④ **`202` 响应体**须由 `run_id` + **`approval_id`** + `message_id` 重建（契约 `:642` 三者齐全）→ 故本表须落 `approval_id`（**J-4 新增**）。**R5-2 更正说明**：原口径写「按 `outcome` 返回同一拒绝码 / 同一失败码」，但拒绝码有 `422`/`403`/`409` 三种、失败码有 `504`/`502` 两种，**仅凭 `outcome` 无法唯一确定** → 增列 `http_status` 消除。
- **重放与「审批后执行」的关系（R5-2 顺带定死；原为未定义）**：幂等行记录的是**首次请求**的结果；审批通过后由**决议端点**触发的执行**不经 `Idempotency-Key`**，故**不回写**该行 → 重放该键**仍返回首次的 `202`**（与「重放与首次完全一致」同口径）。审批后的执行结果看**运行记录与审计**（`tool.executed` / `tool.blocked`），**幂等行不承担该职责**。
- **缺键不写本表、不触发真实执行**（裁决 R6，见 §3.2）；**本段不做清理、不设 TTL**（避免"过期后可重放"的新语义；**注意**：这是**幂等表**的口径，与 §4.1.5 的**正文密文列强制 TTL**是两回事）。**交叉引用（P10）**：**本表不落正文**——正文密文唯一落点是 §4.1.1 的 `body_ciphertext`（§4.1.1 边界第 3 条已禁"落幂等表"）。本表的幂等与响应重建判据见 §5 **用例 14 / 31**；**"本表不落正文"的判据见 §5 用例 33①**（Q1 双向引用）。
- **鉴权**：本表只为**服务端幂等判定**服务，**不对外暴露读取端点**；查询一律带 `(tenant_id, actor_id, conversation_id)` 归属过滤（宪法·数据归属）。

#### 4.1.4 参数规范化算法（`args_digest`）

**原则：只做「表示层归一」，不做任何"看起来一样就折叠"的模糊处理。**

| # | 规则 |
| --- | --- |
| 1 | 输入为 schema 校验通过后的 JSON 值（`null` / bool / 数字 / 字符串 / 数组 / 对象） |
| 2 | **对象**：键按 Unicode 码点升序排序；**保留 `null` 值**；**「缺键」与「键=null」视为不同**（不省略键） |
| 3 | **数组**：**保持原顺序**（顺序敏感，不排序） |
| 4 | **字符串**：先做 NFC 归一；**仅对 schema 声明为「路径」的参数**再做：`/` 分隔归一、折叠 `.`/`..`、去尾部 `/`（根除外）、**不做大小写折叠**（执行环境为 Linux，大小写敏感） |
| 5 | **数字**：按类型分别序列化，**不做跨类型折叠**（整数 `1` 与浮点 `1.0` 属不同类型 → 摘要**不同**）；**浮点不保留「字面量差异」**——`1.0` 与 `1.00` 解析后同为 `float 1.0`、序列化同为 `1.0`，故**视为相同**（其数值语义本亦相同）。**禁止浮点近似参与**——金额类参数必须由 schema 声明为整数分或字符串（与宪法「金额不用浮点」一致）。**注（R4-4 / R5-3 修订，两次）**：① 原「小数去尾随 0」与判据「`{"a":1}` vs `{"a":1.0}` → 不同」自相矛盾，已删（R4-4）；② R4-4 改写后新写的「`1.0` 与 `1.00` 亦视为不同」在规则 7 的 `json.dumps` 口径下**不可实现**（规则 1 的输入是已解析的 JSON 值，Python `float` 不保留尾随零）——该要求**已删除**，判据见 §5 用例 28（R5-3） |
| 6 | **布尔**：输出 `true` / `false`（小写） |
| 7 | **序列化**：`json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))`（排序已在规则 2 完成） |
| 8 | **摘要**：`args_digest = "sha256:" + sha256(utf8(序列化结果)).hexdigest()` |

**等价性口径**：规范化后字节相同 ⇒ 摘要相同；字节不同 ⇒ 摘要不同（除哈希碰撞外）。**不允许存在"语义相同但摘要不同"的可利用差异**。

**单测判据（**对应 §5 用例 28**）**：`{"a":1,"b":2}` vs `{"b":2,"a":1}` → **相同**；`{"a":1}` vs `{"a":1.0}` → **不同**（类型不同）；**`{"a":1.0}` vs `{"a":1.00}` → 相同**（同为 `float`，序列化同为 `1.0`；R5-3 定死）；`{"a":null}` vs `{}` → **不同**（缺键 ≠ null）；路径参数 `a//b` vs `a/b` → **相同**；路径参数 `A` vs `a` → **不同**；同一输入重复调用 → **稳定**。

#### 4.1.5 `027` 与 `026` 的主从、事务、回退与迁移工程约定（裁决 R7）

| 项 | 结论 |
| --- | --- |
| 授权权威 | **`027`（逐项）是工具执行的唯一授权权威**；执行放行只看 `027` |
| `026` 处置 | **保留、不删、不回填**；语义降级为「运行级授权快照」（段一读路径与粗判仍可用，**不得单独放行工具执行**） |
| 事务边界 | `decide_approval` 的「写 `027` 决议状态 + 写 `026` 快照 + 适配器决议」**同事务**，任一失败全部回滚 |
| 判定顺序（⑦） | 先按 `027` 逐项判放行；`authorization is None` 分支**仅允许**出现在「⑤ 判定无需审批」路径。**〔2026-09-13 用户裁决〕该路径完成 ②③④ 后直接进入 ⑧**（依契约闸门表「九步闸门 → HTTP 语义」）；原「该路径不得触达 ⑧」表述与契约冲突，**已作废**（否则无需审批的工具无法执行） |
| 并发 | 同一 `run+step` 并发落库由部分唯一索引收敛；**并发审批为「首写获胜」——重复决议返回 `409`**（与实码 `app/runtime/mock.py` 的 `ApprovalAlreadyDecided` 一致；R4-3 已同步契约 `:592`，原「最后写入获胜」口径作废） |
| 回退 | 先停真实执行（切回 `WORKBENCH_AGENT_RUNTIME_BACKEND=mock`）→ `DROP TABLE workbench_tool_actions` → `DROP TABLE workbench_execution_idempotency` → `DROP CONSTRAINT workbench_run_records_run_tenant_unique` → 删除 `workbench_schema_migrations` 中 `027` 的记账行 |
| 前进兼容 | 两张新表**不回填、无需回填**；唯一约束为纯增补；回退后 `026` 快照与段一行为不受影响 |
| 迁移工程约定 | 迁移按 `sorted(glob)` 顺序执行并记账于 `workbench_schema_migrations`，**无自动回滚**（`app/migrations.py`）→ 文件名须 `027_` 且排在 `026` 之后；DDL 一律 `IF NOT EXISTS` / `DROP … IF EXISTS` + `ADD`（与 024/025/026 同写法，可重复执行）。**⚠️ 例外（2026-09-13 真库演练发现）**：§4.1.2 对 `workbench_run_records` 的唯一约束增补**不得**用 `DROP … IF EXISTS` + `ADD`——两张新表持有指向它的**复合外键**，整组重跑时 DROP 必失败（*other objects depend on it*）→ 改用 **DO 块按 `pg_constraint` 判定**（见 §4.1.2 更正块）；**须同步 `.env.staging.example` 的迁移清单登记**（`tests/test_staging_assets.py` 对模板与 `migrations/*.sql` 做逐条相等断言，漏登则 staging 预检永远 `blocked`）；**须补 `027` 的静态契约测试**（沿用 `tests/test_persistence_contract.py` 同口径） |
| 清理策略（**幂等表**） | 本段**不做**清理（无 TTL）；保留策略属后续段次，登记于 §8 U12 |
| 清理策略（**受控正文密文列**，J7 = 丙案） | **强制 TTL，不再是"不做清理"**（与上条区分）：① 审批落定（`approved`/`rejected`/`expired`）→ **同一事务内清空**该列；② 审批未落定 → **到期即清**（到期时刻 = 审批超时时刻）；③ 清理由**启动时 + 周期**执行（周期 = `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`，P3 新增；与 §3.3 孤儿容器回收同口径）；④ **清理失败必须告警并登记**；⑤ 清理只记「已清理 / 清理失败」的**计数与既有动作码**，**不新增动作码**、**不落正文**；⑥ **本项属本段必做**（与幂等表保留策略不同——后者仍属后续段次）；⑦ 清理异常**不得**影响既有读路径与段一行为。**判据见 §5 用例 32③④**（P8 双向引用）；**到期置 `expired` 的执行方见 §4.1.6-8**（P6） |

#### 4.1.6 装配与失败语义（B4 的落点）

现状（已核对）：`decide_approval`（`app/runtime/service.py:116-134`）只写 `026` 授权位并转调适配器；决议端点（`app/main.py:1834-1877`）只持有 `runtime_service`，**无任何执行依赖**；仓库内目前**不存在** dsh 适配器 / 工具目录 / 容器执行器。

1. **新增 `ToolExecutionService`**，构造依赖：`ToolSpecCatalog`、**`BodyCipher`**（**P2 新增**：正文密文的加解密器与密钥管理；见 §3.4 约束 1 与下条 1.1）、`ContainerExecutor`、`WorkspaceManager`、`ToolActionStore`(`027`)、`RunRecords`、`Audit`。
   1.1. **加解密失败语义（P2 定死，fail-closed）**：① **⑥ 落库前加密失败** → **不落库、不进入等待**，返回 **`503`**（与"落库失败"同类，契约闸门表 ⑥ 行），记 `error` 日志，**不写 `tool.*` 审计**（未产生副作用）；② **重跑时解密失败**（⑦ 之后、⑧ 之前）→ 见 §4.1.6-5 失败表的**新增行**：`502` + `reason_code=runtime_error` + `tool.blocked` + 保持 `approved`（可重试/可人工介入）；③ **两种情形均不得**降级为"跳过该参数继续执行"或"用 `args_json` 的占位常量当参数"。
2. **装配点**：应用启动装配处（与 `runtime_service` 同处）创建；`WORKBENCH_AGENT_RUNTIME_BACKEND=mock` 时**必须为 `None`**。
3. **启动期断言（fail-closed）**：`backend=dsh` 时断言 `tool_execution`、`run_records`、`tool_actions` **三者非 `None`**，否则**拒绝启用真实执行并告警**（记 `error`，**不拒绝整个服务进程启动**，与 §3.5/§3.6 一致）。**并新增（P1 定死，2026-09-13）**：**断言 `ToolSpecCatalog` 中每个工具的每个 `params_schema` 参数都已显式声明 `param_roles`**——**任一参数未声明即拒绝启用真实执行并告警**（判据见 §5 **用例 34**）。
4. **调用链**：

```
POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval
  → runtime_service.decide_approval(...)
      → 【事务 A】写 027 决议状态 + 写 026 快照 + adapter.decide_approval
      → 若 approved：tool_execution.resume(run_id, approval_id)
            → 取 027 中 approved 行：**控制参数**从 `args_json` 取回；**正文类参数从 `body_ciphertext` 解密还原**（明文只在内存中存活到本次执行结束，**不回写、不进审计/日志**）
            → **重算完整参数的 `args_digest` 并与本行比对**（不一致 → ⑦ 返回 `409`）
            → 从 ① 重跑 ①–⑨（含 ②③④；禁止跳过）
            → **〔2026-09-13 用户裁决（U19 收口·方案 b）〕重跑路径不执行「运行级比对」**：⑦ 在此**只做逐行 `027` 校验**，**不调用**运行级闸门 `ensure_execution_authorized(actor, run_id, plan, …)` ⇒ `resume` **无需** `actor` / `plan` 参数。**理由**：§4.1.5 / R7 已定 **`027` 是工具执行的唯一授权权威**，`026` 三列已降级为「运行级快照」且**不得单独作为放行依据** ⇒ 运行级比对在重跑路径上**语义冗余**；且 `plan` 未持久化于 `run_records`（只有 `proposal_id`），回查须引入新依赖。**边界**：本豁免**仅限重跑路径**；**首次执行路径与 §3.2 ⑦ 的运行级比对不变**。
```

5. **重跑失败语义（定死）**：

| 失败步 | 状态码 | `026` 授权位 | `027` 行 | 审计 |
| --- | --- | --- | --- | --- |
| ① 工具已不在组装面（**审批后重跑路径**） | `409` | 保留 | 保持 `approved`，`reason_code=not_in_catalog` | `tool.blocked` |
| ② 参数校验失败 | `422` | 保留 | 同左，`param_invalid` | `tool.blocked` |
| ③ 路径越界 | `403` | 保留 | 同左，`path_denied` | `tool.blocked` |
| ④ 黑名单命中 | `403` | 保留 | **置 `rejected`**，`blacklisted`（不允许审批放行） | `tool.blocked` |
| ⑦ 之后·**正文解密失败**（**P2 新增**） | `502` | 保留 | 保持 `approved`（可重试 / 可人工介入），`runtime_error` | `tool.blocked` |
| ⑧ 超时 | `504` | 保留 | 保持 `approved`（可重试），`timeout` | `tool.blocked` |
| ⑧ 其它失败 | `502` | 保留 | 保持 `approved`（可重试），`runtime_error` | `tool.blocked` |
| ⑨ 成功（对外 `201`，见契约 `:641`；原写 `200`，J-5 更正） | `201` | 保留 | 保持 `approved` | `tool.executed` |

- **授权位不回滚的理由**：失败原因（超时 / 运行时错误 / 参数校验）与"批准意图"无关，回滚会把"批准一次、执行失败"变成"还要再批一次"；**④ 黑名单例外**——必须在 `027` 上留不可执行痕迹。
- **不新增"执行成功/失败"审批状态**（避免语义混淆）；执行结果只由审计与 `reason_code` 表达。
- **① 的结果码分界（J9 定死，2026-09-13；原第六轮阻断 R6-3）**：本表 ① 行取 **`409`** 是**审批后重跑路径**的语义——工具在**授权时存在**、**重跑时已不在组装面** = **状态漂移冲突**；而**首次执行路径**下"工具不在组装面"属**输入语义错误** → 由契约闸门表 ① 行给 **`422`**（与 ② 参数错误同类）。**两者刻意不同，且已双向写明**（契约 `:641` 状态码分支与闸门表 ① 行已补注）；**实现不得自行统一为一个码**，也不得只改代码不改文档。

6. **⑨ 之前各步的判定留痕（第三轮补，评审 P7）**：为让 §5 用例 16 可判定，**工具执行入口须对 ①–④ 的判定产出可观测记录**——命中即按 §3.4 写 `tool.blocked` + `reason` 枚举码；**②③④ 的通过路径亦须留下可断言的判定痕迹**（实现可为执行入口的判定序列记录 / 打桩可观测的调用计数，**不得新增审计动作码**，也**不含**参数原文与宿主路径）。
7. **决议端点响应体（定死，须同轮回改契约）**：在既有 `{run_id, approval_id, status, run_status}` 之上**新增可选字段** `execution: {outcome, code?, message_id?}`（`outcome ∈ executed / pending_approval / rejected / failed`）；**不改既有字段**；回改前须确认 `admin-web` / `companion-pwa` 对未知字段不报错（前端 strict 解析时须同步改）。判据见 §5 **用例 31**；**响应体不得含正文/密文**——判据见 §5 **用例 33②**（Q1 双向引用）。
8. **审批超时 → `expired` 的执行方（P6 定死，2026-09-13）**：**由「审批过期处理」承担**，与 §4.1.5 的清理任务**同批执行**（**启动时 + 按 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 周期**），**在同一事务内**完成三件事：① 置 `status='expired'`；② 写 `decided_by = "system:approval-timeout"`（**受控常量，不得来自请求体**）、`decided_at = 到期时刻`、`decision_source = "timeout"`（受控常量）；③ **清空 `body_ciphertext` 与 `body_expires_at`**。→ 同时满足 `decision_check`（非 `pending` ⇒ 决议两列非空）与 `body_check`（两列同有同无）。**不得只清密文而不改状态**——否则该行仍为 `pending`，一旦被批准将**无正文可还原**（届时落 §4.1.6-5 的解密失败行，属可避免缺陷）。

#### 4.1.7 待批动作的冻结与读取（**并入归档草稿 §2**，第四轮修订 R4-2）

> **为什么必须补**：第三轮判定 B2「参数摘要 + 逐项授权」在现有代码下不可实现（`PlanStep` 无参数字段、`plan_digest` 只取 4 字段摘要）。第三轮修订把落点定在 `027`，但**并入时漏掉了这一节的接口口径**——本条补回，使 ⑦ 有明确落点。

1. **待批动作的冻结（⑥）**：把 `{tool_key, 控制参数, plan_digest, risk_level, requires_approval}` 冻结为一行 `workbench_tool_actions(status='pending')`——**控制参数落 `args_json`；若含 `body` 类参数，正文经 AEAD 加密后落 `body_ciphertext`，并同事务写 `body_expires_at`（= 该动作的审批超时时刻）**（§3.4「唯一受控例外」五条约束）；**同事务**保存按完整参数（**含正文**）算定的 `args_digest`；**⑥ 落库失败 → 返回 `503`，不进入等待**（与契约闸门表 ⑥ 行一致）；**⑥ 失败不写幂等表**（同事务失败，见 §4.1.3）。
2. **审计归属**：⑥ 落库本身**不写 `tool.*` 审计**（避免新增动作码）；只有 ⑨ 成功写 `tool.executed`、被拒写 `tool.blocked`。
3. **执行对象唯一**：执行器**只执行 `027` 中 `status='approved'` 且 `plan_digest` 与运行当前计划一致的行**；**控制参数取该行 `args_json`，正文类参数从该行 `body_ciphertext` 解密还原，并重算完整 `args_digest` 与本行比对**（不一致 → `409`）→ **不存在「批准 A 执行 B」的通道**（B ≠ A 就没有对应的 `approved` 行，或有行而摘要对不上）。
4. **⑦ 逐项校验**：逐行核 `status='approved'` + `plan_digest` 一致 + **完整参数重算后的 `args_digest` 与本行一致** + `tool_key` 仍在组装面内 + ③④ 在重跑中通过；任一行不满足 → `409`，**不执行该行**。
5. **接口口径（关键）**：⑦ 需要一个**能拿到待判动作集合**的入口；现签名只比对计划摘要，**无法表达逐项与参数摘要**：

| 现签名 | 新签名（本段必须实现） |
| --- | --- |
| `RuntimeService.ensure_execution_authorized(actor, run_id, plan)` | `ensure_execution_authorized(actor, run_id, plan, actions: Sequence[ToolAction])` —— 新增**待判动作序列**；**缺省语义（R5-4 消歧，定死）**：`actions` 缺省时**仅退化为「运行级摘要比对」**（即 `026` 路径，**只变比对粒度**），**不含** §3.2 第 170 行所**明令禁止**的 `run_records is None → return` **fail-open** 行为；**装配 dsh 时 `run_records` 必须非 `None`，否则启动期即拒绝启用真实执行**（§4.1.6-3）。→ 此处"旧行为"**仅指比对粒度退化，不指 fail-open**（第四轮用词歧义已消除）。判据见 §5 **用例 29** |

   - **投影（本段原称 `ToolAction`，**实现名 `AuthorizationAction`**）**：`{ action_id, approval_id, step_id, tool_key, args_digest, plan_digest, risk_level, requires_approval }`——即 §4.1.1 表中与判定相关列的**只读投影**（**不含参数原文，也不含 `args_json`**——判定只需摘要投影）；`args_digest` 由 §4.1.4 算法产出。**8 个字段均须非空断言**（§5 **用例 29**）。
      **〔2026-09-13 命名更正〕** 本节原称该投影为 `ToolAction`，但 `app/tool_execution/store.py` 已有**同名却是 21 字段整行**的 `ToolAction` ⇒ 实现改名为 **`AuthorizationAction`**（定义在 `app/runtime/authorization.py`，**未 shadow、未复用同一个类**）。本节保留原名便于对照，**实现与判据以 `AuthorizationAction` 为准**（§5 用例 29③ 已并列断言与整行 `ToolAction` 的类型区分）。
   - **调用点（已定位）**：`app/runtime/service.py:105`（`resume` 传 `state.plan`）与**段二新增的工具执行入口**；**新增调用点必须显式传入 `actions`，不得留空**。
   - **缺省边界**：`actions` 缺省（`None`/空序列）**只允许**出现在「⑤ 判定无需审批」路径；**〔2026-09-13 用户裁决〕该路径完成 ②③④ 后直接进入 ⑧**（依契约闸门表）——原写该路径**不得触达 ⑧**，**已作废**（该表述出自评审「fail-open 收窄」条目，与契约闸门表冲突）。**不得**把该缺省当作「跳过 ⑥⑦ 直接执行」的开关。
6. **状态迁移不新增审计动作码**：`027` 行的 `pending→approved/rejected/expired` 迁移**不产生新的审计动作码**；决议事实由既有 `run.approval_decided` 与 ⑨ 的 `tool.*` 表达。

> **本节新增内容的评审范围**（**第六轮**请一并确认）：**§4.1.1 与 §4.1.3 两张新表 DDL**（含 `args_json` 的**「正文边界」六条**、幂等表 **`http_status`**）与字段规范对照、§4.1.2 对既有表的 `UNIQUE` 增补、§4.1.4 参数规范化算法、§4.1.5 主从/事务/回退/迁移工程约定、§4.1.6 装配与失败语义、**§4.1.7 待批动作冻结与读取（含 `ToolAction` 与签名变更）**；**§5 用例 28–31**。（**R5-4 更正**：原文误写"§4.1.1 两张新表"——两张新表分属 §4.1.1 与 §4.1.3。）

## 5. 测试计划（先写失败测试，后写实现）

| # | 用例 | 类型 | 风险级 | 必须红的方式 |
| --- | --- | --- | --- | --- |
| 1 | 白名单：组装时过滤 **且** 执行入口再校验（只改一处必须被拦） | 正常 | P0 | 去掉执行入口校验 → 必须红 |
| 2 | 结构化参数：未知字段 / 类型不符 → 拒绝 | 正常 | P0 | 放开未知字段 → 必须红 |
| 3 | 路径逃逸：`../../etc/passwd`、符号链接指向目录外 → 拒绝 | 异常 | P0 | 去掉 realpath 校验 → 必须红 |
| 4 | **④ 先于 ⑤⑦ 且审批后重跑**：观测点 = **审批通过后的第二次执行尝试是否重新经过 ②③④**。样本至少含 `rm -rf /workspace/x`、`/usr/bin/rm`（realpath 归一）、`bash -c "..."`、`python -c "..."`、`find . -delete`、`sed -i`、`chmod 777`、**`env rm -rf /workspace/x`**、**`busybox rm -rf /`**、**`/workspace/ls`（工作卷内同名脚本）** | 异常 | P0 | 改为「审批后直接从 ⑦ 续跑」→ 必须红（原稿「把黑名单挪到授权之后」**不可复现**：④ 挪到 ⑦ 之后仍在 ⑧ 之前，评审附录 A#18） |
| 5 | 风险定档 → `needs_approval`：`full_auto` + **`artifact.export`（`critical` 承担工具，§3.1.1）** → 仍要审批 | 正常 | P0 | 绕过 `needs_approval` 自写判定 → 必须红 |
| 6 | 授权位：未授权/摘要不符 → 拒绝执行 | 异常 | P0 | 去掉摘要比对 → 必须红（与段一同口径） |
| 7 | 结果落库：grep 不到文件正文 | 正常 | P1 | 直接落原文 → 必须红 |
| 8 | `agent_key`：不存在/已停用 → 拒绝路由到执行 | 异常 | P0 | 去掉存在性/启用校验 → 必须红 |
| 9 | 容器负向：`--network none` 真断网、只读根真只读、非 root、看不到 PG/**Valkey**/**SeaweedFS**〔2026-09-13 组件名同步〕 | 边界 | P0 | 与前置清单 B4 共用同一组判据 |
| 10 | 回滚开关：默认 `mock` 下全量全绿；显式设 `dsh` 而**故意缺一项剖面断言** → 必须红 | 正常 | P1 | 见 §3.6；原稿「必须红的方式」为空，无法与「从未启用 dsh」区分 |
| 11 | **路径黑名单（C 类）**：读 `.env` / `~/.ssh/id_rsa` / `/etc/shadow` / `/proc/self/environ` / **`/proc/self/maps`** / **`/sys/**`** → 拒绝 | 异常 | P0 | 去掉 C 类路径判定 → 必须红 |
| 12 | **§3.2.1 锁定值**：`python app.py`（Q1，经 A12 落实）、管道组合（Q3）、`grep`（Q2 不在最小只读集）→ 全部拒绝 | 异常 | P0 | 放开任一锁定值 → 必须红 |
| 13 | **授权绑定参数**（评审 B2）：批准「写 A」后把参数改为 B（两者都在允许目录、都不在黑名单）→ 必须 `409` | 异常 | P0 | 去掉参数摘要比对 → 必须红 |
| 14 | **执行幂等与缺键语义**（评审 B5；第三轮按裁决 R6 补 ②）：① **同一 `Idempotency-Key` 重放** → 只 1 条消息、只 1 个承载任务、只 1 个运行、不二次执行，且返回首次结果；② **不带键** → 响应 `stub=true`，**不新增承载任务、不新增运行、不产生任何真实副作用** | 正常 | P0 | 去掉幂等判定 → 必须红；把「缺键」当作「幂等关闭后照常真实执行」→ 必须红。**原稿用 `message_id` 不可测**：其值由 `append_message` 每次 `uuid4` 新建，重放拿不到相同值 |
| 15 | **可执行文件来源**（评审 B3）：允许名 + 工作卷内同名 shebang 脚本 → 拒绝；工作卷 `noexec` 生效 | 异常 | P0 | 去掉 ④-0 → 必须红 |
| 16 | **审批后不得跳过闸门**（评审 B4 / P7）：对执行器打桩，断言审批通过后的执行**确实重新经过 ①–④**——观测点 = 打桩记录的**闸门调用序列/计数**（§4.1.6 第 6 条的判定留痕），且 ④ 命中时审计出现 `tool.blocked` | 异常 | P0 | 把「重跑」改成「从 ⑦ 直接续跑」→ 必须红（此时 ②③④ 的调用计数为 0）。原稿的「审计中重现判定记录」缺落点（②③④ 通过路径无留痕定义），已按 §4.1.6-6 补齐 |
| 17 | **容器加固**：`no-new-privileges`、工作卷 `nosuid,nodev,noexec`、镜像 **digest** 一致、超时后**孤儿容器被回收** | 边界 | P0 | 任一项关掉 → 对应断言必须红 |
| 18 | **同步硬上限**：超时 → 拒绝并**真的终止容器**（真跑，不得只做静态检查） | 边界 | P0 | 去掉终止步骤 → 必须红 |
| 19 | **工具目录与定档**：目录中不得存在未定档工具；`artifact.export` 必须为 `critical` 且 `requires_approval` | 正常 | P1 | 改坏定档（如把导出降为 `low`）→ 必须红 |
| 20 | **审计**：`reason` 写入自由文本 → 必须红；`GET /api/v1/audits?action=tool.executed` 可用（漏扩 `AuditAction` → 422） | 正常 | P1 | 漏扩动作码或白名单 → 必须红（评审 M2/M3/G5） |
| 21 | **沙箱升级通道**（清单自认最高优先级待验项）：`bash`/`write`/`edit` 的 `sandbox_permissions` 升级请求 → 必须**被拒或不挂起** | 异常 | P0 | **通过判据 = 附真实调用的原始报文**（证明被拒或不挂起）；**未取证即视为未通过**（不是"无法判定"），由段二-1 收口（重审澄清） |
| 22 | **逐项授权**（第二轮新增）：一个运行内有 2 个需审批动作，只批准其中 1 个 → **未批准的那个不得执行** | 异常 | P0 | 去掉逐项校验（回退为整单授权）→ 必须红 |
| 23 | **待批动作持久化**（第二轮新增）：⑥ 落库失败 → **不得进入等待**；落库成功 → 审批决议端点可从迁移 `027` 取回**冻结的动作与参数** | 边界 | P0 | 去掉 `027` 落点、或改为从内存/事件取 → 必须红 |
| 24 | **`dsh-subprocess-local` 已禁用**（第二轮新增）：启动期断言禁用清单含它**与 `dsh-session-telemetry-otel`（2026-09-13 补 D-A）**；尝试经子进程起命令 → 被拒 | 异常 | P0 | 从禁用清单移除 → 必须红 |
| 25 | **导出侧校验**（第二轮新增）：`artifact.export` 的**类型白名单 / 大小上限 / 数量上限 / 内容嗅探 / 命名净化** → 逐项拒绝非法输入 | 异常 | P0 | 关掉任一项 → 对应断言必须红 |
| 26 | **导出归属**（第三轮新增，评审 R3-5）：`artifact.export` 以**他人租户 / 越权对象**为 `target`，或 `path`/`target` 指向非本租户受控范围 → 拒绝（`403`/`404`，不泄露存在性）并记审计 | 异常 | P0 | 去掉归属校验 → 必须红 |
| 27 | **前端动作标签同步**（第三轮新增，评审 P4）：扩 `AuditAction` 后 `tests/test_frontend_audit_labels.py` 必须绿——`admin-web/src/features/auditLog/types.ts` 的标签表须与后端动作码全集相等 | 正常 | P1 | 漏同步前端标签项 → 必须红 |
| 28 | **参数规范化判据**（**R5-3 新增**）：逐条断言 §4.1.4 的等价性口径——`{"a":1,"b":2}` vs `{"b":2,"a":1}` → **相同**；`{"a":1}` vs `{"a":1.0}` → **不同**（类型不同）；**`{"a":1.0}` vs `{"a":1.00}` → 相同**；`{"a":null}` vs `{}` → **不同**（缺键 ≠ null）；路径参数 `a//b` vs `a/b` → **相同**；路径参数 `A` vs `a` → **不同**；同一输入重复调用 → **稳定** | 正常 | P1 | 改坏任一条归一规则 → 对应断言必须红。**原判据误挂在用例 13**（§4.1.4 已改指向本条：用例 13 断言的是"授权绑定参数"，与本条断言对象不同） |
| 29 **【✅ 已实现·2026-09-13，见 §8 U18】** | **`actions` 缺省语义 + `ToolAction`（实现名 `AuthorizationAction`）字段**（**R5-4 新增**）：① `actions` 缺省且在「⑤ 判定无需审批」路径 → **只退化为运行级摘要比对**；**〔2026-09-13 用户裁决：原「该路径不得触达 ⑧」作废，该路径完成 ②③④ 后进入 ⑧〕**（打桩断言：执行器**被调用一次**，且 ②③④ 的判定留痕存在）；② `actions` 缺省却处于需审批路径 → **必须 `409`**；③ `ToolAction` 8 字段**逐个非空**，`args_digest` 与 §4.1.4 算法一致，且**投影中不含参数原文与 `args_json`** | 边界 | P0 | 把缺省实现为 `run_records is None → return`（fail-open）→ 必须红（§3.2 明令禁止）；把缺省当作「跳过 ⑥⑦ 直接执行」的开关 → 必须红 |
| 30 | **装配三断言**（**R5-4 新增**）：`WORKBENCH_AGENT_RUNTIME_BACKEND=dsh` 时 `tool_execution` / `run_records` / `tool_actions` **任一为 `None`** → **拒绝启用真实执行并告警（记 `error`）**，且**不拒绝整个服务进程启动**；`=mock` 时 `tool_execution` **必须为 `None`** | 异常 | P0 | 去掉任一断言 → 必须红；改成「拒绝进程启动」→ 与 §3.5/§3.6 口径不符，同样必须红 |
| 31 | **决议端点 `execution` 响应体**（**R5-4 新增**）：`POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval` 在既有字段之上返回 `execution: {outcome, code?, message_id?}`（`outcome ∈ executed / pending_approval / rejected / failed`）；**既有字段不变**；**不得返回**工具参数原文、宿主路径、凭据 | 正常 | P1 | 删掉 `execution` 或让既有字段漂移 → 必须红；响应体出现参数原文/宿主路径 → 必须红 |
| 32 | **受控正文密文与 TTL**（**J7 = 丙案，2026-09-13 新增**；**Q1 条款引用：§3.4 唯一受控例外（约束 1–5）/ §4.1.1 边界第 2–5 条与 `body_check` / §4.1.5 清理策略 / §4.1.6-8 `expired` 执行方**）：① 需审批**且含 `body`** 的动作 ⑥ 落库后 `body_ciphertext` **非空**、`body_expires_at` = **该动作的审批超时时刻**；② **`body_ciphertext` 不是明文**（**P7 改为可执行口径**——`BYTEA` 列**不能直接 grep 明文**，第七轮复核指出原口径**可能假绿**）：**三项须同时成立**——(a) 取 `encode(body_ciphertext,'hex')`，断言**不包含**正文原文 UTF-8 字节的 hex 子串；(b) 断言 `octet_length(body_ciphertext) ≥ 正文字节数 + 28`——**28 = AES-256-GCM 的 12B nonce + 16B tag（Q2 定死，来源见 §3.4 约束 1）**；下界不成立即说明**未按定死算法加密**；(c) **逐通道检索正文原文 → 均不得命中**（**Q2 补可执行方式**）：**(c1) 库内三处用 SQL 查询**（**R2 补：须按列类型判定**）——① `workbench_tool_actions.args_json`（**JSONB** → **必须 `args_json::text`**）；② **`workbench_audit_log.detail`**（**JSONB** → **必须 `detail::text`**；**审计表名已点名 = `workbench_audit_log`**）；③ `workbench_conversation_messages.content`（**TEXT** → **可直接判定**）；均以 `LIKE` / `position()` 判正文原文（或其 hex）——**PostgreSQL 对 JSONB 无 `LIKE`/`position()` 隐式转换，漏 `::text` 会直接报错**；**不得**用文件级 grep 代替；**(c2) 日志**——对 `WORKBENCH` 服务的运行日志与 `app/` 输出的日志文件逐一 grep 正文原文，**具体路径须在验收记录中写明**（随实现的日志配置确定）；③ **审批落定（approved / rejected / expired）后，同一事务内 `body_ciphertext` 与 `body_expires_at` 均被清空**（两列同时为 `NULL`）；④ **审批未落定 → 到期由清理任务清空**，并产出「已清理/清理失败」计数与告警（不新增动作码、不落正文）；⑤ **未进入审批等待的动作**（无需审批 / 同请求内完成）`body_ciphertext` **必为 `NULL`**；⑥ `args_json` 中 `body` 参数**为占位常量** `"«body»"`，且该占位**不参与任何比较/重建**；⑦ `body_check` 生效：构造「有密文无 TTL」与「有 TTL 无密文」两种写入 → **均被库拒绝**（**P7：在隔离测试库直连写入**，不经应用层；**不得在生产库执行**） | 边界 | P0 | 把**明文**写进 `body_ciphertext` → 必须红；去掉「落定即清」或「到期即清」→ 必须红；把「无需审批」的动作用密文列承载 → 必须红；删掉 `body_check` → 必须红；**改成"只追加 nonce+tag 而不加密"（明文可见）→ 必须红**；**把长度下界改小（如 `+28` → `+8`）或换成无 tag 的算法 → 必须红**；**让占位常量 `"«body»"` 参与比较/重建 → 必须红**；**(c1) 把正文写进 `args_json` / 消息表 / 审计明细 → 必须红** |
| 33 | **正文不进入任何对外通道**（**J7 = 丙案，2026-09-13 新增**；**Q1 条款引用：§3.4 约束 1 / 3 / 4 与审计明细最小集 / §4.1.3（幂等表不落正文）/ 契约「审计与落库口径」**）：① `tool.executed` / `tool.blocked` 审计明细**不含**正文，也**不含** `args_digest`；② 决议端点响应体、`201` / `202` 响应体**不含**正文、密文、宿主路径、凭据；③ **`artifact.export` 的导出通道不得携带流程密文**（导出内容与审批密文列无关）；④ 日志中 grep 不到正文与密文 | 异常 | P0 | 把正文或密文写进审计/日志/响应体 → 必须红；导出物中出现流程密文 → 必须红 |
| 34 | **`param_roles` 全覆盖断言**（**P1 新增，2026-09-13**）：构造「`ToolSpecCatalog` 中**任一参数未声明 `param_roles`**」→ **启动期断言拒绝启用真实执行并告警（记 `error`）**，且**不拒绝整个服务进程启动**；反向断言：8 个工具的**每个参数都已在 §3.1.1 显式标注** | 异常 | P0 | 把未声明参数当作"默认 `control`"放行 → 必须红（该 fail-open 口径已作废）；去掉该断言 → 必须红 |
| 35 | **短期令牌的绑定强制与恒时比对**（**2026-09-13 用户裁决新增**；**条款引用：§3.5 P1 第 3 条的「② 与 ④ 的校验点」注**）：**校验点 ＝ 工作台控制面** —— **执行侧回调工作台**（`artifact.export` 导出 / 请求授权）时，工作台按令牌**反查**其 `(tenant, session, generation)` 并与**当前执行**比对（**constant-time**）。① **令牌与当前执行不匹配**（为 run-A 签发、却用于 run-B 的回调）→ **拒绝**（`403`，不泄露存在性）并记审计；② **跨租户**（令牌租户 ≠ 目标租户）→ **拒绝**；③ **代次不匹配**（同会话旧代次令牌）→ **拒绝**；④ **反向**：完全匹配 → **放行**；⑤ **容器侧伪造绑定声明无效果**（服务端只以自己的权威记录为准，**不读容器声明**）；⑥ **网关数据面不做绑定**（不得在网关加绑定校验，也不得把网关侧 `bound` 当作安全边界）—— 现状实测见前置清单 §B14 F 行与 `_dsh-gateway-verify\out\30-binding-gw.log` | 异常 | P0 | 去掉反查或比对 → 必须红；把 ①–③ 任一情形放行 → 必须红；**把恒时比对换成短路比较**（用「先比长度、再逐字节提前返回」的替身实现）→ 必须红（**④ 以「调用 constant-time 原语」为判据，不以计时为判据**）；把校验点挪到**网关数据面** → 与 §3.5 P1 口径不符，同样必须红 |

**反假测试纪律**：标「必须红」的每条都要**真的改坏跑一遍确认变红**再还原，并把结果写进汇报。

---

## 6. 验收标准

| 类别 | 要求 |
| --- | --- |
| **风险分级** | 本段属 **P0（权限/资金相邻）+ P1（数据）**：§5 各用例已标级别，**P0 每次必测**，三类用例（正常 / 临界 / 异常非法）全覆盖 |
| **正常流程** | 必须**查库/查审计验证**，不只看接口返回；给出「一次真实执行」的完整证据链（闸门各步 + 审计 + 摘要） |
| **临界值** | 四档风险 × 三档自治的组合；超时边界；资源上限边界；空/超大参数 |
| **异常与非法输入** | 路径逃逸（`..`、符号链接、硬链接）、黑名单命令、包装器间接命令、工作卷同名可执行文件、伪造参数、未知字段、跨租户、`agent_key` 非法、容器逃逸尝试（挂 `docker.sock`、`--privileged`）、**`artifact.export` 跨租户/越权导出（用例 26）**、**无 `Idempotency-Key` 时的行为（用例 14②）**、**短期令牌绑定不匹配 / 跨租户 / 旧代次 / 容器伪造绑定声明（用例 35）** |
| **前端四态与标签** | 对话页触发真实执行后，**加载 / 空 / 错误 / 无权限**四态齐备（含新增状态：`202` pending / `504` 超时 / `403` 工具被拦 / 幂等重放的归属）并纳入验收；**扩 `AuditAction` 后 `tests/test_frontend_audit_labels.py` 必须绿**（用例 27，评审 P4） |
| **合规交付物** | 许可证核对结论 + `THIRD-PARTY-NOTICES`（§4；**「逐包比对正文」未完成部分须如实标注，见 §8 U13**）；**真源三件套之「功能清单」= `docs/feature-inventory.md`**（裁决 R8） |
| **迁移交付** | `027` 设计（§4.1）落地为 `migrations/027_*.sql` 且**可重复执行**；补静态契约测试；`.env.staging.example` 迁移清单同步登记（漏登则 staging 预检 `blocked`）；对既有表 `workbench_run_records` 的约束变更进变更记录（宪法 1.4） |
| **聚合命令** | **一条命令**跑完全部（等价 CI 四个 job），落点 = `scripts/verify_all.py`（跨平台，本机与 CI 共用）；汇报须给出该命令与存档路径 |
| **清理纪律** | 段二-2 的一次性**假执行器/测试桩**须列清单、**经用户确认后删除**，删完重跑正式测试（评审附录 C#13） |
| **验收分离** | 各子段验收由**只读独立方**执行（只许看与给结论），产出证据形式固定（评审附录 C#14） |

**受影响既有测试的回归登记（第四轮修订 R4-13）**——实现前须逐项确认「扩 / 改 / 新增」，避免新增变更**静默打断既有守护**：

| 受影响面 | 既有守护 / 用例 | 预期动作 |
| --- | --- | --- |
| 扩 `AuditAction`（`tool.executed` / `tool.blocked`） | `tests/test_frontend_audit_labels.py`（前后端动作码**全集相等**） | **必须同步** `admin-web/src/features/auditLog/types.ts` 的标签表（否则必红） |
| 扩 `ALLOWED_DETAIL_KEYS`（`tool_key` / `risk_level`） | `tests/test_audit_models.py` | 扩守护；并**新增**一条「既有 5 处 `reason` 自由文本写入不被误伤」的正向用例 |
| `agent_key` 收紧（执行入口 `422`） | `tests/test_conversation_api.py`；`admin-web/src/features/conversation/state.ts`（`422` 文案） | 确认既有对话用例仍绿；**修正前端 `422` 文案**（原固定映射为"消息内容不符合要求"，第三轮 P15 未闭环） |
| `ensure_execution_authorized` 收窄 fail-open | 段一既有用例 | 确认「缺省旧行为」下段一全绿；**新增**断言「装配 dsh 时 `run_records` 必非 `None`」 |
| 对话端点新增 `Idempotency-Key` 与 `202` 体 | `admin-web` / `companion-pwa` 的解析路径 | 新增「客户端解析未知字段不报错」的用例 |
| 新增迁移 `027` + 对既有表 `UNIQUE` 增补 | `tests/test_staging_assets.py`（模板与 `migrations/*.sql` **逐条相等**）、`tests/test_persistence_contract.py` | `027` 落地时**必须同步** `.env.staging.example` 迁移清单（漏登则 staging 预检**永久 `blocked`**）；补 `027` 的静态契约测试（**须点名断言两张新表的全部列与 3 个 CHECK**，含 `args_json` / `body_ciphertext` / `body_expires_at` / `http_status` / `approval_id` 与 `body_check` / `result_check`） |
| **决议端点新增 `execution` 字段**（§4.1.6-7 / 用例 31，**第六轮 J-9 被点名补入**） | 既有决议端点用例（文件名以仓库为准）与 `admin-web` / `companion-pwa` 的审批卡解析路径 | 确认既有决议端点用例仍绿；**新增**「客户端解析未知字段 `execution` 不报错」；**既有字段不得漂移** |
| 新增 **19 项**配置（2026-09-13 更新：原 12 项 + **路径①「模型网关」六项** + **⑥ 孤儿上限 `WORKBENCH_EXEC_ORPHAN_LIMIT`**） | `tests/test_env_templates.py` | 扩该守护测试至覆盖全部新增项（见前置清单 §B15，**须同步改为 19 项**） |
| 聚合命令 | 无（`scripts/verify_all.py` 尚不存在） | 本段新增 |

**报告要求**：五类现象实例（正常 / 参数错误 / 未登录 / 无权限 / 访问他人数据）+ 数据与审计前后变化；**没验证的必须写「未验证」**。

**端到端**：容器负向回归**必须真跑**（`--network none` 下联网失败等）；不得只做静态检查。

**全量回归**：须有**一条聚合命令**跑完全部（等价 CI 四个 job：`pytest` + `compileall` + 管理台 vitest/build + 伴侣端 vitest/build + 桌面 `node --test`）。仓库现无该聚合脚本 → **本段须新增**，并在汇报中给出命令与存档路径（评审附录 C#10）。

---

## 7. 待确认 → 决议记录（2026-09-12 用户逐项答复）

| # | 问题 | 决议 / 状态 |
| --- | --- | --- |
| **X1** | §1.4 的子段划分是否采纳？ | **已定（采纳）**：段二拆为段二-1~4；D20 措辞已同步追加该决议，P2a-2 交付表已指向四个子段 |
| **X2** | 危险命令黑名单**具体条目** | **已定（2026-09-12）**：写入 §3.2.1（R1–R4、A1–A12、B、C 三层与 Q1–Q4 锁定值）；本轮按评审补强 A11 包装器、A12 裸解释器、参数形态与路径族、C 类匹配算法 |
| **X3** | A2 的**成本安排**（生产分主机） | **已定（接受分主机）**：维持 §3.3 生产分主机硬约束；开发期允许本机 Docker（仅验证机制） |
| **X4** | 单轮预算（前置清单 B12）本段做不做？ | **已定（本段不做）**：已写入 §1.2 第 6 条；成本三级熔断完整口径属 P6 |
| **X5** | 是否需要「工具调用记录表」？ | **已定（不建工具调用记录表）**：工具调用走既有 append-only 审计。**迁移口径已更正（第三轮）**：由「无新迁移」改为「**新增迁移 `027`**」（2026-09-12 裁决 R1）——`027` 承载**待批动作 + 逐项授权项**（执行闸门所需），**不是**工具调用记录表，两条并不矛盾（原表述互斥，第三轮评审 R3-2 指出后更正） |
| **Y1–Y3** | 工具目录端点 / 运行归属 / 审计明细 | **已定（2026-09-12）**：见 §3.7；Y2 的 `origin` 要求经首轮评审后**撤销** |
| **P1** | dsh 进程位置与模型凭据来源 | **已定口径（2026-09-13 裁决路径①「自建模型网关」）**：供应商密钥只在容器外网关、容器内仅短期令牌；网络面改「仅内网桥 + 仅网关可达」；**判据 C 作废、改 C′**（§3.5）。**B14 判据 A/B/E/F 与 C′ 仍待真实 turn 取证** |
| **P2** | 执行同步 vs 后台化 | **已定（保持同步 + 单次执行硬上限）**；并发/排队属 P2b |
| **LGPL** | 许可证与 `THIRD-PARTY-NOTICES` | **已定（纳入本段交付物）**：逐包核对（已完成）→ **保留 `sharp`**；**⚠️ 决议算术已于 2026-09-13 更正（D-B，门禁 §F7.4）**：Linux 实测随镜像 `@img/*` **4 个**、**含 LGPL 2 条**（原写"共 2 个、LGPL 仅 1 个"**与实测不符**）→ `THIRD-PARTY-NOTICES` **须含 2 条 LGPL**；"删除 `@img/sharp-wasm32` 降回 1 条"列为**实施期实测项** |
| **R1** | 重审：B2/B4 的落点（参数摘要 + 审批后重跑） | **已定（2026-09-12 第二轮）：新增迁移 `027`**（授权项 + 待批动作持久化）→ 支持**逐项授权**；**推翻此前的「无新迁移」口径**，属地基变更须随本规格专项评审 |
| **R2** | 重审：执行幂等键载体 | **已定：请求头 `Idempotency-Key`**（按 `(tenant, 操作者, 会话, 键)` 唯一，命中返回既有结果）；**原 `message_id` 方案实测不可行**（每次 append 新建） |
| **R3** | 重审：`dsh-subprocess-local` 处置 | **已定：显式禁用**（与 `tool-bash` 同等；否则模型可自起子进程，④ 系列闸门被整体绕过） |
| **R4** | 重审：`restrict` 空交集的作用域 | **已定：只禁「真实执行」并告警，不拒绝服务进程启动**（`tool_allowlist` 默认 `[]`，否则一处配置即打挂服务） |
| **R5** | 第三轮：`027` 的完整 DDL 只存在于未被引用的草稿 | **已定（2026-09-13）：并入规格**——草稿 §1–§5 作为本规格 **§4.1 附录**写入（含两份 DDL、对既有表 `workbench_run_records` 的 `UNIQUE (run_id, tenant_id)` 增补、参数规范化算法、装配与失败语义表）；草稿文件保留并标注「已并入 §4.1，转归档」 |
| **R6** | 第三轮：`Idempotency-Key` 的必填性与缺省语义 | **已定：请求头可选；缺键 ⇒ 不触发真实执行**（沿用既有 `stub=true`，不创建承载任务与运行）；带键 ⇒ 真实执行 + 幂等（§3.2） |
| **R7** | 第三轮：`026` 与 `027` 谁是授权权威 | **已定：`027` 为唯一授权权威**；`026` 保留、不删、不回填，降级为「运行级授权快照」；`decide_approval` 同事务写 `027` 状态 + `026` 快照 + 适配器决议（§3.2） |
| **R8** | 第三轮：宪法 2.1「功能清单」怎么落 | **已定：另建独立《功能清单》文档**（`docs/feature-inventory.md`，按宪法 2.1 六要素逐项写）——**推翻 2026-09-12 的「不另建文档、以立项 §14.1 充当」裁决**；本规格头部与门禁清单显式引用 |

> **X1–X5、Y1–Y3、P1–P2、LGPL、R1–R4 已全部闭环**（2026-09-12）；**第三轮裁决 R5–R8 亦已闭环**（2026-09-13，见上表与 §9.2）。段二能否开工，取决于前置清单 [§B 开工前置与 §C 文档前置](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-preflight-checklist.md)，不再取决于本规格的决策项。

---

## 8. 风险与未覆盖（如实登记）

1. **🔴 本段是本立项风险最高的部分**（D8 路线 A + 文件/命令 + 容器）。任何「先跑起来再补闸门」的做法都不可接受：**闸门先于执行器**。
2. **dsh 是 RC**：一个月 22 个版本、三代会话格式迁移、**无 `engines`**、子包版本已混用。必须靠「精确版本 + 适配器隔离 + 可关回 mock」三件套控住，不能指望上游稳定。
3. **沙箱不是安全边界**（§15 #2）：Linux 侧结论未知（前置清单 B3 ④）；即使结论是 ✅，也不改变本段的边界设计（主机边界 + 最小挂载 + 无长寿命凭据）。
4. **审批交互在段二仍是非流式的**：⑧ 步执行期间没有流式反馈（P2b 才有），用户可能面对「等一会儿才出结果」的体验；本段以**单次执行硬上限**兜住时长风险。
5. **本段不解决**：技能市场投毒（P4）、记忆与画像（P3）、单轮预算与成本熔断（X4 **已定：本段不做**，完整口径属 P6，见 §1.2 第 6 条）。
6. **本文件不构成任何实现完成的声明**：段二**尚未开始编码**，且**前置清单未过闸**。

**本轮新增的「待核实」清单（不得当作已解决）**：

| # | 待核实项 | 收口方式 |
| --- | --- | --- |
| U1 | **dsh 进程位置与模型凭据来源**（P1） | 段二-1 用真实凭据实测回填（§3.5）；**取证模板见前置清单 [§B14](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-preflight-checklist.md)（四条同时成立判据 + 3 条统一红线）与 [OpenMausBot 研读报告 §6](file:///d:/徐徐AI学习/公司工作台/docs/openmausbot-source-study-and-adaptation-plan.md)（7 条现象→判据→成立/不成立边界）**。**进展（2026-09-13）**：**判据 A / C′ 已取得成立证据**（供应商域名出站连接由**网关容器**发起；执行容器全程只有一条到网关的连接、不可达供应商域名；网关停机后 turn 以 `code=TRANSPORT` 指向网关失败）〔**2026-09-13 复核更正：两条结论成立但各有局限 —— A 缺宿主侧抓包、C′ 靠轮询采样可能漏短连接，见下行**〕；**容器内无供应商密钥明文**（文件 / env / `/proc/*/environ` 三口径全 0）；~~**短期令牌可终态吊销**~~〔🔴 **2026-09-13 复核更正：`REVOKE` / `DENY reason=unknown-token` 在 `out\` 内**无任何归档证据**，不得视为已实测**〕（见前置清单 **§F9**）。**但供应商凭据实测 401（同密钥直连上游同样 401）⇒「**真实供应商**调用成功」未取证**。**2026-09-13 补充（§F12 桩上游 + §F13 真实供应商）**：先以**本地桩上游**取得**成功态**，随后用同一脚本把上游换成 `https://api.deepseek.com` **复跑并同样成立** —— **判据 B 的因果**（宿主凭据存在 → 真实 `UPSTREAM-RES 200` → turn `kind=completed`；**清空 → 401 → 立即失败 `code=AUTH`**）与 **红线 1 未命中**均已取证；**原"仅存两项限定"的现状（2026-09-13 更新）** ＝ **容器形态已加固**（门禁 §B17 **已于同日闭环、解除「阻断上线」**，残留「镜像层未测」挂住）与 **F 的 ②④⑤⑥**（⑤ 已取证＝结论「未实现」、⑥ 口径已定并实现；**②④ 仍缺工作台控制面的强制校验**，§8 U17）。**判据 D / E 已按路径①重述**（§F9.3 与评审记录 §24）。**逐条状态以 [前置清单 §B14「当前取证状态」块](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-preflight-checklist.md) 为准（2026-09-13 经主视角 + 独立只读视角两轮复核原始日志；**初版 2 处硬错误已由复核纠正**）**：**A / C′ / D 的结论成立（各有局限：A 缺宿主侧抓包；C′ 靠轮询采样、可能漏短连接；D 各轮令牌长度 43/29/21，后两者来源未留证）；B 结构 ✅ / **因果 ✅（§F12 桩 + §F13 真实供应商）**；E / G 部分；F 仅 2/6 有条目证据（②绑定未强制、④`constant-time` 与 ⑥孤儿上限未实现、⑤吊销无归档证据）；**红线 1 未命中（§F12 桩 + §F13 真实供应商）、红线 2 / 3 未命中（但红线 3 的"镜像层"一项根本没测）**。⚠️ **本次实验形态不代表生产形态**（容器实测 `CapDrop`/`SecurityOpt` 为 `null`、`PidsLimit`/`Memory`/`NanoCpus` 为 `null`/0/0、**以 root 运行**、dsh 由**宿主 bind mount** 提供）⇒ **不得外推到 §4/§B15 所述加固口径**；**该形态缺口已单列为前置清单门禁 §B17「加固口径下的复跑」—— 已于 2026-09-13 闭环（加固容器内真实 turn 复跑、判据 3 = 一致），解除「阻断上线」；残留「镜像层未测」挂住**。⚠️ 同日前置清单中曾有 4 处「B14 全未取证」的表述（§F6 表 / §F7.5 / §F8.5 / §F8.6），**均系 §F9 执行前的陈旧口径，已就地加更正注** |
| U2 | **TOCTOU / 硬链接**绕过是否真被「原子化 + 不同设备」堵住 | 写用例 + 实验验证（§3.2.1 局限 6） |
| U3 | Linux 侧沙箱结论（`windows-acl: partial` 之外的 Linux 行为） | 前置清单 B3 ④ 复验 |
| U4 | `@deepseek-ai/*` **精确计数**与各子包版本线 | lockfile **不在本仓库内**，以清单实测原始输出为准（§2.3） |
| U5 | dsh 协议「三请求 + 四通知」枚举 | 需附**原始协议报文**，否则标待核实（§2.1） |
| U6 | **单会话最大轮次**上限由谁承担（宪法 4.9） | 本段未覆盖，需明确承担方或登记为不覆盖 |
| U7 | 模型 / dsh 调用的**重试上限与单次失败降级**口径 | 本段给了整体开关与超时，单次降级未定 → 需补口径。**实测补充（2026-09-13，前置清单 §F9.4）**：**`dsh-llm-retry` 在传输失败时会自行重试**（网关停机场景实测 **5 次 `llm/retry`** 后 turn 才结束）⇒ 与 §4 新增的 **`WORKBENCH_MODEL_GATEWAY_MAX_RETRIES`（默认 `0`）叠加会造成重试放大** → **「重试归口」须定死**（建议：**容器内不重试、重试只在网关**，与 §3.5 P1 第 4 条一致——**但尚待裁决，本条未定**） |
| U8 | 前端「管理台 147 / 伴侣端 37 / 桌面 19」用例数 | 文档原值，本轮未复核 |
| U9 | ~~真源三件套中的「功能清单」是否齐备~~ → **已闭环（2026-09-13 裁决 R8）** | 首轮评审附录 C#18 提出、重审指出漏登 → **本轮另建独立《功能清单》`docs/feature-inventory.md`**（宪法 2.1 六要素），**推翻** 2026-09-12「以立项 §14.1 充当、不另建文档」的裁决；原裁决自本决议起失效 |
| U10 | **`restrict` 的运行期拦截效果**（清单 §F3 自认「仍未取到」） | §3.5 的「第二道防线」与空交集口径均建立其上 → 段二-1 用真实模型驱动取证，取证前**不得**视为已成立 |
| U11 | ✅ **已定值（2026-09-13 用户裁决）= `180` 秒** —— **`WORKBENCH_EXEC_TIMEOUT_SECONDS` 的默认值**（同步执行硬上限的具体数值） | **定值 `180`**（≈ 冷启动上限 79s 的 2.3×），已进 `app/settings.py` / `.env.staging.example`，由 `tests/test_env_templates.py::test_stage2_defaults_are_pinned` 钉死（含反假测试）。**同批定值**：`EXEC_PIDS_LIMIT=256` / `EXEC_MEMORY_MB=2048` / `EXEC_CPU_QUOTA=2.0` / `BODY_CLEANUP_INTERVAL_SECONDS=60` / `MODEL_GATEWAY_TOKEN_TTL_SECONDS=300` / `MODEL_GATEWAY_UPSTREAM_TIMEOUT_SECONDS=60`。以下为原登记口径与实测约束。**实测约束（2026-09-13，前置清单 §F9.4）**：**`dsh --profile sdk` 的 `initialize` 冷启动实测 52–79s**（两次分别为 53.2s / 78.9s，来自 `transport.onRequest` 首次 `await ctx.get("loader")?.await()`）⇒ **默认值必须覆盖冷启动**，否则会把"初始化慢"**误判为执行超时**；**是否给冷启动另设独立预算**亦待定 |
| U12 | **幂等表的保留/清理策略**（本段明确不做、无 TTL，见 §4.1.5） | 保留策略属后续段次；当前口径已登记于 §4.1.5。**注（J7 = 丙案，2026-09-13）**：**受控正文密文列的 TTL 清理不属本项**——它已定为**本段必做**（见 §4.1.5 第 2 行与 §3.4 例外第 2 条） |
| U13 | **许可证「逐包比对正文」是否完成**（清单 §F5 自认未逐包比对 583 条目、`THIRD-PARTY-NOTICES` 未产出、镜像内二次扫描未做） | 段二-1 收口；**完成前 §4 不得表述为"逐包核对已完成"**，只可写"按 lockfile 声明值统计已完成，正文比对属未完成" |
| U14 | **`args_json` 的单行上限**（是否需在库层加长度约束；`control` 参数的合理上限） | 第五轮 R5-1 新增（甲案引入该列）→ 段二-1 实测后定值；见 §4.1.1 边界第 6 条 |
| U15 | **丙案机制的落地**（受控正文密文列 + `param_roles` 声明字段） | **文档层已实施（第七轮补丁后更完整：新增 `BodyCipher` 组件落点、`WORKBENCH_BODY_ENCRYPTION_KEY`/清理周期两项配置、加解密失败语义、密钥轮换窗口、`expired` 执行方、用例 32–34）**。**仍未做**：`migrations/027` 未落地、**加解密实现与密钥管理未实现**、**TTL 清理任务未实现**、**无任何实现或测试** → 实现前**不得视为可用** |
| U16 | ✅ **已定值（2026-09-13 用户裁决）= `60` 秒** —— **`WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 的默认值**（P3 新增配置） | **定值 `60`**，已进 `app/settings.py` / `.env.staging.example`，由 `test_stage2_defaults_are_pinned` 钉死；亦决定 P4 的密钥轮换窗口长度。原登记口径：第七轮补丁新增该项但**未定默认值**（同 U11 的性质）→ **实现前须定死数值并进模板与守护测试** |
| U17 | **短期令牌 ⑤「终态同步吊销」与 ⑥「孤儿上限」的口径与用例**（2026-09-13 新增） | **②④ 的校验点已裁决**（＝工作台控制面，见 §3.5 P1 第 3 条）且已补 **§5 用例 35**。**⑥ 口径已于 2026-09-13 用户裁决（保守 fail-closed）**：① **上限 = 独立配置项，默认 `8`**（拟名 `WORKBENCH_EXEC_ORPHAN_LIMIT`；⚠️ **须同步进三处台账** —— `app/settings.py`、`.env.staging.example`、`tests/test_env_templates.py` 的 `STAGE2_SETTINGS_FIELDS` ⇒ **段二配置项由 18 变 19，B15 / 门禁 §B15 的项数须同批更新**，否则 `test_stage2_settings_are_declared` 与 `test_staging_template_covers_every_stage2_setting` 必红）；**✅ 已落地（2026-09-13 段二-3）：`WORKBENCH_EXEC_ORPHAN_LIMIT` 默认 `8` 已进 `app/settings.py` / `.env.staging.example` / `STAGE2_SETTINGS_FIELDS` 三处，项数 18 → 19**；② **超限 → 拒绝新执行并告警（fail-closed）**（记 `error`，与 §4.1.6-3 同口径：不放行真实执行、**不打挂进程**）；③ **清扫时机 = 启动时 + 按 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 周期**（与 §4.1.5 的清理任务**同批**）。**⑤ 已于 2026-09-13 运行期取证，结论 =「未实现」（否证成立）**：网关原型**无任何调用方**调用其 `/__revoke` 端点（`gw.js` 无 turn / session 生命周期钩子；驱动只发 `initialize` / `session/prompt` / `shutdown`），且**实跑否证**——真实 turn 走到终态（`turn/end` + `status=idle` + `exit 0`）之后，**同一令牌复用仍返回 `UPSTREAM-RES status=200`**（晚于终态约 3 秒），网关全量日志内 **`REVOKE` 行数为 0**；**对照组**（新铸令牌 → `200`、伪造令牌 → `401`）排除"网关全拒 / 网关故障"的假象 ⇒ `REVOKE` / `DENY reason=unknown-token` 目前**确实只是 `gw.js` 的代码字面量**。**归档**（仓库外）：`_dsh-gateway-verify\out\60-revoke-A.log` / `61-revoke-B.log` / `62-revoke-gw.log` / `63-revoke-stub.log`。**未测分支**：超时 / 崩溃 / 被 kill 的终态**未取证**。**⇒ ⑤ 的实现同样落在段二-3。** **✅ ⑤ 原型闭环已完成（2026-09-13 段二-3）**：新增 `app/tool_execution/gateway_token.py`（`GatewayTokenClient` + `build_terminal_state_revoker`），并由 `ContainerExecutor.token_revoker` 在**容器终态**触发 `/__revoke`；**重跑一轮取证**证明 — 铸令牌 → 数据面 `200`（对照组）→ turn 终态吊销（网关日志 `REVOKE bound=turn-70 n=1 total=0`）→ **同一令牌复用被拒（`401` + `DENY reason=unknown-token`）** → 再铸新令牌 `200`（排除「网关全拒」假象）。**原始日志归档（仓库外）**：`_dsh-gateway-verify\out\70-revoke-driver.log` / `71-revoke-gw.log` / `72-revoke-stub.log`。🔴 **生产落点 = §F 的模型网关**（供应商域名/密钥只在网关侧；`WORKBENCH_MODEL_GATEWAY_*` 六项）——**本期只做「原型闭环 + 生产落点登记」，生产实现在 §F，不在本期范围**。**收口要求**：⑥ 的实现与 ⑤⑥ 的 §5 用例均**落在段二-3**（⑥ 已落地；⑤⑥ 的 §5 用例仍待补）；**在此之前不得声称「F 六条已被守护」。** |
| U18 | ✅ **已闭环（2026-09-13）—— §5 用例 29（P0）** | **本轮完成**：① `ensure_execution_authorized` 增 `actions` 参数并**定死缺省语义**（缺省只允许出现在「⑤ 判定无需审批」路径；**缺省 + 需审批路径 → `409`**）；② 8 字段投影落地为 **`AuthorizationAction`**（规格原称 `ToolAction`，因与 `store.py` 的 21 字段整行同名而改名，见 §4.1.7-5 命名更正）；③ 假执行器加**调用计数**（`call_count` / `calls`）；④ 补 **用例 29 ①②③ + 反假 2 组**（缺省跳过 ⑥⑦ → ② 变红；投影携带 `args_json` → ③ 变红）；⑤ **027 仓储已接线到 `RuntimeService`**（`app/main.py` 先建**单一实例**再分别传入 `build_runtime_service` 与 `build_tool_execution`；`backend=mock` 下按 §4.1.6-2 保持 `None`），反假证明「换新建实例 ⇒ 共享断言与强保护断言**双双变红**」。回归 **1534 passed, 10 skipped**。**残余未验证（登记在此，视为 U18 的附属待办）**：① **HTTP 端到端 409 未验证**（`tool_execution_service` 在 `app/main.py` 仍**未被任何路由引用**，属既有状态）；② **真实 dsh 装配未起进程验证**（测试用等价复现接线顺序覆盖）；③ **真库下同实例复用未实测**（按禁令只用 InMemory）。 |
| U19 | ✅ **已闭环（2026-09-13，用户裁决·方案 b）** | **裁决**：**在 §4.1.6-4 明确豁免**「重跑路径不做运行级比对」——重跑只做**逐行 `027` 校验**，`resume` **无需** `actor` / `plan`。**理由**：§4.1.5 / R7 已定 **`027` 为唯一授权权威**、`026` 降级为运行级快照且**不得单独作为放行依据** ⇒ 运行级比对在重跑路径**语义冗余**；且 `plan` 未持久化于 `run_records`，回查须引入新依赖。**边界**：豁免**仅限重跑路径**，**首次执行路径与 §3.2 ⑦ 不变**。**实现现状**：`resume` 签名**保持** `(run_id, approval_id)`，与本次裁决一致（无需改代码）。**原缺口描述（保留备查）**：把 `tool_execution_service` 接入决议端点时，严格照 §4.1.6-4 实现 `resume(run_id, approval_id)` —— 该签名不含 `actor`/`plan`，而运行级闸门 `ensure_execution_authorized(actor, run_id, plan, actions)` 必须有二者 ⇒ 重跑时只做逐行校验。 |

---

## 9. 评审记录与本轮修订说明（2026-09-12）

**首轮专项评审**：3 个独立只读视角（安全与闸门正确性 / 一致性与可测性 / 宪法合规与流程）+ 汇总方复核；结论**不予放行**（5 条阻断项 / 11 条重要项 / 若干建议）。**完整记录见** [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md)。

**阻断项处置（5/5 已闭环）**

| # | 阻断项 | 本轮处置位置 |
| --- | --- | --- |
| B1 | `origin=conversation` 与「零新迁移」互斥 | **撤销该要求**（用户裁决）：§1.2 第 5 条、§3.7 Y2、§4 |
| B2 | 授权位摘要不含参数 → 「批准 A 执行 B」 | §3.2 ⑦ 改为「计划摘要 **+ 参数摘要** 比对」；用例 13 |
| B3 | `basename` 判定可被工作卷内同名可执行文件绕过 | §3.2 新增 **④-0 可执行文件来源**；§3.2.1 局限 5；§3.3 工作卷 `noexec`；用例 15 |
| B4 | 审批通过后如何推进到 ⑧ 未定义 | §3.2 第二条不可协商口径（**审批通过后从 ① 重跑，禁止跳过 ②③④**）；用例 16；用例 4 观测点更正 |
| B5 | 对话端点触发真实副作用却无幂等 | §3.2 第四条不可协商口径（**`message_id` 为执行幂等键**）；用例 14 |

**重要项处置（M1–M6 / G1–G7 / P1–P2）**：M1 → 契约 ⑦ 行删除「授权来源」（契约章节同步回改）；M2 → §3.4 动作码改为**硬要求**；M3 → §4 修正守护测试覆盖范围并**要求本段扩测试**；M4 → §2.3 按实测口径更正并标待核实；M5 → §1.3/§1.4 与契约对齐 `agent_key` 落点；M6 → 头部基线更正为 1434；G1 → §3.2 ④-1（Q2 进闸门且 fail-closed）+ §3.2.1 A11；G2 → §3.2.1 R1/B/C 补参数形态、归档别名与路径族；G3 → 新增 **§3.1.1 工具清单与定档**（含 `critical` 承担工具）；G4 → §3.4 明确落库落点；G5 → §3.4 `reason` 枚举化；G6 → §3.5 `restrict` 空交集 **fail-closed**；G7 → §1.3/§1.4 `agent_key` 收紧**并入段二-3**；P1 → §3.5/§3.7/§8 U1 **待核实**；P2 → §1.2 第 7 条与 §3.3「同步 + 硬上限」。

**其它已处置建议**：容器加固（`no-new-privileges`/`nosuid,nodev,noexec`/镜像 digest/孤儿容器回收/`/dev/shm`）、路径原子性与不同设备、C 类匹配算法、R4 Linux 限定、权限来源校验归位、`reason` 枚举、工具目录附录、用例可判定性与反假构造、P0/P1 分级、聚合命令、前端四态、清理纪律、验收分离、许可证交付物。

**本轮仍未闭环（不得视为通过）**：§8 的 **U1–U11**；前置清单 §B 的 B3④ 与 B13 遗留项；§5 用例 21（沙箱升级通道真实行为）。

---

### 9.1 第二轮修订（规格重审后，2026-09-12）

**重审结论：不予放行**（3 个独立视角：A「阻断项闭合」判**不予放行**、B「一致性与可测性」判**不建议放行**、C「宪法合规」判**可放行（附条件）**；**以更严为准**）。重审记录见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md) §7。核心发现：

- **B1 真闭合**；**B2 / B4 / B5 属「表面闭合」**——规格写了、但按**现有代码**实现不了：`PlanStep` 无参数字段、迁移 `026` 只有单列摘要、`message_id` 每次 `append` 都新建、运行状态里没有「待批动作」的结构化落点。
- **本轮修订引入的新矛盾**：① `reason` 若按全局键级枚举化，会打断既有 5 处审计写入（`accounts`/`content`/`workforce`/`planner`/`orchestration`）；② 「逐项授权」与「单列摘要 + 零新迁移」互斥。①②**均已在第二轮处置**（作用域收窄 / 迁移 `027`）。
- **修订者（AI）本轮引入的 5 处事实错误已更正**：契约子段映射写反（把 G7 又装回去）、`reason` 作用域过宽、LGPL「压到 2 条」（`@img/sharp-linux-x64` 实为 Apache-2.0，不是 LGPL）、清单 §B1 残留「245 个子包」、「唯一减范围手段」绝对化。

**第二轮改动清单**：

| # | 改动 | 触发 |
| --- | --- | --- |
| 1 | **新增迁移 `027`**（授权项 + 待批动作持久化）→ 同时解决 B2（参数摘要无落点）与 B4（审批后重跑无所依），并使**逐项授权**可实现 | 重审 A/B（R1） |
| 2 | **执行幂等改为请求头 `Idempotency-Key`**（原 `message_id` 方案实测不可行）；用例 14 同步改写 | 重审 A（R2） |
| 3 | **`dsh-subprocess-local` 显式禁用**（与 `tool-bash` 同等）+ 用例 24 | 重审 A（R3） |
| 4 | **`restrict` 空交集作用域收窄**为「只禁真实执行 + 告警」，不拒绝服务进程启动 | 重审 A（R4） |
| 5 | `fs.write` **拆分**为 `fs.write`（新建）/ `fs.overwrite`（覆盖，`high`）；`ToolCatalog` 字段表补 `requires_approval` | 重审 B |
| 6 | `artifact.export` **闸门落点明确**（自建工具：③/⑤/⑦/⑨ 适用、④ 不适用、`restrict` 不覆盖）+ **导出侧校验**（类型/大小/数量/嗅探/命名） | 重审 B/C |
| 7 | Y2 承载任务**字段级口径**补齐（含 `ensure_can_create` 与 `critical` 岗位约束） | 重审 B（原 B#9 遗留） |
| 8 | §3.3 补 `--cpus`；§4 补受信任根配置项、CPU 限额、导出开关默认 `false`、**环境分开三栏**；§3.3 凭据行加「前提待核实」 | 重审 C |
| 9 | §5 用例 14/16/21 改为**可判定**，新增用例 22–25；§8 补 **U9–U11** | 重审 B/C |

**重审触发（更新）**：以上改动须再经一轮独立复核；**因 §4 已由「无新迁移」改为「新增迁移 `027`」，重审须同时确认该**地基变更**的评审是否充分**。复核通过后，本文件状态改为「已评审（附记录）」，并按清单 §C1 判据视为过闸。

---

### 9.2 第三轮修订（第三轮独立复核后，2026-09-13）

**第三轮复核结论：不予放行**（4 个独立只读视角「对抗式阻断项闭合 / 迁移 `027` 地基变更专项 / 一致性与可测性 / 宪法合规与回归」+ 汇总方亲自复核，**四视角一致**；记录见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md) §8）。核心发现：

- **R3-1 `027` 地基变更评审信息不足**：规格内只有一句职责，完整 DDL 只存在于**未被规格引用**的草稿（该文件自述「不是阶段规格、待评审」）；
- **R3-2 正文残留旧口径**：§3.4 / §3.7 Y2 / §7 X5 与 §4「新增迁移 `027`」互斥；契约 `:693` 未同步；
- **R3-3 草稿 ⊃ 规格**：对既有表 `workbench_run_records` 的 `UNIQUE` 增补与幂等新表均未进规格；
- **R3-4 B2 / B4 / B5 仍属「表面闭合」**；**R3-5 `artifact.export` 缺跨租户归属验收项**。

**用户裁决（2026-09-13）**：R5 并入规格 / R6 缺键不触发真实执行 / R7 `027` 为授权权威、`026` 降为快照 / R8 另建独立《功能清单》——见 §7 决议表与记录 §8.9。

**本轮改动清单**：

| # | 改动 | 触发 |
| --- | --- | --- |
| 1 | **新增 §4.1 迁移 `027` 设计（附录）**：两张新表 DDL、对既有表 `workbench_run_records` 的 `UNIQUE (run_id, tenant_id)` 增补、字段规范对照、参数规范化算法、主从/事务/回退/迁移工程约定、装配与失败语义（含重跑失败语义表） | R5 / R3-1 / R3-3 |
| 2 | §3.2 ⑦ 补「**`027` 为唯一授权权威；`026` 保留不删不回填、降级为运行级快照；`decide_approval` 同事务写 `027`+`026`+适配器决议**」 | R7 |
| 3 | 幂等补「**请求头可选；缺键 ⇒ 不触发真实执行（`stub=true`）**」（§3.2、§3.7 Y2、用例 14②、§4.1.3） | R6 |
| 4 | **三处旧口径清零**：§3.4「本段不新建表」、§3.7 Y2「零新迁移 / `message_id` 派生」、§7 X5「无新迁移」 | R3-2 |
| 5 | §3.6 启动断言失败处置与 §3.5 的 `restrict` 空交集口径统一（**拒绝装配真实执行并告警，不拒绝服务进程启动**） | P2 |
| 6 | §4.1.6-6 新增「⑨ 之前各步的判定留痕」；用例 16 观测点改为可判定的**打桩闸门调用序列/计数** | P7 |
| 7 | 新增 **用例 26**（`artifact.export` 跨租户归属）、**用例 27**（前端动作标签同步）；§6 补「迁移交付」「聚合命令（落点 `scripts/verify_all.py`）」「前端四态与标签」 | R3-5 / P4 / P9 |
| 8 | §4 许可证行**口径更正**（「逐包核对已完成」→ 仅按 lockfile 声明值统计完成）；§8 新增 **U12**（`027`/幂等表保留策略）、**U13**（许可证逐包正文比对未完成） | P14 |
| 9 | **U9 闭环**：另建独立《功能清单》`docs/feature-inventory.md`（宪法 2.1 六要素），**推翻** 2026-09-12「以立项 §14.1 充当、不另建文档」的原裁决 | R8 / P10 |

**本轮仍未闭环（不得视为通过）**：§8 的 **U1–U8、U10–U13**；前置清单 §B 的 B3④ 与 B13 遗留项；§5 用例 21（沙箱升级通道真实行为）；**§4.1 本附录自身尚未通过评审**。

> **重审触发（第三次更新）**：第四轮独立复核须**同时确认 §4.1 数据模型本体（地基变更）的评审是否充分**——这是第三轮被判「不充分」的直接原因。复核通过后，本文件状态方可改为「已评审（附记录）」，并按清单 §C1 判据视为过闸。

---

### 9.3 第四轮修订（第四轮独立复核后，2026-09-13）

**第四轮复核结论：不予放行**（4 个独立只读视角「`§4.1` 数据模型本体专项 / 对抗式真闭合与旧口径 / 一致性与可测性 / 宪法合规与回归」+ 汇总方亲验 4 条；A 判不予放行，B/C/D 判附条件放行——**以更严为准**）。完整记录见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md) **§9**。

**本轮改动清单（逐条对应第四轮阻断项与重要项）**：

| # | 改动 | 触发 |
| --- | --- | --- |
| 1 | §4.1 头部新增**「🔴 执行顺序」**硬要求：`027` 单文件内**先 `ALTER … ADD UNIQUE (run_id, tenant_id)`，再建两张表** | R4-1 |
| 2 | **新增 §4.1.7「待批动作的冻结与读取」**：并回归档草稿 §2——`ensure_execution_authorized(..., actions: Sequence[ToolAction])` 签名变更与旧行为退化规则、`ToolAction` 定义、调用点、缺省边界，以及「⑥ 落库失败 `503` 不进等待」「⑥ 不写 `tool.*` 审计」「执行器只执行 `approved` 且 `plan_digest` 一致的行」三条语义 | R4-2 |
| 3 | §4.1.1 新增 **`approval_id` 列 + 唯一索引**（决议入口键），使「审批通过后取回冻结动作」可实现 | R4-6 |
| 4 | **枚举统一**：`reason` / `reason_code` 三处（§3.4、§4.1.1、§4.1.6）统一为**同一 9 值集合**（补 `not_in_catalog`/`approval_denied`/`approval_expired`）；幂等表 `outcome` 由 3 值**扩为 4 值**（补 `failed`），并定义"首次执行即失败也写幂等行、重放返回同一失败" | R4-3 |
| 5 | §4.1.4 规则 5 **删除「小数去尾随 0」**，改为「不做跨类型折叠、不做尾随零归一（fail-closed 取更严）」，与单测判据自洽 | R4-4 |
| 6 | §4.1.3 `message_id` 由 `NOT NULL` 改为**可空**，并新增「响应重建」口径（为空时按 `outcome` 返回确定结果码） | R4-5 |
| 7 | §4.1.1 字段规范对照表**更正两处不实**：「append-only」→「不提供 DELETE 路径（本表非 append-only，决议就地更新）」；「并发审批最后写入获胜」→「**首写获胜：重复决议 `409`**」（与实码一致） | R4-3 / 重要项 9 |
| 8 | §3.7 **清除「零新迁移」措辞残留**（不再以已推翻口径作撤销理由） | 重要项 12 |
| 9 | §6 新增**「受影响既有测试的回归登记」**表（8 行，含前端 422 文案、PWA/桌面未知字段解析、`027` 模板登记） | 重要项 13 |
| 10 | 头部状态与本节（§9.3）更新；契约 `:587` 的 `execution` 字段、`:592` 的并发口径、`:671` 的 `reason` 集合同步回改 | 重要项 9/10 |
| 11 | 前置清单新增 **§B15**（10 项配置的守护测试扩项判据）；`feature-inventory.md` §3.4 补**许可来源**并**强化 C3 约束**；`poc-license-checklist.md` 同步 OpenClaw/Codex 核对结论；新建 `docs/change-record.md` 落 `027` 的既有表变更记录；`delivery-remaining-checklist.md` 组 10 补 4 条 | R4-7 / R4-8 / P6 / P9 |

**本轮仍未闭环（不得视为通过）**：§8 的 **U1–U8、U10–U13**；`WORKBENCH_EXEC_TIMEOUT_SECONDS` 默认值（U11，已在清单 §B15 登记为"实现前必须定值"）；`027` 未落地；前置清单 §B 的 B3④ 与 B13 遗留项；§5 用例 21（沙箱升级通道真实行为）；**§4.1 本附录自身尚未通过评审**。

> **重审触发（第四次更新）**：第五轮独立复核须**同时确认 §4.1 数据模型本体**，且**该确认必须由未参与 §4.1 撰写的独立视角完成**（§4.1 由本轮汇总方撰写并入，其"自评"不构成独立评审——记录 §9.7 已声明该结构性弱点）。复核通过后，本文件状态方可改为「已评审（附记录）」，并按清单 §C1 判据视为过闸；**在此之前不得建表**。

---

### 9.4 第五轮修订（第五轮独立复核后，2026-09-13）

**第五轮复核结论：不予放行**（4 个只读视角——「`§4.1` 数据模型本体**独立确认** / 对抗式真闭合 / 一致性与可测性 / 宪法合规与回归」+ 汇总方亲验 **11 条**；其中 **A 视角判「不予放行」**，B/C/D 判「附条件放行」——**以更严为准**）。**本轮首次满足记录 §9.7 与 §9.3 末段的独立性要求：`§4.1` 由未参与其撰写的视角（A）独立完成确认**；A 与 B 就 R4-2 是否闭合存在分歧，**汇总方亲验后采信 A**（缺列是文本事实）。完整记录见 [`dsh-integration-review-record.md`](file:///d:/徐徐AI学习/公司工作台/docs/dsh-integration-review-record.md) **§10**。

**用户裁决（J1，2026-09-13）：按「甲案」** —— `027` **增列承载参数**，并**显式声明与 §3.4「永不落正文」的边界**。

**本轮改动清单（逐条对应第五轮阻断项）**：

| # | 改动 | 触发 |
| --- | --- | --- |
| 1 | §4.1.1 新增 **`args_json JSONB NOT NULL`**（**控制参数**的受控落库副本）**＋「`args_json` 的正文边界」六条**（参数二分类 / 只落 `control` / 正文不落任何持久层 / 重跑从**事实源**重读并**重算完整摘要比对** / 无可复读事实源的 `body` 在 ⑥ **拒绝 `422`** / 大小边界） | **R5-1（甲案）** |
| 2 | §4.1.3 新增 **`http_status INTEGER NOT NULL`**；「响应重建」改为**可兑现口径**（`http_status` 为唯一结果码来源）；**顺带定死**：审批后执行**不回写**幂等行，重放仍返回首次 `202` | **R5-2**（并顺带关 I-8） |
| 3 | §4.1.4 规则 5 **删除不可实现的「`1.0` 与 `1.00` 视为不同」**，改为「同为 `float` → **相同**」；判据**改指 §5 用例 28**（原误挂用例 13） | **R5-3** / 顺带 **I-1** |
| 4 | §4.1.6 调用链补「**控制参数取 `args_json`** + 正文从**事实源重读** + 重算摘要比对」；§4.1.7 第 1/3/4 条同步；**「缺省保持旧行为」消歧**（**仅指比对粒度退化，不含 fail-open**）；`ToolAction` 注明「不含参数原文与 `args_json`」 | **R5-1 / R5-4** / 顺带 **I-4** |
| 5 | §5 **新增用例 28–31**（参数规范化判据 / `actions` 缺省语义 + `ToolAction` 字段 / 装配三断言 / 决议端点 `execution` 响应体） | **R5-3 / R5-4** |
| 6 | §4.1.7 末行**评审范围更正**（两张新表分属 §4.1.1 与 §4.1.3，原误写为一节） | N-9 |
| 7 | `docs/change-record.md` **补登两张新表**（`workbench_tool_actions` / `workbench_execution_idempotency`）——宪法 1.4 数据模型变更留痕 | **R5-5** |
| 8 | `poc-license-checklist.md`：Hermes / Codex / OpenClaw 改为**上游 `LICENSE` 原文直取（经 GitHub 官方 API）并记录 SHA**；Hermes 原「依据为知识库笔记 + 用户在使用」**不构成许可证证据**，已更正 | **R5-6** |
| 9 | **状态同步四处**：门禁清单（头部 / §C1 / §C3 / §E.5）、功能清单（§3.3 / §5.3）、立项 §14.1 P2a-2——由「第三轮 · 待第四轮」改为「**第五轮 · 待第六轮**」 | **R5-7** |
| 10 | **四份文档互斥修正**：`architecture.md` ② 行改「**无已生效实例 + 唯一候选**」；`moat-boundaries.md` §3 同步；`capability-ownership-map.md` 第 20/21/30 行改为**单一归属**（删「D/C」、候选归属走"先补一行"规则） | **R5-8** |
| 11 | `multi-adapter-coexistence-spec.md` **新增「边界声明」三条**（未评审不得作依据；**I3 与契约同向但不等效、不得由该文件驱动改动**）；`architecture.md` 加**状态声明**（三份文档为未评审草案、降级为参考）；`api-contract.md` 审批推进段补**参数取回口径**；`moat-boundaries.md` §7 补更正与授权登记 | **R5-9** |

**本轮仍未闭环（不得视为通过）**：§8 的 **U1–U8、U10–U13**（含 **U11 = `WORKBENCH_EXEC_TIMEOUT_SECONDS` 默认值**，**第三次挂起**，需用户裁决）；`027` 未落地（**可重复执行性、对既有 1434 项零破坏、升级/回退演练一律未验证**）；前置清单 §B 的 B3④ 与 B13 遗留项；§5 用例 21（沙箱升级通道真实行为）；**记录 §10.4 的 18 条重要项已登记、本轮未逐条修**。

> **J2/J3/J4/J5 未单独裁决**——本轮按汇总方建议执行：**J2** 取「幂等表**加列**」；**J4** 取「**取回上游 LICENSE 原文**」（优于原两选项）；**J3/J5** 取「四份文档**降级为参考 + 声明不构成改动要求**」。**如不同意可回改**（记录 §11 已留痕）。

> **重审触发（第五次更新）**：**第六轮独立复核**须确认 ① `§4.1` 数据模型本体（**含 `args_json` 正文边界六条与 `http_status`**）；② **§5 用例 28–31 的可判定性**；③ **R5-5 / R5-7 / R5-8 / R5-9 的落地**。通过后本文件状态方可改为「已评审（附记录）」，并按清单 §C1 判据视为过闸；**在此之前不得建表、不得写第一行实现代码**。

---

### 9.5 第六轮修订（J7 = 丙案 + J8/J9 定死，2026-09-13）

**第六轮复核结论：不予放行（3 阻断）**（A/B/C 三视角均判不予放行，D 判附条件）。**核心判断：第五轮的「甲案」本体不可实现**——甲案＝"`args_json` 只落 `control`，`body` 靠**事实源重读**"，但唯二带 `body` 的工具（`fs.write` / `fs.overwrite`）的 `content` 是**模型生成的新内容**，**不存在可复读的事实源**；且 §3.3 下工作卷"生成即空、运行结束销毁"，跨请求审批等待期的存活语义从未定义。→ **在既有 §3.3 + §3.4 下，"审批"与"写文件"不可兼得。** 完整记录见 `dsh-integration-review-record.md` §12。

**用户裁决（2026-09-13）**：
- **J7 = 丙案**：`body` 落**受控密文**（**牺牲 §3.4「永不落正文」的绝对性**，换取"审批 + 写文件"可用）；
- **J8 定死**：`ToolCatalog` 新增 **`param_roles`** 字段（`{参数名: "control"|"body"}`，默认 `control`）；⚠️ **更正注（过闸前补，2026-09-13）**：**本行为第六轮当时口径的历史留痕**——后经 **P1**（改为 **fail-closed、取消默认值、未声明即拒绝装配**）与 **P11**（**改名 `ToolSpecCatalog`**）修订，**当前有效口径以 §3.1 / §3.1.1 / §4.1.1 边界第 1 条为准**；
- **J9 定死**：① 步**按阶段区分结果码**（首次 → `422` 输入语义错误；审批后重跑 → `409` 状态漂移冲突），**并双向写进契约**；
- **J6（`WORKBENCH_EXEC_TIMEOUT_SECONDS`）仍挂起**（第四次）。

**本轮改动清单（对应记录 §13.3 的 9 项）**：

| # | 改动 | 关联 |
| --- | --- | --- |
| 1 | §3.4「永不落正文」→「**默认 + 唯一受控例外**」五条约束；§4.1.5 清理策略拆两行（**密文列强制 TTL、本段必做**） | J7 = 丙案 |
| 2 | §4.1.1 DDL 增 **`body_ciphertext` + `body_expires_at` + `body_check`**（同有同无）；字段规范对照表增「字段内容边界」行；边界第 3/4/5 条改写（**「从工作卷读」与「⑥ 拒绝 `422`」作废**） | J7 |
| 3 | §3.1 增 **`param_roles`** 字段；§3.1.1 逐工具标注（**仅 `fs.write`/`fs.overwrite` 的 `content` 为 `body`**） | J8 |
| 4 | §4.1.6 调用链与 §4.1.7 第 1/3/4 条 → **「从 `body_ciphertext` 解密还原」** | J7 |
| 5 | §4.1.3 增 **`approval_id`** 列（重建 `202` 响应体）+ **`result_check`**（`outcome` ↔ `http_status` 合法组合）+ **⑥ 失败不写幂等表**；§4.1.6-5 ⑨ 行 `200` → **`201`** | J-4 / J-5 |
| 6 | §4.1.6-5 ① 行补「审批后重跑路径」限定 + **新增 J9 分界说明**；契约 `:641` 状态码分支与闸门表 ① 行**双向补注** | **R6-3 / J9** |
| 7 | **§5 新增用例 32（密文与 TTL）与用例 33（正文不进对外通道）** | 丙案验收 |
| 8 | §6 回归表：补「**决议端点新增 `execution` 字段**」行；`027` 静态契约测试**点名断言全部列与 3 个 CHECK** | J-9 |
| 9 | `change-record.md` 三条记录同步密文列 / `approval_id` / `result_check`；`api-contract.md` 参数取回口径改**密文还原** | 合规 / 落地 |

**仍未闭环（不得视为通过）**：**J-1～J-16（第六轮 14 条重要项）**、J6、U11、U12、U13、U14、**U15**；`027` 未落地（**可重复执行性 / FK 列序 / 对既有 1434 项零破坏 / 升级回退演练 一律未验证**）；**加解密与密钥管理、TTL 清理任务、全部实现与测试均未写**；§5 用例 21 仍「未通过」。

> **重审触发（第六次更新）**：**第七轮只做「定点复核」**（依记录 §12.9 的流程建议，不再全量）——仅确认 **R6-1 / R6-2 / R6-3 三条阻断**是否真闭合，以及 §5 **用例 32/33** 的可判定性。通过后本文件状态方可改为「已评审（附记录）」，并按清单 §C1 判据视为过闸；**在此之前不得建表、不得写第一行实现代码**。

> **第七轮定点复核结论（2026-09-13）：未通过（部分闭合）** —— **R6-3 真闭合**；**R6-1 / R6-2 表面闭合**：① `param_roles` **默认值 fail-open**（漏声明 → 正文明文进 `args_json`，与 §3.4 方向相反且不可检出）；② **加解密组件、密钥、清理周期无落点**，**加解密失败语义与密钥轮换未定**；③ **用例 32② 不可判定**（`BYTEA` 列无法 grep 明文，可能假绿）；④ **8 处状态漂移** + 门禁 §C3「31 条」事实错误；⑤ `ToolCatalog` **同名不同构**。完整记录见 `dsh-integration-review-record.md` **§15**。

---

### 9.6 第七轮补丁（P1–P11，2026-09-13）

**用户裁决**：**P1**（`param_roles` 改 **fail-closed**）✓、**P3**（**新增独立密钥配置**，不复用 `backup_encryption_key`）✓、**P11**（**`ToolCatalog` 重命名为 `ToolSpecCatalog`**，新建独立模块）✓，**其余 8 条按推荐直接做**。

| # | 补丁 | 落点 |
| --- | --- | --- |
| **P1** | **消除 fail-open**：`param_roles` **无默认值**，**必须为每个参数显式声明**；**任一参数未声明 → 拒绝装配**（启动期断言 §4.1.6-3 + 用例 **34**）。三处口径同步（§3.1 / §3.1.1 / §4.1.1 边界第 1 条） | §3.1、§3.1.1、§4.1.1、§4.1.6-3、§5 |
| **P2** | **加解密组件落点**：`ToolExecutionService` 构造依赖增 **`BodyCipher`**；新增 **1.1 加解密失败语义**（⑥ 加密失败 → `503` 不进等待；重跑解密失败 → **失败表新增行** `502`+`runtime_error`+`tool.blocked`+保持 `approved`） | §4.1.6-1/-1.1、§4.1.6-5 |
| **P3** | **配置 10 → 12 项**：增 **`WORKBENCH_BODY_ENCRYPTION_KEY`**（必填非空、配置外置、不复用备份密钥）与 **`WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`**；§6 回归表与门禁 §B15 须同步为 12 项 | §4、§6、门禁 §B15 |
| **P4** | **密钥轮换**：双密钥窗口（新密钥加密、旧密钥仅解密），**窗口 = 最大审批超时 + 清理周期** | §3.4 约束 1 |
| **P5** | **占位常量 `"«body»"` 不参与任何比较/判定/响应重建**（按 `param_roles` 按键区分，不按值判定） | §3.4 约束 5 |
| **P6** | **审批超时 → `expired` 的执行方**：由「审批过期处理」与清理任务**同批、同事务**完成「置 `expired` + 写 `decided_by`/`decided_at`/`decision_source` + 清空两列」；**禁止只清密文不改状态** | §4.1.6-8 |
| **P7** | **用例 32② 改可执行口径**（hex 子串断言 + 长度下界 + 四处 grep）；**32⑦ 注明在隔离测试库直连写入** | §5 用例 32 |
| **P8** | **双向引用**：§3.4 / §4.1.1 边界 / §4.1.3 / §4.1.5 回指**用例 32 / 33**（补 P1 的用例 34） | §3.4、§4.1.1、§4.1.3、§4.1.5 |
| **P9** | **状态同步 8 处 + §C3「31 条」→「34 条」**（本轮新增用例 34；第七轮时为 33） | 门禁清单、功能清单、立项、能力归属表 |
| **P10** | §4.1.3 与 §4.1.1 边界第 3 条**交叉引用**（幂等表不落正文） | §4.1.3 |
| **P11** | **`ToolCatalog` → `ToolSpecCatalog`**，新建独立模块；**明确与 `app/planner/models.py` 既有同名类的关系**（不得复用该名、不得扩该类） | §3.1、§3.1.1、§4.1.6-1 |
| **Q1** | **P8 真双向引用**（补丁确认未通过项）：① **用例 32/33 行内补条款引用**（§3.4 / §4.1.1 / §4.1.5 / §4.1.6-8 与 §4.1.3 / 契约）；② **§4.1.1 边界第 2/3/4/5 条、§4.1.3、§4.1.6-7 补回指用例 32/33** | §5、§4.1.1、§4.1.3、§4.1.6-7 |
| **Q2** | **P7 补可执行性**（补丁确认未通过项）：① **定死 AEAD 算法 = AES-256-GCM**（**nonce 12B + tag 16B → overhead 28B**），长度断言改 `≥ 正文字节数 + 28`（**有来源**）；② 用例 32②(c) 给**可执行检索方式**（库内 **SQL 查询**、日志**路径须在验收记录写明**）；③ **③ 必须红列补 4 条**（只追加 nonce+tag 不加密 / 下界改小 / 占位常量参与比较 / 正文写进 `args_json` 等） | §3.4、§5 |
| **Q3** | **修状态漂移**：§3.4 例外引言「2026-09-13 已实施」→「**文档层已定案；实现未落地**（见 §8 U15）」 | §3.4 |
| **R1** | **§4.1.1 边界第 1 条补回指**：增「判据见 §5 **用例 34**（机制）与 **32⑥ / 33①**（后果）」 | §4.1.1 |
| **R2** | **用例 32②(c1) 补列类型口径**：① `args_json`（**JSONB** → 必须 `::text`）；② **点名 `workbench_audit_log.detail`**（**JSONB** → 必须 `::text`）；③ 注明 `conversation_messages.content` 为 **TEXT** 可直接判定——**JSONB 无隐式转换，漏 `::text` 会报错** | §5 |
| **R3** | **补 nonce 唯一性/随机性**（12B CSPRNG、严禁重用、不得由计数器/时间戳/密钥派生）**+ 定死密钥格式**（32 字节原始密钥的 `base64`，启动期校验长度） | §3.4、§4 |
| **D-A**（2026-09-13，段二-1 取证出新发现） | **`dsh-session-telemetry-otel` 加入 §3.5 禁用清单**：实测其 `exporter.url` 默认指向 `harness-telemetry.deepseeksvc.com`、`mode` 默认 `FEEDBACK_ONLY` → **web 之外的第二条默认出网通道 + 会话数据外流**；**关闭首选上游开关 `DSH_TELEMETRY_DISABLED`**（§F8.1④ 实测存在），禁用插件为兜底；进启动期断言，用例 24 同步 | §3.5、§5 |
| 🔴 **C1（2026-09-13，阻断级）** | **B14 判据 C 与 dsh 架构不相容**（`dsh --profile sdk` 由容器内进程自驱模型调用）⇒ **U1 的"容器内不持密钥"在 dsh 默认部署下不成立**；可行形态须**自建模型网关**（容器内仅短期令牌）。**三条路径待裁决，见门禁 §F8.4** | §3.3、§3.5、门禁 §F8 |
| ✅ **C2（2026-09-13 用户裁决：路径①）** | **走「自建模型网关」**：段二新增组件（容器外持供应商密钥、容器内仅短期令牌六条）；**网络面由 `--network none` 改为「仅内网桥（`--internal`）+ 仅网关可达、无外网出口」**；**判据 C 正式作废 → 改判 C′（容器内无指向供应商域名的连接）**；§1.1 新增交付项 F、§3.3 网络/凭据两行、§3.5 P1 全部回填；**§4 配置项需新增网关相关项（待补）** | §1.1、§3.3、§3.5、门禁 §B14/§F8 |
| **D-B**（2026-09-13，段二-1 取证出新发现） | **B13 决议算术更正**：Linux 实测随镜像 `@img/*` **4 个**（非 2 个）、**含 LGPL 2 条**（非 1 条）→ `THIRD-PARTY-NOTICES` **须含 2 条 LGPL**；"删除 `@img/sharp-wasm32` 降回 1 条"列为**实施期实测项**（须证明 sharp 仍可用） | 门禁 §B13 |

**仍未闭环（不得视为通过）**：**J-4～J-16**（第六轮重要项）、**J6**、**U11**（超时默认值）、**U12**、**U13**、**U14**、**U15**（丙案机制未实现）、**U16（新）**；`027` 未落地 → 可重复执行性 / FK 列序 / 对既有 1434 项零破坏 / 升级回退演练**一律未验证**；**加解密实现、密钥管理、TTL 清理任务、全部用例均未实现未测**。

> **评审闭环（第十次更新，2026-09-13）**：本规格**已评审通过（附记录）**。评审链共 **8 次独立复核**（首轮 1–4 次 → 第三～六轮全量 → 第七轮定点 → 补丁确认 → 再次补丁确认 → 最后一次补丁确认），**终局**：**R1/R2/R3 全部真闭合**（见 `dsh-integration-review-record.md` **§21**）。
> ⚠️ **下一步不是写代码**：须先做**门禁 §B 取证**（**段二-1**：运行时复验 + 容器能力取证，**只读勘察**，不写业务代码）；§B 通过后才进入**段二-2**（工具目录 + 九步闸门）。**本节及 §4.1 的 DDL 仍未落地**（`migrations/027` 不存在）。
