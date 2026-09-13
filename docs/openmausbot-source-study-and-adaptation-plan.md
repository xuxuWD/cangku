# OpenMausBot 源码研读与借鉴方案

> **性质**：**调研 + 借鉴提案**。**不是决策记录**，不改变任何既有决议；由其推导的决策须经评审后写入 [立项文档](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §4 / §17 或段二规格。
> **方法**：`git clone --depth 1` 到**仓库之外** `d:\徐徐AI学习\_openmausbot-study\OpenMausBot`（64.7 MB / 2069 文件 / 1073 个 `ts·tsx` / 130 个 md），按 **5 个域并行只读深读**（引擎驱动 / 权限审批沙箱 / 进程与凭据边界 / 数据模型 / 前端与工程合规），加**汇总方亲自复核 7 条**。**全程只读，未修改对方仓库与我们的仓库，未执行任何 git 写操作，未向本项目引入其任何代码、资源、文案或视觉。**
> **快照**：`milind-soni/OpenMausBot@c869681`（2026-09-13）。
> **日期**：2026-09-13
> **上位**：[段二规格](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-dsh-integration-design.md)（U1 待核实项）、[立项文档](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/specs/2026-09-12-conversational-agent-platform-design.md) §17、[P2c 交互模式借鉴清单](file:///d:/徐徐AI学习/公司工作台/docs/p2c-interaction-study.md)。

---

## 1. 许可边界（先看，因为它决定"能借什么"）

| 范围 | 许可（读原文核实） | 我们能用什么 |
| --- | --- | --- |
| 仓库主体（除 `enterprise/`） | **Apache-2.0** | **可商用**；**模式可借；代码亦可复用**，但须履行 §4 义务（随附许可全文、保留 `NOTICE`、标注修改文件） |
| **`enterprise/`** | **非开源 carve-out**（`LICENSING.md:6-18`）：仅 dev/test 免费，**生产需 license key**；**禁止托管给第三方 / 白标** | **绝对不引用、不复制、不改编其任何内容**（这是最容易踩的一脚） |
| 商标 | **不随许可授予**（`LICENSING.md:40-43`，引 Apache §6） | 我们**不得使用**其名称与吉祥物 |
| 打包的第三方 | 各自许可；含 **MPL-2.0 × 7**（Cua 原生运行时）与 Chromium BSD | 若复用其**打包产物**须另行核对；**做法**可借（见 §4-G） |

> **与另两个候选的差别**：OpenWorkBuddy 与 EvoFlow 都是**非商用许可**（只能看不能抄）；OpenMausBot 主体是 **Apache-2.0**，是三个里唯一**允许代码复用**的。但注意"能复用"≠"该复用"——见 §5。

---

## 2. 最重要的五个发现

### 2.1 🔴 它的权限模型与我们的九步闸门**方向相反**——不是参照实现，而是反例

`docs/approval-levels.md:3-7` 原文：

> "Each level is one of the **provider's own permission modes, passed through**. OpenMausBot **does not judge an action itself: there is no app-side allowlist, classifier, or pattern rule.**"

- 它的"权限模型" = **5 档供应商模式透传 + 2 条 app 侧硬规则**；**没有** `low/medium/high/critical` 的风险枚举、**没有**阈值判定、**没有**参数 schema、**没有**路径校验、**没有**危险命令黑名单（视角 B，已复核）。
- **最高档 Full access 是"标准解除"**（`approval-levels.md:14`：覆盖 "potentially destructive or sensitive work"，残留提示自动代答）——**不存在"高危必须审批"的兜底**。
- **批准后不重跑任何校验**：决议写回后 CLI 直接继续本来在等的那次调用（视角 B 证据），**与我们「审批通过后必须从 ① 重跑全套闸门」正好相反**。
- 唯一"豁免被禁止"的是**提问类**（任何模式都不得代答）。

**结论**：这份代码**不能**当作我们九步闸门的对照实现。但它反过来**印证了我们更严**：② 参数 schema、③ 路径、④ 三个子判定且命中即拒、⑤ `critical` 定档、⑦ 计划/参数摘要逐项授权、审批后重跑——**在它那里全部没有对应物**。我们**不得**因"对方也没做"而简化任何一条。

### 2.2 它的容器**不是安全边界**，而我们的必须是

| 项 | OpenMausBot（证据） | 我们（段二 §3.3） |
| --- | --- | --- |
| agent 进程位置 | **在宿主**——harness spawn 本机 CLI（`claude`/`codex`…），以**当前 OS 用户权限**运行 | 容器内，非 root |
| 容器里跑什么 | 只是**被 agent 遥控的桌面**（XFCE），agent 本身不在里面 | agent 沙箱本体 |
| 网络 | 容器 run args **全段无 `--network`** → 默认 bridge（**可出网**），`container-computer.ts:895-946` | **`--network none`** |
| 工作卷 | 只挂一个目录 + `0700`，**无 `noexec/nodev/nosuid`** | `nosuid,nodev,noexec` + 与容器根**不同设备** |
| 加固 | ✅ 有一手：`--cap-drop ALL` + 仅 `SETUID/SETGID`（podman 另加 `SYS_CHROOT`）、`--ipc private`、`--cgroupns private`、`--shm-size 512m`、`--memory 4g`、`--cpus 2`、`--pids-limit`、端口只绑 `127.0.0.1` | 同级更严 + 镜像 digest 钉死 + 孤儿回收 |

**结论**：它把"执行侧"定义成"容器/云机"，**agent CLI 被算作宿主可信面**——这正是我们 U1 要划的那条线（见 §6）。它的"最小挂载"是**为了隔离被遥控的桌面**，不是隔离 agent 进程。

### 2.3 ⭐ 它的判据可以直接把我们 U1 的问法**改写成可取证清单**（本轮最高价值产出）

它把"凭据在哪"收口成一条判据：**harness 是唯一 spawn 者 ⟹ harness 是唯一凭据持有者**（`README.md:180-182`「The harness server owns every agent process」）。据此，我们的 U1（"dsh 进程跑在工作台宿主还是工具容器内？模型凭据从哪来？"）可改写为：

> **"容器内不持有模型密钥"成立 ⟺ ① 出站连接发起方在容器外 + ② 清空宿主侧凭据后 turn 立即失败 + ③ `--network none` 下容器既不出网也不持密钥 + ④ 容器无密钥明文（env/argv/镜像层/日志）。四条必须同时成立。**

完整 7 条现象→判据→边界见 **§6**。这份清单建议直接作为**段二-1 的取证模板**（清单 §B 的补充）。

### 2.4 三条**可迁移的契约纪律**（我们适配器层缺的正是这些）

1. **能力旗标必须同时门控「挂载」与「对模型的提示」**。它的注释反复出现同一句：`never show a knob the driver cannot turn`、`a bot must never be told it has a computer whose tools its driver cannot mount — it burns turns hunting for tools that aren't there`（`server/contracts.ts:288-334`，已复核）。→ 我们 `AgentRuntimeAdapter` **没有能力声明面**，九步闸门与对话入口各自 `if`，缺单一可信来源。
2. **失败一律 fail-closed，且降级成"可展示状态"而不是崩溃**：未知驱动 → `ShadowInstance{shadow:true, reason}`，对外 `{state:"unavailable", reason}`（`server/harness/registry.ts:18-26, 90`），**不阻止启动**。→ 与我们裁决 R4（`restrict` 空交集不拒绝进程启动）同向；我们 `registry.py` 目前是**构造期校验失败即 raise**，粒度更粗。
3. **恢复前先判"重放是否安全"**：`before-accept`（本轮未产生副作用→允许重放一次）/ `after-accept`（已产生输出→**禁止重放**）/ `unknown`，判据优先级是"**模型说话了就说明 prompt 送达了**"（`server/resume-recovery.ts`）。→ 我们 `resume_run` 目前**无条件恢复**；段二"同步 + 单次执行硬上限"下，盲目重跑会产生**重复副作用**（与宪法 4.2 幂等直接相关）。

### 2.5 许可与工程合规：Apache-2.0 可商用，但 `enterprise/` 是雷区

- 主体 Apache-2.0；**`enterprise/` 目录非开源**（生产要 key、禁托管/白标）——**最容易被误引的一脚**。
- 它把**许可当打包硬闸门**：签名前校验许可文件存在，缺文件直接 `throw`；发布流水线再校验一次；并为原生运行时生成 **CycloneDX SBOM**，脚本在包集合不符时失败（视角 E 证据）。→ 这是可直接照抄的**做法**（对应我们 `THIRD-PARTY-NOTICES` 义务，段二 §4/U13）。

---

## 3. 逐域要点（压缩版，完整证据在各视角报告）

### 3.1 引擎/驱动抽象（视角 A）
- 契约是三层：`ProviderDriver`（静态 SPI）/ `ProviderInstance`（实例，含 `snapshot()` 可用性探测、`refreshModels()`、认证流、`reviewPermission()`）/ `ProviderAdapter`（每轮：`sendTurn`、`interruptTurn`、`respondToRequest`、`steer`、`hasSession`、`stopAll`、`onEvent` 订阅）。
- 17 个内置驱动收敛方式：**通用运行时 + 瘦 support 对象**（ACP 系）或**自有协议驱动**（claude/codex/pi）。ACP 的 per-harness 差异全收进 `AcpSupport` 字段/钩子。
- 事件模型 14 类（`session.* / turn.* / item.* / content.delta / request.* / runtime.error`）；**驱动→服务端是进程内回调订阅，服务端→UI 是单条 SSE**（带游标、心跳不推进重放、`hello.resumed=false` 时要求全量 hydrate）。
- 两个可直接抄的细节：**`turn.completed.usage` 是唯一可累加的数**（live 指示器永不许求和）；`assistant_image` **折进私有附件 store、绝不走渲染端 SSE**。
- 会话归 provider 原生 session 所有，harness 只存 `resumeCursors`（per task × per instance）+ `lastInstanceId`，且**对客户端隐藏**。

### 3.2 权限/审批/沙箱（视角 B）
- 审批链路：`provider CLI → permission-proxy（unix socket）→ 驱动 broker → request.opened → 落成 options 消息卡`；挂起→决议→**CLI 内续跑**（不重跑校验）。
- fail-closed 兜底齐全：代理连不上→deny；回合已结束→按 deny/answer；重复 ask id→deny；15 分钟超时→permission deny。
- **提权两阶段**：`Full`/`Custom` 只能在打包桌面端开启；HTTP 直接 PATCH 提权 **403**；存储态先落 inert 标记、普通客户端一律降级显示为 `ask`，只有 Electron 私密通道能使其生效。→ 对应我们「授权来源白名单校验发生在审批写入阶段」。
- 平台门禁典范（**我已亲验** `docs/linux-desktop.md:178-210`）：Wayland **fail-closed**、旧 opt-in 自动重置、**"will not be controlled by an environment override"**、`Linux Auto never routes to the user's desktop`。
- 缺口：审计 `decisions.ndjson` **轮转覆盖 `.1`**（会吞历史）；逐 thread 事件日志**无界**；审批人与发起人**可以是同一人**。

### 3.3 进程与凭据边界（视角 C）
- 拓扑：`Electron main → harness(127.0.0.1:8799，绑定地址硬编码) → spawn CLI 子进程（stdio 管道，不经 shell、不用 PTY）→ 再由 CLI 挂 stdio MCP 子进程`。
- 生命周期：POSIX 用**进程组** `kill(-pid)`（连坐 MCP 子进程）；Windows `taskkill /T /F`；停击用 `WeakMap` 幂等；turn 结束**只停轮次不停进程**（idle 10 分钟回收）；停机统一 `dispose`；**data dir 单进程租约**。
- 凭据：`~/.openmausbot/config.json`（桌面壳用 Electron `safeStorage`；无壳时**明文 + 0600**）；**API 只回 `configured` 布尔，永不回显**（有测试守护）；**密钥只进 env、不进 argv**（注释点名 `argv` 通过 `ps` 可读）；对子进程做**白名单式剥离 + 定点注入**（"父进程 env 里搭便车的 key 绝不放行——那会把订阅制登录翻转成按量计费"）。
- **容器里只有一个 env（`VNC_PW`），没有任何模型凭据**。
- **短期凭据原型（per-turn capability）**：每轮新铸 `randomBytes(24)`、绑死 `(租户/会话/turn 代次)`、服务端记录为准（请求体字段只是"断言"）、`timingSafeEqual` 比对、turn 终态**同步吊销**、有孤儿兜底上限。→ 这是 §3.5「是否允许短期凭据」的最佳参考形态。
- 暴露面：harness loopback 硬编码；**companion sidecar 是唯一监听 `0.0.0.0` 的部分**，且**默认关闭**（"running this process *is* the opt-in, so there is no toggle to forget"）。

### 3.4 数据模型（视角 D）
- 形态：**单进程 + 单数据目录 + 文件为真相 + SQLite 记转录**（`bots.json` / `groups.json` 整文件重写；`messages.db` WAL）。
- **无迁移机制、无 schema 版本号**（核心 JSON 无 version），演进靠"非 strict schema + 未知键保留 + 启动时启发式修复"。
- **无租户列**；隔离靠"一目录一进程一 OS 用户"。
- 转录**非 append-only**（卡片需原地更新）；消息是**树**（`parentId` + `active_leaf_id`）。
- 有价值的三处取舍：**「不可用 + 原因」是一等数据**（`ProviderSnapshot{state, reason}` + 错误分类码）；**受保护状态放在 agent 可写工作区之外**（技能审批态、记忆 journal）；**投影式索引可重建**（文件是真相，索引随时重建）。
- 它的缺口与我们自查项的对应见 §5.3。

### 3.5 前端与工程（视角 E）
- 不是路由驱动：**单一 reducer + `activeView` 三值 + 叠加式面板**（`ChatView` / `GroupView` / `TeamMap` / `Routines` + Inspector + Computer + Settings）。
- 内联审批链路（**已亲验**）：后端落成 `kind:"options"` 消息卡 → **单条 SSE**（自建 supervisor：游标 `?since=`、ping、退避重连、`focus/online/visibility` 唤醒）→ UI 提取未决卡 → **决议"接管输入区"**（不是卡上按钮）→ `POST /api/threads/:id/respond` → **reducer 里 `case "decideRequest": return state;`（权威态由服务端 `request.resolved` 回流，无本地乐观更新）**。
- **卡类型由结构字段判定、不由按钮文案判定**（`card-answer.ts`：判错的后果是卡被判 `unavailable`、机器人白等 15 分钟）。
- 不卡顿的结构手法（浏览器 React 19，**可迁移到我们 admin-web**）：**每帧批量 delta**（rAF 合并 + 100ms 兜底 + 64Ki 上限）、**流状态与主状态隔离**（`StreamContext`，token 帧不进 reducer）、**已定稿转录整体 memo**、**窗口化 120 条 + 锚定式边界**、**底部跟随 4px 亚像素阈值**、**三态命名纪律**（`settled / failed / stalled / timed-out / needs-user` 是不同结果）。
- ⚠️ **认知纠正**：它**当前并不渲染增量正文**（流式尾部显示 presence 而非 partial text，其官方验证文档自述）；我们若要"边生成边显示"，那是 **P2b 的 SSE 契约**问题，它在此处**没有可借的实现**。

---

## 4. 可借鉴清单（按对我们的用处排序）

| # | 借鉴点 | 落到我们哪里 | 阶段 | 不可照搬之处 |
| --- | --- | --- | --- | --- |
| **A** | **「容器内不持有模型密钥」的四条同时成立判据**（出站连接发起方在容器外 / 清空宿主凭据即失败 / `--network none` 下照常成功 / 无密钥明文） | **段二-1 取证模板**（补清单 §B 与规格 §8 U1 的收口方式） | **段二-1（最高优先）** | 它的结论"agent 在宿主"不能当我们的结论——我们**必须实测** |
| **B** | **能力声明面**（驱动声明能挂什么/能不能做，UI 与闸门都读它，绝不显示"转不动的旋钮"） | `AgentRuntimeAdapter` 补能力声明；九步闸门 ① 与对话入口共用同一来源 | 段二-3 | 旗标名须换成我们的语义（文件写/命令执行/网络/知识检索/能否产 `critical`），**不搬 MCP 那套** |
| **C** | **失败降级成"可展示状态"而不是崩溃**（`{state, reason}` + 错误分类码 + shadow） | 适配器/注册表：dsh 未装、未登录、版本不符都应**可展示且不阻断启动** | 段二-3 | 它的探测会去读宿主凭据文件（`~/.claude` 等），我们 A3 禁止 |
| **D** | **恢复前判"重放是否安全"**（`before-accept` 可重放 / `after-accept` 禁止） | `resume_run` 补判据；段二超时/断连后的重跑必须据此 fail-closed | 段二-3 | dsh 只有 3 个请求、拿不到同等信号 → 只能用**我们自己的 checkpoint/审计**推 |
| **E** | **短期凭据的六条形态**（每 turn 新铸 / 绑死租户·会话·代次 / 服务端为准 / constant-time 比对 / 终态同步吊销 / 孤儿上限） | 规格 §3.5「是否允许短期凭据」→ 改为「**仅允许**此形态；**禁止**开机固定的共享令牌」 | 段二-3 | 它靠宿主 CLI 登录态；我们必须容器内零凭据 |
| **F** | **脱敏"保形不保值" + 幂等**（`«redacted N chars»`，且对已掩码值幂等，否则会改 hash） | 我们 `redact_payload` 目前**只按键名**匹配 → 补**内容形状**一路（工具标题/命令摘要/回复正文里带的 key） | 段二-3 | 它的正则是围绕其 provider 生态的，我们需自建并防中文误伤 |
| **G** | **许可当打包硬闸门 + SBOM 可复现** | `THIRD-PARTY-NOTICES` 的产出与校验（段二 §4 / §8 U13） | 段二-3 | 不复用其打包产物（带 MPL/Chromium 义务） |
| **H** | **审批 UX 三条判据**：决议入口唯一（接管输入区）/ 权威态服务端回流（无本地乐观）/ 卡类型由结构字段判定 | **P2c**（D1 已裁决"随 P2c"） | P2c | 它靠独立 `respond` 端点；我们若坚持"前端只是入口、不新增后端契约"，需在 P2b 明确选路 |
| **I** | **SSE 传输的 supervisor 形态**：游标 + ping 活性 + 退避重连 + 可见性唤醒 + `resumed=false` 走快照回退 + 快照与实时帧排队对齐 | **P2b**（立项 §17.4 的断线续播） | P2b | 它是单机单用户、消息全量在内存；我们必须落库 + 分页 |
| **J** | **不卡顿的结构手法**（每帧批量 / 流状态分区 / 转录 memo / 120 条窗口 / bottom-follow 阈值） | P2c 前端性能判据（**阈值我们自定**） | P2c | 它不渲染 partial text；Electron 单端 ≠ 我们三端并存 |
| **K** | **状态与三态命名纪律**（`settled/failed/stalled/timed-out/needs-user` 是不同结果） | 我们的运行/审批状态取值显式化 | P2b/P2c | — |
| **L** | **文档工程骨架**：每篇验证配方固定「给出什么证据 / **这篇证明了什么、没证明什么** / 最后执行日期」，并明写"**单测全绿不等于用户流程可用**" | 我们的验收记录格式（强化"未验证必须写未验证"） | 立即可用 | 不抄文案 |

---

## 5. 不可照搬清单 + 我方自查项

### 5.1 不可照搬（照搬即违反我们既定约束）

> **通用判据已单独成文**：[`architecture.md` §外部集成的判据：接适配器 vs 搬代码](file:///d:/徐徐AI学习/公司工作台/docs/architecture.md)（含三问判据与"能力面 = 对方接口面"的代价说明）。本节只列**针对 OpenMausBot 的具体结论**，不重复判据。

1. **把审批判定整体外包给 provider**（`approval-levels.md:5-7`）——与"命中即拒、不允许审批放行"直接冲突。
2. **Full access 自动批准一切**（含沙箱放宽与 computer 控制）——与"最高档不豁免审批"冲突。
3. **在本机以用户权限跑 agent CLI、并使用用户本机登录态**——与我们"分主机 + 容器 + 无长寿命凭据"冲突。
4. **容器可出网**（其容器无 `--network none`）——我们硬性 `--network none`。
5. **"Always allow this session"把供应商建议的权限规则原样回传**——授权粒度不受我们控制，无法做参数摘要绑定。
6. **批准后不重跑校验直接续跑**——与我们 ⑦→⑧ 之间"从 ① 重跑"相反。
7. **单机 loopback 即凭据**（其 companion 自述"the loopback socket IS the credential"）——我们多租户必须有 401/403 与数据归属。
8. **明文密钥入配置文件**（无桌面壳时）——我们已用 `app/accounts/secrets.py`。
9. **无迁移机制 / 无租户列 / 转录可改可删 / 审计落普通文件**——我们已有更严结构，**不要退化**。
10. **代码、组件、文案、皮肤、视觉**（立项 P2c 明令）；**`enterprise/` 任何内容**；其商标与吉祥物。

### 5.2 它暴露的、我们**可能同类**的风险（我方自查项，均为**未核实**，需自查后处置）

| # | 它的缺口 | 我们是否有同类风险 | 建议动作 |
| --- | --- | --- | --- |
| 1 | 审计轮转"只有一份 `.1`"，**会吞掉历史** | 若我们的审计/事件做轮转则同类 | 审计与运行日志**按日期分段**（或外部归档），不要只留一份 `.1`；补磁盘容量告警 |
| 2 | 逐 thread 事件日志**无界** | 同类（长期运行必然增长） | 运行事件需容量/保留策略 |
| 3 | 审批人与**发起人可以是同一人** | 我们**不会**（已定"仅 ceo/超管 + 发起人不得自审"） | 保留，不因对方宽松而放宽 |
| 4 | 脱敏只覆盖"键名" | **是**——我们 `redact_payload` 只按键名 | 补"内容形状"脱敏并做**幂等**（否则改 hash） |
| 5 | 审计文件可被删改 | **待自查**：`app/audit/store.py` 是否存在 DELETE 路径、DB 是否有 REVOKE | 列入验收项 |
| 6 | 金额/费用用浮点 | **待自查**：`usage_ledger` 与费用展示是否全整数分（`daily_budget_cents` 已合规） | 列入验收项 |
| 7 | 跨进程无行级并发控制 | **待自查**：生产是否强制 `state_postgres`（`state.py` 自认内存态为已知限制） | 列入验收项 |
| 8 | 用户无"导出/删除自己数据"接口 | **是同类**（我们一期不含会话物理删除） | 合规（宪法九章）需归档 + 保留策略补位 |

---

## 6. ⭐ U1 可取证问题清单（改写版 · 建议作为段二-1 模板）

> 原文问法缺判据：即使实测"能跑通"，也无法区分三种可能（宿主发起 / 容器发起但凭据由宿主注入 / 容器自称发起）。

| # | 现象 | 判据 | 成立边界 | 不成立边界 |
| --- | --- | --- | --- | --- |
| **A** | 一次真实 turn 期间，容器内与宿主上**同时**抓指向模型供应商域名的出站连接，记录建立连接的 PID / 路径 / 网络命名空间 | 出站连接恒来自**容器外**的 PID，且容器命名空间内无该连接 | 发起方 PID 不在容器 PID 命名空间内，父链指向工作台/适配器进程 → **位置维度成立** | 发起方 PID 在容器内 → **不成立**，§3.3"模型调用由工作台侧发起"前提失效，须改设计 |
| **B** | 跑通真实 turn 的**同时**：`env` 全量、`/proc/*/environ` 全量、`inspect` 的 mounts/env、容器内全盘 grep 已知密钥值 | 四处**均无**该密钥明文（或前缀/哈希） | 四处皆无，**且清空宿主侧该密钥后 turn 立即失败**（因果证据） | 任一处命中；或"清空宿主密钥后仍成功"（说明容器内有独立凭据） |
| **C** | 保持 `--network none` 跑真实 turn | turn **仍成功**（含流正常结束、无 `AUTH`/超时） | 成立即为**强证据**：宿主发起、容器无网络面 | turn 因网络失败 → 调用链经过容器网络 → 回到 A 定位发起方 |
| **D** | 容器内 `ps -ef` 的 PID 1 树里能否找到 dsh / node 进程 | 借"**谁 spawn 谁持凭据**"口径 | dsh **不在**容器 PID 树内、父进程是工作台/适配器 → 与对方同构 → **成立** | dsh 是容器内节点 → 与密钥同处一个信任域 → **须重新论证**（很可能不成立） |
| **E** | 容器与宿主分别 `ps -ef` / 读 `/proc/<pid>/cmdline` | 借其 `SECURITY.md` 的硬判据："**argv 在 `ps` 里可见就是漏洞**" | argv/env 均无密钥、无内网地址、无工作台控制端点 | 密钥出现在任何 cmdline → **立即判不成立** |
| **F** | 执行侧回调工作台（导出产物/请求授权）时拿到的是什么凭据、生命周期多长、kill turn 后是否立即失效 | 借 §4-E 的六条形态 | 满足六条且**不持有任何供应商 API Key** | 拿到开机固定的共享令牌 → 不成立（对方明确点名为反模式） |
| **G** | 容器内能否自行联网；dsh 的 `web_*` 是否真禁用；容器 env 是否存在任一供应商 key | 前置清单已实测：`dsh-web-search-deepseek` **读 `DEEPSEEK_API_KEY`**，容器里只要有它**就能自行联网** | 容器 env **不存在**任何供应商 key，且 `--network none` 下 `web_*` 真实调用不可用 | 存在任一供应商 key → **同时**违反 A4 与 U1 |

**三条统一红线（任一命中即判"不成立"）**：
1. **清空宿主侧模型凭据后，真实 turn 仍成功**。
2. **容器 PID 命名空间内存在一个能出网、且持有模型凭据的进程**（不论它叫不叫 dsh）。
3. **密钥以明文出现在任何 `argv` / `env` / 容器 spec / 镜像层 / 日志**，或 `--network none` 下仍能触达供应商域名。

> **纪律**：四条必须**同时**成立；任何只有静态证据、无运行期证据的，按段二规格 §8 纪律标「**未核实**」，**不得计入成立**。

---

## 7. 对我方既有文档的更正（本轮复核发现）

[P2c 交互模式借鉴清单](file:///d:/徐徐AI学习/公司工作台/docs/p2c-interaction-study.md) §4 的可借项**混用了两个项目的证据且未逐行标注来源**，本轮回填更正：

| 行 | 原状 | 更正 |
| --- | --- | --- |
| A 内联审批卡 | 归 OpenMausBot | ✅ 成立，但**形态需修正**：决议不是"卡上按钮"，而是**接管输入区**；且它走独立 `respond` 端点（与我方"前端只是入口、不新增后端契约"需在 P2b 选路） |
| B 一行流 | 归"对方" | ✅ 在 OpenMausBot 成立，但**"原始入参"是脱敏且有界的**（≤200 条、best-effort redaction）——与我们口径一致 |
| C 产出 chip | 归"对方" | ❌ **实为 OpenWorkBuddy**；OpenMausBot 的产出走**附件**，无 chip 栈 |
| D 权限"关掉即摘掉" | 归"对方" | ⚠️ **只在 MCP surface 上成立**（Off 时 mcpConfig 不含该 server，并用系统提示告知模型）；**对 shell 审批恰好相反**（它没有 app 侧白名单） |
| E 收尾"未打勾就退回" | 归"对方" | ❌ **实为 OpenWorkBuddy**；OpenMausBot 只有**展示**（Verify 卡），**无强制退回**路径 |
| F 模型灰显给原因 | 归 OpenMausBot | ✅ 方向成立，但**形态是"一个聚焦动作 + 原因 + 整屏 setup 态"**，不是灰显墙 |
| G 性能 19.7s→0.7s | 编号归 OpenMausBot | ❌ 数字出自 **OpenWorkBuddy**；OpenMausBot 的真机制是 §3.5 那套结构手法，**且它不渲染 partial text** |
| H 域名白名单边界 | 归"对方" | ⚠️ OpenMausBot **无此断言**（`evilexample` 全库无命中）；但其**日志/登录域校验**确有正确写法 `host === allowed \|\| host.endsWith("." + allowed)`，可作参考 |

→ 已在 §4 表中逐行补来源标注；本文件不替代原清单（原清单仍是 P2c 输入，本文件是它的**证据回填与更正**）。

---

## 8. 未核实与独立性声明

**未核实**（不得作为设计前提）：
1. **未安装、未运行、未截图比对**——全程静态源码阅读，未跑它的测试、未启动应用。
2. 「十万字流式 19.7s → 0.7s」属 **OpenWorkBuddy** 宣称，在 OpenMausBot 全库无命中，**未复现**。
3. 其 `pnpm-lock.yaml`（1000+ 依赖）**未逐包核对许可**；"无非宽松许可"仅限 `third_party/**` 与直接依赖。
4. Local VM 容器的**实际出网能力**未运行验证（仅静态读 args 未见 `--network`）。
5. `electron/cua-linux.cjs` 的 GNOME/Wayland 分支与 `capabilities.cjs` 的"Wayland 一律不可用"最终生效层未追踪。
6. 我方 §5.2 的 8 条自查项**均未自查**（审计删除路径、费用是否整数分、是否强制 `state_postgres` 等）。
7. 我方 U1 的原始实测数据未重跑（前置清单自述"仍未取到"）。

**独立性声保**：本报告由 5 个互不共享推理的只读视角产出 + 汇总方**亲自复核 7 条**（`approval-levels.md` 的"不判定"口径、容器 run args、`server.listen` 绑定硬编码、`redact.ts` 保形幂等掩码、`LICENSING.md` 的 `enterprise/` carve-out、`store.tsx` 的 `decideRequest` 回流、`linux-desktop.md` 的 Wayland fail-closed 与环境变量不可绕过）；**未修改任何文件、未执行 git 写操作、未向其仓库或本项目引入任何代码**。

> **汇总方偏差声明**：本报告的"可借鉴"排序含汇总方判断，属**建议**，不构成决策；涉及我们范围/契约/阶段的结论须经评审。

---

## 9. 结论与下一步

1. **它的最大价值不是代码，而是三条判据**：谁 spawn 谁持凭据、能力旗标必须同时门控"挂载与提示"、恢复前先判"重放是否安全"。**U1 取证清单（§6）建议立即纳入段二-1**。
2. **它的权限模型不可作对照实现**——方向与我们的九步闸门相反，且多处是**反例**；我们的更严条目**必须原样保留**。
3. **不建议复用其代码**：能借的（契约纪律、脱敏、SSE supervisor、前端结构手法）都可**自行实现**；而它的实现绑在"单机 + 宿主 CLI + 进程内总线"形态上，移植成本大于收益，还会引入 `enterprise/` 与 MPL 许可的核对负担。
4. **本报告不改变任何既有排序**：段二（P2a-2）→ P2b → P2c；P2c 相关项仍按 D1–D4 裁决"随 P2c"。
5. **建议的下一步**（须你裁决）：
   - **① 把 §6 的 U1 取证清单登记进段二前置清单 §B**（作为段二-1 的交付判据）；
   - **② 把 §5.2 的 8 条自查项登记为待办**（其中 3 条涉及我们既有实现的合规/质量，值得独立核查）；
   - **③ 归档本报告**并在 [P2c 借鉴清单](file:///d:/徐徐AI学习/公司工作台/docs/p2c-interaction-study.md) 中回链（已在本文件 §7 完成更正）；
   - **④ 维持**"不复用其代码"的默认口径。
