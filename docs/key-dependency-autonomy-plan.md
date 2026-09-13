# 关键依赖自主可控方案

> **性质**：**方案（待评审）**。回答一个具体问题：**如果某个上游闭源、删库或停更，我们靠什么继续活下去、继续演进。**
> **触发**：2026-09-13 用户提出「上游哪天不开源了，适配器还有什么用？我需要一套能自主控制的」。
> **建立依据（既有要求，此前未落地）**：本项目在 **4 处**文档里已经要求过"退出方案"，但一次也没做——[POC 计划 `:113`](superpowers/plans/2026-09-06-agent-runtime-poc.md)、同文件 [`:122`](superpowers/plans/2026-09-06-agent-runtime-poc.md)、[commercial-g0 设计 `:163`](superpowers/specs/2026-09-06-commercial-g0-design.md)、[POC 设计 `:165`](superpowers/specs/2026-09-06-agent-runtime-poc-design.md)。**本方案就是把那 4 处收口。**
> **日期**：2026-09-13

---

## 1. 先把"自主可控"定义清楚（否则会讨论成"要不要搬代码"）

**自主可控 = 同时满足以下四条**（缺一不可）：

| # | 条件 | 说明 | 为什么它才是判据 |
| --- | --- | --- | --- |
| **①** | **许可允许永久使用与修改** | MIT / Apache-2.0 等宽松许可的授权**永久且不可撤销** | 只要拿过那一版，**上游闭源/删库不影响我用、改、分发那一版** |
| **②** | **能离线复现构建并运行** | 有源码/镜像归档，**断网也能构建起来、跑起来** | 这是"生存能力"的真正载体；做不到 ②，①就是纸面权利 |
| **③** | **有自维护能力** | 有人/有知识能改它、能修漏洞、能跟着我们的需求演进 | 决定"能不能继续长"，而不是"能不能活着" |
| **④** | **有替换/退出路径** | 知道换成谁、迁移成本多大、什么时候触发切换 | 决定"要不要被要挟" |

> **关键澄清（本项目内部曾混淆）**：**"把源码搬进我们仓库" ≠ 自主可控**——它只改变"存放位置"。搬进仓库后，上游闭源你**同样只能停在旧版本自维护**，结果与"**归档一版 + 自维护**"**完全一致**，但多背三笔账：**许可义务、与上游永久分叉、漏洞自修**；若是 GPL / 非商用许可，搬 = **违约**。
> **因此：第 0 层用"归档 + 可复现构建"，而不是"搬进仓库"。**

---

## 2. 为什么这个担心是真的（证据，不是假设）

**许可会变（已见诸事实）**：

| 项目 | 许可实况 | 对我们的影响 |
| --- | --- | --- |
| OpenMausBot | **自身从 MIT 迁移到 Apache-2.0**（其 `NOTICE` 自述） | 许可可改 → 不能假设"今天是 MIT 明天还是" |
| Dify / FastGPT | **修改版 Apache-2.0**（多租户运营需书面授权、前端品牌不可移除） | 看着像开源，实际有附加限制 |
| n8n | Sustainable Use License（禁对外 SaaS） | 同 |
| MaxKB | GPL-3.0（强传染） | 与我们闭源商业形态不兼容 |
| EvoFlow / OpenWorkBuddy | **非商用许可** | 只能提炼设计，**禁止搬运** |

**上游会停更/闭源/被收购**：`dsh` 目前是 **RC**（一个月 22 个版本、已发生三代会话格式迁移）——**变更是已发生的事实，不是风险假设**。

---

## 3. 分层策略（本方案的主体）

### 第 0 层 · 归档 + 可复现构建 + 断网演练（**解决"哪天不开源"，零许可风险**）

对**每一个关键依赖**做到：

1. **版本钉死**（禁 `latest`/`main`/`head`；本项目已有此规则，见 `tests/test_frontend_dependency_pins.py` 同类守护）；
2. **归档**：源码 tarball / 容器镜像 / 依赖 lockfile，放到**我们自己的内网位置**（私有 registry 或受控归档目录），**不只依赖上游仓库可访问**；
3. **可复现构建**：只凭归档 + 内网镜像，**能重新构建出可运行产物**；
4. **断网演练**：在**断网**环境下跑一次「构建 → 启动 → 跑通一条最小链路」，**留存原始输出**；
5. 演练通过后登记：**归档位置、校验和、构建命令、演练日期**。

> 做完第 0 层，上游删库/闭源对我们的影响**从"生存"降级为"只是不能升级"**。
> **这是本方案的第一优先级**，且**现在就能做，不需要等段二评审通过**。

### 第 1 层 · 可搬的搬（**严格限定的例外**）

仅当**四条同时满足**才把第三方源码 vendor 进本仓库（判据见 [`architecture.md` §外部集成的判据](architecture.md)）：

1. 许可**宽且可商用**（MIT / Apache-2.0 等）；
2. 是**无状态窄组件**（不是整套引擎/平台）；
3. **进程边界传不过去**（性能、原子性、事务性要求）；
4. 我们**愿意并有能力长期维护**它。

**当前明确不满足**（因此**不搬**）：`dsh`（整套 harness）、`OpenClaw`（整套 Gateway 平台）、`Codex`（Rust 内核）、`Hermes`（整套 agent）；`OpenWorkBuddy` / `EvoFlow`（非商用，**连看代码之外的使用都不允许**）。

### 第 2 层 · 一定自研（**不可外包的核心**）

| 层 | 内容 | 状态 |
| --- | --- | --- |
| 治理 | 九步闸门、授权位（`026`/`027`）、审批与授权闸门、四档风险 | 段一已交付 / 段二在规格中 |
| 隔离 | 容器执行器、最小挂载、无长寿命凭据、镜像 digest | 段二（未开工） |
| 数据 | 多租户隔离**写进数据库约束**、审计不可篡改、幂等、迁移链 | 已交付 |
| 沉淀 | **P3 记忆层 / P4 技能层 / P6 自进化** | **未开工——这三层决定我们最终是不是"套壳"** |

> **口径**：通用引擎（agent 主循环、模型接入、浏览器驱动）**不自研**（不重复造轮子）；**但治理/隔离/审计/沉淀必须自研**——本项目的调研已写明「**多租户 + RBAC + 审计 + 审批是开源生态的集体空白**」，**这层没有现成轮子**。

### 贯穿 · 退出方案（每个关键依赖一页）

固定四问：**① 如果它明天闭源/停更，我怎么办？② 换成谁（候选≥1）？③ 迁移成本多大（人日/风险）？④ 触发切换的条件是什么？**

---

## 4. 关键依赖清单（逐项四问）

| # | 依赖 | 类型 / 现状 | 许可 | 第 0 层（归档+断网构建） | 退出方案 |
| --- | --- | --- | --- | --- | --- |
| 1 | **`dsh`（`@deepseek-ai/dsh`）** | 段二执行引擎（**未接入**，段二未开工）；上游 **RC**；**探针位置已核实（2026-09-13）**：仓库外 `d:\徐徐AI学习\_dsh-verify\`（含 `package-lock.json`、`package.json`、`.env.dsh.txt`、**安装树 `node_modules`（2026-09-13 已核实存在）**） | 246 条目 = 241 MIT + 5 BSD-3；**无 GPL/AGPL**；LGPL 来自 `sharp` 生态（**2026-09-13 实测更正：随镜像 `@img/*` 为 4 个、含 LGPL 2 条**，见段二前置清单 §F7.4） | 🟡 **部分完成（2026-09-13）**：**离线归档包 + 校验和 + 断网演练已就绪**——`dsh-0.1.5-rc.1-offline-archive.tar.gz`（52 MiB，sha256 `3ceb0178…e811`）；**另含基础镜像归档** `node-22-slim-image.tar`（79 MiB，sha256 `d19c3368…7029`；**镜像 RepoDigest `node@sha256:83f487e0a634…`**，**digest 形式**，可对齐段二规格 §4 的 `WORKBENCH_EXEC_IMAGE_DIGEST` 口径）；**`--network none` 下**纯离线装出 522 包、最小链路 exit 0 / 352 行、**输出与期望逐字节一致**，且**基础镜像可离线恢复**（§10.6）。**仍待搬运到内网受控位置** —— ⏸ **P0-2 于 2026-09-13 按用户裁决（选项 D）暂时挂起**（恢复条件见 §5 / §8 第 1 项） | ✅ 见 **§9-1** |
| 2 | RAGFlow / AgentScope | 知识层 / 受控执行器（**适配器**，需 HTTPS + 认证注入） | **未核**（见 §8） | ❌ 未做 | ✅ 见 **§9-2** |
| 3 | WeKnora | 企业知识服务（**适配器**） | **未核**（见 §8） | ❌ 未做 | ✅ 见 **§9-3** |
| 4 | DeerFlow / Codex Worker / Hermes | 本地独立进程（**适配器**，`http://127.0.0.1:91xx`） | DeerFlow 待核；Codex Worker = **Apache-2.0**；Hermes = **MIT** | ❌ 未做 | ✅ 见 **§9-4** |
| 5 | GEO | 业务外部系统（版本化适配器） | 对端契约 | 不适用（对方系统） | ✅ 见 **§9-5** |
| 6 | PostgreSQL + pgvector / Redis / 对象存储 | 基础设施 | 宽松（**具体版本与镜像未登记**） | ❌ 未做（官方镜像归档未登记） | ✅ 见 **§9-6** |
| 7 | Electron / Node / Python 运行时 | 三端与后端运行时 | 宽松 | ❌ 未做 | ✅ 见 **§9-7** |

> **§4 的"退出方案"列已由 P0-4 补齐**（2026-09-13）→ 逐项四问见 **§9**。
> **"归档位置 / 校验和 / 构建命令 / 演练日期"四列本表尚未填写**——属 **P0-2 / P0-3 / P0-5**（需内网存储与可断网环境，见 §8）。
> 存量核对面见 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md)（许可状态）与段二前置清单 §B13 / §F5（dsh 许可细节）。

---

## 5. 立即执行项（P0，按顺序）

| # | 事项 | 判据（怎么算做完） | 依赖 |
| --- | --- | --- | --- |
| ~~**P0-1**~~ ✅ **已完成（2026-09-13）** | 确认 `dsh` 探针/构建当前位置 | 位于**仓库外** `d:\徐徐AI学习\_dsh-verify\`，含 `package-lock.json`、`package.json`、`.env.dsh.txt`、**安装树 `node_modules`（2026-09-13 已核实存在）** | 无需外部输入 |
| **P0-2** ⏸ **挂起（2026-09-13 用户裁决 D）** | **归档 `dsh` 钉死版本**（lockfile + npm `_cacache` tarball 存储 + 期望输出），并**落到内网受控位置** | 归档包**已就绪且含校验和**（`MANIFEST.md` §3）、**不依赖上游可访问**（断网演练已证）；❌ **"落到受控位置"未闭环** —— 经三轮排查确认**本机无此位置、也无任何内网入口**（证据见 §8 第 1 项） | **恢复条件**：用户指定一个**受控归档位置**（内网 NAS / 制品库，**或**云对象存储——后者属**口径变更**，须用户明确接受） |
| **P0-3** ✅ **已完成（2026-09-13）** | **断网构建演练**：用归档构建出可运行产物并跑通最小链路，**留存原始输出** | ✅ **已留存**：`--network none` 容器内**纯离线**装出 **522 包**、最小链路 **exit 0 / 352 行**、**输出与归档期望逐字节一致**；**另含基础镜像的离线恢复**（`rmi` → `load` → ID 与 5 层摘要逐条一致 → 恢复后可用，见 **§10.6**）。原始日志 `_dsh-offline-verify\out\01~05-*.log`，及归档 `MANIFEST.md` §4 | ✅ 已用**网络命名空间隔离的容器**替代"断网机器"（可复现性更强，且不依赖额外硬件） |
| ~~**P0-4**~~ ✅ **已完成（2026-09-13）** | 逐个补 **7 项依赖的退出方案**（§3 贯穿四问） | ✅ **7/7 已补，见 §9**；每项候选替换目标 ≥1。⚠️ **但"退出路径已就绪"不成立**——§4 第 0 层只 **`dsh` 一项部分落地（P0-2 待搬运）**，其余 6 项仍未做 | 无需外部输入 |
| **P0-5** | 把上述结果回填 §4 表格与 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md) | 四列填满 | P0-2~P0-4 |

> **P0-1 / P0-3 / P0-4 已完成（2026-09-13）**；**P0-2 已按用户裁决（选项 D）于 2026-09-13 暂时挂起** —— 归档包已就绪，**恢复条件 = 用户指定一个受控归档位置**；**P0-5 随 P0-2 一并挂起**。
> **其余 6 项依赖的第 0 层已完成侦察（见 §11）**：结论是**只有 #6 / #7 可立即归档**（在用且有实物），**#2/#3/#4 未接入故无版本可归档**，**#5 不适用**；**并查出 3 个真缺口**（① 后端无 lockfile ② Redis/MinIO 钉死 tag 本机缺失 ③ 基础镜像用 tag 而非 digest）。**真归档动作同样卡在"目的地"。**
> ⛔ **挂起 ≠ 闭环**：**第 0 层判据 ① 仍未闭环 ⇒ 上线自检必须包含本项，且仍不得宣称"关键依赖可自主控制 / 不依赖上游开源状态"**。

---

## 6. 与既有文档的关系

| 文档 | 关系 |
| --- | --- |
| [`architecture.md` §外部集成的判据](architecture.md) | 提供"接适配器 vs 搬代码"的**三问判据**；本方案第 1 层直接引用它，不重复 |
| [`poc-license-checklist.md`](superpowers/poc-license-checklist.md) | 提供**许可核对状态**；本方案负责它明确要求过、但一直没做的"退出方案"与"版本锁定归档" |
| 段二规格 §4 / §8 U13 | dsh 的许可与镜像口径来源；本方案的归档演练是其**上游前置**（不改段二范围） |
| 段二前置清单 §B13 / §B15 | 许可证与配置守护；本方案不替代它们 |

---

## 7. 明确不做（防范围蔓延）

1. **不搬非宽松许可的代码**（EvoFlow、OpenWorkBuddy 等）——**违法/违约风险**，不在本方案讨论范围；
2. **不搬整套引擎/平台**（dsh / OpenClaw / Codex / Hermes）——按 §3 第 1 层的四条判据，**均不满足**；
3. **不为"将来可能闭源"提前 fork**——第 0 层（归档 + 可复现构建）已覆盖该风险，fork 只会带来分叉成本；
4. **不改任何既有架构决议**（P2a→P2b→P2c 顺序、段二范围）。

---

## 8. 未决与待核实

1. **内网归档位置**未定（**待用户提供**）→ **P0-2 只差这一步**：归档包已生成于 `_dsh-offline-verify\dist\`（含 `MANIFEST.md` 校验和清单），**搬过去并登记位置即可收口**。
   - **2026-09-13 本机排查结论（只读）**：**本机不存在可用的"内网受控位置"** —— 仅本地 `C:`/`D:` 两块盘；**无映射网络驱动器**（`net use` 列表为空）；**`net share` 仅默认管理共享**（`C$`/`D$`/`IPC$`/`ADMIN$`，**无自定义共享**）；**未加入域**（`Workgroup=WORKGROUP`，`PartOfDomain=False`）；**npm 源为公网** `registry.npmjs.org`（无私有源）；**Docker 无私有 registry、无镜像加速**；`hosts` **无内网主机条目**；项目 git 远端为**公网 GitHub**（`github.com/xuxuWD/cangku`）。
   - **2026-09-13 第二轮（更深，仍只读）**：**记住的网络位置**（`MountPoints2`）**无任何 UNC 形态条目**；**资源管理器手输路径**（`TypedPaths`）**仅本地路径**；**无持久盘符映射**（`HKCU:\Network` 空）；**无 SMB 映射/会话**（`Get-SmbMapping`/`Get-SmbConnection` 空）；**SSH 已知主机仅 `github.com`**（无内网主机）；**未配置任何云/对象存储**（`.aws`/`.s3cfg`/`.ossutilconfig`/`rclone`/`mc` 全部不存在）；**Docker 无 registry mirror / proxy 配置**；**WinHTTP 无代理**（直连）；**ARP 邻表**仅见各自网关（`192.168.28.33`、`198.18.0.x`），**未见 NAS 类主机**。
   - **2026-09-13 网络面结论**：本机位于 `192.168.28.0/24`（WLAN）与 `192.168.1.0/24`（以太网）两个**普通局域网**；`PulseVPN` 只持有自己的 `198.18.0.1/30`（**fake-IP 段，代理式 VPN 特征**），**路由表中没有任何企业/内网网段** ⇒ **即使公司侧存在 NAS/制品库，本机当前也看不到它**。
   - **2026-09-13 局域网扫描（用户授权后执行）→ 结论：本机无内网存储入口；且本轮端口结论作废**
     - **网卡实况**：**`以太网` = Disconnected（未插线）**；**`WLAN` 唯一连接 = 手机热点 `SSID=k40`**（网关 `192.168.28.33`，仅 DNS/53 应答）；`PulseVPN` 为**代理式 VPN**（fake-IP 段 `198.18.0.0/15`）。⇒ 本机当前**根本不在任何公司/内网里**。
     - **🔴 方法失效（如实登记）**：TCP connect 探测在当前网络下**几乎全部返回"开放"**。**对照实验**（`203.0.113.7:445` = TEST-NET-3 **不可路由**、`10.0.0.1:445`、`192.168.1.1:12345`、`192.168.1.1:65000`）**同样返回 True** ⇒ **本地代理/PulseVPN 接受了所有 TCP 连接**，**"端口开放"系假阳性**。
     - ⇒ **本轮端口结论一律作废**；仅**存活主机/ARP/网卡状态**层面的观测仍有效。严格结论只能是：**"当前网络环境下，无法从本机发现任何内网存储入口"**（不能推广为"局域网内无 NAS"）。
     - ⚠️ **纪律**：将来在**真正的公司内网**重扫时，**必须先用对照实验验证探测方法本身**（对照通过后，结果方可采信）。
      - **原始输出留档**（扫描日志文件已按用户指示删除，关键行在此留档）：`PING_ALIVE_COUNT=1` → 仅 `192.168.28.33` 存活；端口探测段**无任何 HOST 行**；候选文件/存储服务 = `(none)`；`done`。
   - **2026-09-13 第三轮（凭据管理器 / SSH 客户端 / 虚拟机）**：**凭据管理器**（`cmdkey /list`）目标**全为个人/公网**（QQ 邮箱、GitHub、Docker Hub、`dhi.io`、剪映），**无任何 `\\服务器\共享` 或域凭据**；**WSL** 仅 `docker-desktop` 工具发行版（无用户 home / SSH）；**FinalShell** 保存的唯一服务器 = **`192.168.25.128:22`，名称 `KylinOS`**（**VMware NAT 网段**典型值）；经查 **VMware 已卸载**（注册表无卸载项、三处常见安装路径均不存在、**无 VMware 服务**、**无防火墙规则**），该 VM 属**本机遗留文件**（`D:\Virtual Machines\KylinOS\KylinOSv11.vmdk`，7.84 GB，**最后使用 2026-05-07**），**当前关机且无法启动**。
   - ⇒ **综合三轮排查结论**：**本机从未连接过任何公司/内网服务器**；"**内网受控位置**"**既不存在、也无任何入口**（不是"没找到"，而是**从未建立**）。
   - **⏸ 2026-09-13 用户裁决（选项 D）：P0-2 暂时挂起。**
     - **恢复条件**：用户指定一个**受控归档位置**（内网 NAS / 制品库；**或**云对象存储——**后者属口径变更，须用户明确接受"受控但不内网"**）。
     - **挂起期间的状态**：归档集继续存放于本机 `_dsh-offline-verify\dist\`（131 MB，含 `MANIFEST.md` 校验和清单），**真源一律不标"已受控"**；**P0-5 随之挂起**。
     - **后果（不可忽略）**：**第 0 层判据 ① 未闭环 ⇒ 上线自检必须包含本项**，且**仍不得对外宣称"关键依赖可自主控制 / 不依赖上游开源状态"**。
   - ⛔ **纪律**：**不得用本机目录（哪怕新建一个专用目录）冒充"内网受控"** —— 它与开发机同处一个信任域与同一块盘，满足不了 §3 第 0 层的"不依赖上游仓库可访问 + 受控"含义。
   - ℹ️ 观测到本机存在 **`PulseVPN` 网络适配器**（可能通向公司/内网），但**无任何内网主机线索**（`hosts` 空、无映射盘）；**是否需要经它访问内网存储，须用户确认**。
2. ~~**可断网演练环境**未定（**待用户提供**）→ 阻塞 P0-3~~ → ✅ **已解决（2026-09-13）**：用 **`--network none` 的网络命名空间隔离容器**完成演练（不依赖额外硬件），并**用归档自证**（解包→纯离线安装→最小链路输出与期望逐字节一致）；
3. ~~`dsh` 探针/lockfile 的当前所在位置~~ ✅ **已核实（2026-09-13）**：位于仓库外 `d:\徐徐AI学习\_dsh-verify\`（`package-lock.json` + `package.json` + `.env.dsh.txt`）；**含安装树 `node_modules`（2026-09-13 二次核实：存在）** → 影响 P0-2 的归档范围（**归档须含安装树或等价可复现安装方式**）；
4. RAGFlow / AgentScope / WeKnora / DeerFlow 的**许可未逐个核**（不在本轮范围）→ **§9-2 / §9-3 / §9-4 的候选替换目标中，凡涉许可者一律标"待核"**；
5. 本方案**未评审**；**P0-1 / P0-3 / P0-4 已完成（2026-09-13）**——P0-4 见 **§9**、**P0-3 见 §10**；**P0-2 归档包已就绪、只差搬运**（需内网归档位置）；**其余 6 项依赖的第 0 层已完成侦察（§11）**，其中**缺口①（后端 lockfile）已完全闭环（§11.5~§11.7）、缺口③（镜像 digest / Node 版本）已修（§11.9）、缺口②仅剩 MinIO（§11.8）**。
6. ~~**MinIO 镜像不可获取**~~ → ✅ 当时**已按选项①换源到 `quay.io/minio/minio` 并钉死 digest**（quay 上有同一 release，纯换源不动版本；详见 **§11.8**）。⚠️ **该处置已于同日被替换取代** —— 对象存储现为 **SeaweedFS**（见第 7 项与 **§11.12**）。
7. ✅ **已裁决并落地（2026-09-13）：对象存储由 MinIO（AGPLv3）换成 SeaweedFS（Apache-2.0）** —— 依据用户已定原则"**不引入 copyleft**"；候选取证见 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md)【MinIO 替代候选取证】；**实施与验证详见 §11.12**。
   - 🔑 **当初的成本判断（已被实测印证）**：`object_storage_url` **当时没有任何应用代码在用**（全仓无 S3 客户端调用）⇒ MinIO 处于"已声明、未接入"，**替换代价最低** —— 事后证明改动仅**compose 一处 + compose.app 一行 URL**。
8. 🔴 **`redis:7.4-alpine` 内的 Redis 7.4.11 是 `RSALv2 + SSPLv1` 双许可（source-available，非 OSI 开源）** —— RSALv2 明文**禁止把其功能作为服务提供给第三方**，SSPLv1 另含**服务化即须开源整个服务对应源码**的义务。**已取证**：上游 `LICENSE.txt` 原文 @ tag `7.4.11`；**四条路径全部取证**（① 维持 `7.4.11`〔RSALv2/SSPLv1〕② 升 8.x 并**显式选 AGPLv3**（原文为**三选一**）③ 回退 7.2（**BSD-3**）④ 换 **Valkey（BSD 3-Clause）**）—— 详见 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md)【Redis 相关许可的四条可选路径】。
   - ✅ **已裁决（2026-09-13，用户裁决）：选 ④ —— 换 Valkey（BSD 3-Clause）**。**依据**：交付形态 = "**现在内部，将来可能对外**"（⇒ **排除 ①**：对外服务化时 RSALv2 会实质命中）；对 copyleft 态度 = "**宁换实现也不引入 copyleft**"（⇒ **排除 ②** 的 AGPLv3 义务**与 ③** 的降级）。
   - ✅ **已实施（2026-09-13，用户批准）—— 六步全部完成，详见 §11.11**：① `valkey/valkey:8-alpine` 可得，**Valkey 8.1.10**，digest `sha256:d2e18f34…43d1`；② 许可正文按 **tag `8.1.10`** 取回 ⇒ **两份 BSD 3-Clause（无 copyleft）**；③ `docker-compose.yml` 已换为 `valkey/valkey:8-alpine@sha256:d2e18f34…43d1`（**服务名仍为 `redis`**，因 `WORKBENCH_REDIS_URL` 与既有测试依赖该主机名）；④ **Streams 实测：用项目自身 [`RedisStreamEventBus`](file:///d:/徐徐AI学习/公司工作台/app/events.py#L87-L151) 真连 Valkey ⇒ `10/10 PASS`**（**含反假测试：坏地址必红；含对照组：同一套对 Redis 7.4.11 亦 10/10**）；⑤ 回归 **`1434 passed` + `compileall` 通过**；⑥ 已留痕（§11.11 / `change-record` / 许可清单 / 门禁）。**source-available 许可风险已由本替换消除（换来 BSD-3）。**
   - 🔗 **同一原则的连带影响**：按"不引入 copyleft"，**MinIO（AGPLv3）也需在对外交付前评估替换**；候选（SeaweedFS / Ceph RGW / Garage 等）**许可一律未核**，**不得凭印象认定某个候选宽松** ⇒ **独立议题，需另行取证 + 另行裁决，本轮未做**。
   - ℹ️ **一个有利事实**：客户端是 `redis` PyPI 包 + `Redis.from_url(...)`，且 [`worker_preflight.py`](file:///d:/徐徐AI学习/公司工作台/scripts/worker_preflight.py#L152) 只要求 URL 为 `redis://` / `rediss://` ⇒ **换服务端无需改应用代码**（协议与 URI 沿用），**改动面限于镜像与验证**。

---

## 9. P0-4：7 项关键依赖退出方案（逐项四问，**2026-09-13**）

> **模板（§3 贯穿四问）**：① 若它明天闭源/停更，我怎么办？② 换成谁（候选 ≥1）？③ 迁移成本多大？④ 触发切换的条件是什么？
> **口径三条（先读，否则会误读本节）**：
> 1. **本节只回答"四问"，不等于"退出路径已就绪"**——**第 0 层（归档 + 断网可复现 + 演练）仍未做**（§4 该列全为 ❌），而**第 0 层才是生存能力的载体**（§1 条件②）；
> 2. **迁移成本用相对量级 S / M / L + "要动哪些层"表达**；**人日一律不估、不承诺**（需按团队产能与目标引擎实测后填）；
> 3. **凡未在本项目文档中核过许可的候选，一律标"许可待核"**——**不得据此声称"可以换过去"**。

### §9-1 `dsh`（`@deepseek-ai/dsh`）

| 问 | 答 |
| --- | --- |
| **① 明天闭源/停更怎么办** | **不依赖上游仓库可访问**：已拿到的版本（`0.1.5-rc.1` + lockfile + 安装树）在其**宽松许可**下**可永久使用与修改**；闭源后**停在归档版本自维护**。**关键接缝是我们自己的**——dsh 全部细节封在 `AgentRuntimeAdapter` 之后（段二规格 §3.5），**上层（九步闸门 / 授权位 / 审计 / 容器边界）不受影响** |
| **② 换成谁（候选 ≥1）** | **≥3 个，全部走同一适配器契约**：(a) **`mock`（已存在）**——保底与回归；(b) **`hermes`（MIT ✅）**；(c) **`codex_worker`（Apache-2.0 ✅）**；(d) `deerflow`（**许可待核**）；(e) **自建最小 agent 循环**（只做"工具调用 + 会话"，复杂能力继续靠自研治理层） |
| **③ 迁移成本** | 相对量级 **M–L**。**要动**：适配器内部实现（stdio 协议 / profile 装配 / 禁用清单 / 凭据注入）、段二 **§B14 取证全部重做**、镜像与 `THIRD-PARTY-NOTICES` 重做。**不必动**：闸门、`026`/`027`、审计、容器边界。**人日待估** |
| **④ 触发切换** | 上游**闭源 / 删库 / 停更**（建议阈值：**连续 2 个发布周期无发布**，可调）；**许可变更**引入附加限制；RC→正式版的**不兼容变更连续两版无法消化**；上游被收购并改条款 |

### §9-2 RAGFlow / AgentScope（知识层 / 受控执行器）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | 两者都是**适配器**、**非核心**。闭源后退回**自建检索**：本项目基础设施**已有 PostgreSQL + pgvector**（§4 第 6 项）→ 用 pgvector 做向量检索，**权限过滤必须在我们侧**（多租户 + RBAC 本就不能外包）；AgentScope 那种"受控执行器"角色 → 退回**段二自研的容器执行器**（§3 第 2 层） |
| **② 候选** | 自建 pgvector 检索服务（**首选，无外部许可风险**）；其它 RAG 引擎（**许可待核**）；**兜底降级形态**＝文件级检索 + 人工维护知识条目 |
| **③ 迁移成本** | 相对量级 **M**（检索质量、切分与排序策略需重调）。**要动**：知识层适配器 + 索引管线；**不动**：权限模型、审计。**人日待估** |
| **④ 触发** | 许可**未核/不允许其形态**；对端不再提供 HTTPS + 认证注入能力；召回或成本不达标 |

### §9-3 WeKnora（企业知识服务）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | 与 §9-2 **同形态**（外部知识服务适配器）：闭源 → **退回 §9-2 的自建 pgvector 检索** |
| **② 候选** | 自建 pgvector 检索（首选）；其它知识库产品（**许可待核**） |
| **③ 迁移成本** | 相对量级 **M**（同 §9-2，主要是索引与检索质量回归）。**人日待估** |
| **④ 触发** | 同 §9-2；**另加**：其服务端能力与我们的多租户隔离要求冲突时（宁可自建） |

> ⚠️ **前置**：**其许可未核** → **核清之前不得把它写进任何"已选定"口径**。

### §9-4 DeerFlow / Codex Worker / Hermes（本地独立进程适配器）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | 三者**互为候选**：同一适配器契约、同一进程形态（`127.0.0.1:91xx`）→ **任一停更即切到另一个**；**三者全停** → 退回 §9-1 的候选集合 |
| **② 候选** | 彼此（**≥1**）；**Codex Worker = Apache-2.0 ✅、Hermes = MIT ✅**（此两项**许可已清**）；DeerFlow **待核** |
| **③ 迁移成本** | 相对量级 **S**（同契约、同进程形态；主要是接线 + 回归用例重跑）。**人日待估** |
| **④ 触发** | 单项不可用 / 协议不兼容 / 许可问题；**任一停更不波及其余两个**（这是"多适配器共存"的价值，见 [`multi-adapter-coexistence-spec.md`](multi-adapter-coexistence-spec.md)） |

### §9-5 GEO（业务外部系统）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | **它不是开源依赖**，而是**业务对端系统**——"自主可控"在这里含义不同：靠**版本化适配器 + 契约冻结**，并**把关键动作保留人工可执行路径**（对方停服时业务仍能手工闭环） |
| **② 候选** | **业务上无等价替换** → 退出路径 = **降级到人工**（须写清：哪些动作可人工、SLA 如何降、谁执行） |
| **③ 迁移成本** | 适配器本身 **S**；但**业务影响 L**（要评估人工兜底的产能与时效）。**人日待估** |
| **④ 触发** | 对端**不兼容变更未提前通知**；停服；契约条款变更 |

### §9-6 PostgreSQL + pgvector / Redis / 对象存储（基础设施）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | 三者许可均宽松，**核心手段就是第 0 层**：**版本钉死 + 官方源码/镜像归档到内网 + 断网可重建 + 备份真跑过恢复**（§3 第 0 层） |
| **② 候选** | **PostgreSQL** → 策略是"**钉死 + 归档 + 可恢复**"，**跨库替换不建议**（MySQL/MariaDB 成本高、且 **pgvector 无对等物**）；**pgvector** → 独立向量库（Qdrant / Milvus / Weaviate——**许可待核**）；**Redis** → **Valkey**（Linux Foundation 分叉，BSD 系——**待核**）或 KeyDB（**待核**）〔背景：**Redis 许可近年多次变更**，是"许可会变"的现实例证〕；**对象存储** → 已按 **S3 兼容**接口使用 → 可换任何 S3 兼容实现（**待核**） |
| **③ 迁移成本** | 版本钉死 + 归档 = **S**（本就要做）；pgvector→独立向量库 = **M**（检索层改造）；Redis→Valkey = **S–M**（协议兼容度高，需回归）。**人日待估** |
| **④ 触发** | 许可/治理变更；版本 **EOL 且有未修安全问题**；单点故障；容量或成本不达标 |

### §9-7 Electron / Node / Python（运行时）

| 问 | 答 |
| --- | --- |
| **① 怎么办** | 运行时是**可归档资产**：**官方安装包 / 镜像 / 源码 tarball 归档到内网 + 版本钉死**（本项目已有钉死规则）。真正的风险不是"闭源"，而是 **EOL + 安全补丁** |
| **② 候选** | **Node** → 官方后续 LTS（自控升级节奏）；**Python** → 官方后续版本；**Electron** → 候选 **Tauri**（Rust），但**改动面很大**；**均无需替换亦可长期运行** |
| **③ 迁移成本** | 归档 + 钉死 + 定期评估 = **S**；Node/Python **大版本升级** = **M**；**Electron → Tauri = L**（三端壳重写级）。**人日待估** |
| **④ 触发** | 目标版本 **EOL 且无安全补丁**；上游引入不兼容变更；Electron 的分发/许可条款变化 |

### §9 小结（**必须与 §9 抬头口径一起读**）

- **四问已补齐 7/7**，每项**候选替换目标 ≥1**（§9-4 甚至互为候选）。
- ⛔ **但"退出路径已就绪"尚不成立**：**第 0 层只有 `dsh` 一项部分落地**——**校验和与断网演练已完成（见 §10）**，但**"归档位置"一列仍空（P0-2 待搬运）**，且**其余 6 项依赖全未做**。
- ⚠️ **许可未核者**：`RAGFlow / AgentScope / WeKnora / DeerFlow / 各类替代品与独立向量库` → 候选**只是候选**，核清前不得写成"已选定"。

---

## 10. P0-3 断网演练记录（2026-09-13）

> 判据要求"有演练记录（**命令 + 输出 + 日期 + 环境**）"——**本节即该记录**（原始日志另存于仓库外 `_dsh-offline-verify\out\01~03-*.log`）。

### 10.1 环境

| 项 | 值 |
| --- | --- |
| 宿主 | Windows + Docker `29.7.2`（linux / overlayfs / cgroup v2，WSL2 kernel `6.18.33.2`） |
| 镜像 | `node:22-slim` |
| Node / npm | `v22.23.2` / `10.9.8` |
| **网络** | **`--network none`**（除 loopback 外**无任何网络接口**；不访问 registry / 上游仓库） |
| 日期 | 2026-09-13（UTC 07:34–07:40） |

### 10.2 命令（容器内，逐字）

```sh
# ① 断网 + 纯离线安装（只用归档缓存）
npm ci --offline --cache=/npmcache --os=linux --cpu=x64 --libc=glibc --no-audit --no-fund
# ② 最小链路
node node_modules/@deepseek-ai/dsh/lib/bin.js --profile sdk --dump-default-config
# ③ 归档自证：解包归档 → 只用解出的缓存再装一次 → 与归档内期望输出比对
tar xzf dsh-0.1.5-rc.1-offline-archive.tar.gz -C /work/extract
cd /work/extract && npm ci --offline --cache=/work/extract/cache --os=linux --cpu=x64 --libc=glibc --no-audit --no-fund
node node_modules/@deepseek-ai/dsh/lib/bin.js --profile sdk --dump-default-config > dump2.yaml
diff -q expected-dump.yaml dump2.yaml
```

### 10.3 原始输出（逐字摘录）

**基线轮（断网 + 纯离线）**：

```
added 522 packages in 3m
NPM_CI_EXIT=0
PKG_DIRS=190
PKG_JSON_COUNT=554
DUMP_EXIT=0
DUMP_LINES=352
DUMP_ERR_HEAD=
```

**归档自证轮**：

```
EXTRACT_EXIT=0
extract_top=ENV.txt cache expected-dump.yaml offline-rehearsal.log package-lock.json package.json
9bc2239bd6e77cf89504bea3d99ebfd021961dbae7e832fddd16917492691915  /work/extract/package.json
9b2dca414c90083444af4e7cd02628c0a8629ceec854bbe0e786e62cb3d3297a  /work/extract/package-lock.json
added 522 packages in 3m
NPM_CI_EXIT=0
PKG_JSON_COUNT=554
DUMP_EXIT=0
DUMP_LINES=352
RESULT=MATCH (byte-identical to archived expected-dump.yaml)
b538c4bc40c92756fbfd306562bc0e57b6964b61e6ce91733b68721e55e19a68  /work/dump2.yaml
```

（解包后 `package.json` / `package-lock.json` 的 sha256 **与打包前完全一致**，即归档内容无损坏。）

### 10.4 归档指纹

| 对象 | SHA-256 |
| --- | --- |
| `dsh-0.1.5-rc.1-offline-archive.tar.gz` | `3ceb01786d246997bf874ddb57e429e43a2e4f8d618166bab1265971c492e811` |
| `package.json` | `9bc2239bd6e77cf89504bea3d99ebfd021961dbae7e832fddd16917492691915` |
| `package-lock.json` | `9b2dca414c90083444af4e7cd02628c0a8629ceec854bbe0e786e62cb3d3297a` |
| `expected-dump.yaml`（= 自证轮输出） | `b538c4bc40c92756fbfd306562bc0e57b6964b61e6ce91733b68721e55e19a68` |

- 归档包 **54,509,877 字节**（≈52 MiB）；npm 缓存 **56,532 KB / `_cacache` 1004 个文件**。
- 存放：**仓库外** `d:\徐徐AI学习\_dsh-offline-verify\dist\`（同目录含 `MANIFEST.md`）。

### 10.5 结论与边界（**必须与边界一起读**）

- ✅ **结论**：**只凭该归档、在无网络环境下，可完整重建 dsh 并跑通最小链路，且输出逐字节可复现** ⇒ 对 `dsh` 而言，§3 第 0 层的 ②（离线可复现构建）③（有产物）④（演练）**已取得证据**；**基础镜像的离线恢复已补测，见 §10.6**。
- ⚠️ **边界**：① 只覆盖 **`dsh` 本体**；② **模型调用未演练**（属段二 B14 范围，且**需要有效凭据**）；③ 演练环境是**网络命名空间隔离的容器**，非"另一台物理断网机器"（可复现性更强，但两者不完全等价）；④ **未**演练"内网私有 registry / Harbor"这种**分发形态**（本次是 `docker save` 文件形态，见 §10.6）。
- ⛔ **仍未闭环**：**P0-2 的"落到内网受控位置"未做** ⇒ **第 0 层判据未整条闭环**，**不得宣称"关键依赖可自主控制"**（与 §1 条件②的严格读法一致）。

### 10.6 补充：**基础镜像归档与离线恢复**（2026-09-13 同日）

**为什么必须补**：§10.1–§10.4 只覆盖 **npm 依赖**，**归档里没有基础镜像** —— 断网时连 `node:22-slim` 都拉不到，"可完整离线恢复"就是**不成立的**。补齐后，归档才构成**完整输入集**。

**归档**（`docker save node:22-slim` → `node-22-slim-image.tar`）：

| 项 | 值 |
| --- | --- |
| 大小 | **82,586,112 字节**（≈79 MiB） |
| SHA-256 | `d19c3368119d57164229e86d665b3b67ccf38353486fc0c750a0956f171e7029` |
| 镜像 ID | `sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5` |
| **RepoDigest** | **`node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5`**（**digest 形式**，可直接对齐段二规格 §4 的 `WORKBENCH_EXEC_IMAGE_DIGEST` 口径） |
| 层数 | **5 层**（摘要：`1d69a5fd…` / `34a6e01a…` / `4a5c8e86…` / `baa7a8b2…` / `72d01f9c…`） |

**恢复演练**（原始输出：`_dsh-offline-verify\out\05-image-archive-verify.log`）：

```
[3] docker rmi node:22-slim        →  Untagged: node:22-slim ; Deleted: sha256:83f487e0a634…
[4] IMAGE_ABSENT=True
[5] docker load -i node-22-slim-image.tar  →  Loaded image: node:22-slim
[6] ID=sha256:83f487e0a634…        ← 与删除前一致
    LAYERS=1d69a5fd… 34a6e01a… 4a5c8e86… baa7a8b2… 72d01f9c…   ← 5 层逐条一致
[7] docker run --rm --network none node:22-slim node -e …  →  RESTORED_IMAGE_OK node=v22.23.2 (exit 0)
```

⇒ **基础镜像可从归档完整离线恢复，且恢复后可用。**

**安全性说明（如实登记）**：删除前已确认**无任何容器依赖该镜像**（`docker ps -a --filter ancestor=node:22-slim` 为空）；且**先归档、后删除、随即恢复**，全程可用归档回滚。

**仍未做**：① 未演练"私有 registry / Harbor"**分发形态**；② 未演练**带登录/权限**的分发链路。

---

## 11. 其余 6 项依赖的第 0 层：**侦察清单**（2026-09-13）

> **性质**：**只做侦察（清单化），不搬归档** —— 归档目的地不存在（P0-2 已挂起，见 §8 第 1 项）。
> **结论先行**：**6 项里只有 #6 / #7 具备"可立即归档"的前提**（**在用且有实物**）；**#2 / #3 / #4 尚未接入真实服务**（**无版本可归档**）；**#5 不适用**。**另查出 3 个真缺口**（见 §11.2）。

### 11.1 逐项侦察（钉死值一律取自**项目自己的配置文件**，非推测）

| # | 依赖 | 项目钉死处 | 钉死值 | 本机实物 | 归档形态 | 缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| **2** | RAGFlow / AgentScope | — | **无**（仅开发期适配器契约；`architecture.md:105` 自述"真实服务部署、认证注入…仍未完成"） | 无 | — | ⛔ **未接入 ⇒ 无版本可归档**（属"接入时同步钉死"） |
| **3** | WeKnora | — | **无**（`D1` 定为唯一主源，但"真实 staging 接入前不视为生产可用"，`architecture.md:73`） | 无 | — | ⛔ 同上 |
| **4** | DeerFlow / Codex Worker / Hermes | — | **无**（`api-contract.md:594` 定为独立外部适配器，未接入） | 无 | — | ⛔ 同上 |
| **5** | GEO | 对端契约 | 不适用 | — | — | — （业务对端系统，第 0 层不适用） |
| **6** | PostgreSQL+pgvector / Redis / MinIO | [`docker-compose.yml`](file:///d:/徐徐AI学习/公司工作台/docker-compose.yml) `:3` / `:14` / `:21` | `pgvector/pgvector:0.8.0-pg16` / `redis:7.4-alpine` / `minio/minio:RELEASE.2025-04-22T22-12-26Z` | ✅ `pgvector…0.8.0-pg16`（`sha256:a132765e…`）<br>❌ **`redis:7.4-alpine` 缺失**（本机仅 `redis:7-alpine`，**tag 不符**）<br>❌ **MinIO 钉死版缺失**（本机仅 `minio/minio:latest`，**浮动**） | `docker save` → tar + sha256 | 🔴 **见 §11.2-②** |
| **7** | Electron / Node / Python 运行时 | [`desktop/package.json`](file:///d:/徐徐AI学习/公司工作台/desktop/package.json) `:15`、[`Dockerfile`](file:///d:/徐徐AI学习/公司工作台/Dockerfile) `:13`、[`pyproject.toml`](file:///d:/徐徐AI学习/公司工作台/pyproject.toml) `:9` | `electron@44.3.0`（精确）；`python:3.12-slim`（**tag**）；`requires-python >=3.11`（**范围**） | ✅ `python:3.12-slim`（`sha256:78387bc3…`）<br>✅ `node:22-slim`（**已归档**，见 §10.6） | `docker save` + 安装器归档 | 🔴 **见 §11.2-①③** |

**前端/桌面依赖侧是好消息**：`admin-web` / `desktop` / `companion-pwa` **三者都有 `package-lock.json`**，且依赖写**精确版本**（如 `react:19.2.8`、`electron:44.3.0`）⇒ **可离线复现**。

### 11.2 🔴 侦察查出的 3 个真缺口

| # | 缺口 | 证据 | 影响 | 建议 / 处置（**未实施的一律标注；已实施的注明落点**） |
| --- | --- | --- | --- | --- |
| **①** | **后端 Python 依赖没有任何 lockfile** | [`requirements.txt`](file:///d:/徐徐AI学习/公司工作台/requirements.txt) **全部是范围约束**（`pypdf>=5,<6` … `cryptography>=44,<49`）；仓库内**无** `requirements.lock` / `uv.lock` / `poetry.lock` / `Pipfile.lock` | **§3 第 0 层条件②（可离线复现构建）对后端不成立** —— 同一份 `requirements.txt` 在不同时间会装出不同版本；断网归档无"确定输入集" | 建议：生成一份**锁定文件**（`pip-compile` / `uv lock` / `pip freeze`）并纳入第 0 层归档。✅ **处置：已完全闭环（2026-09-13，选项 C + E + F）** —— 新增 [`requirements.lock`](file:///d:/徐徐AI学习/公司工作台/requirements.lock)（49 包全锁定 + 835 条哈希）→ **`Dockerfile` 已消费它**（`--require-hashes`）→ 构建通过、**镜像内 49/49 版本逐条一致**、**反假测试（改坏全部哈希必须失败）通过** → **测试套件 `1434 passed`（0 failed）+ `compileall` 通过，与文档基线逐数一致**（见 §11.5 ~ §11.7） |
| **②** | **Redis / MinIO 的"钉死 tag"本机并不存在** | 项目钉 `redis:7.4-alpine`、`minio/minio:RELEASE.2025-04-22T22-12-26Z`；本机实际只有 `redis:7-alpine`、`minio/minio:latest`（**均非钉死值**） | 归档时**必须先拉到钉死 tag 并核对 digest**，否则会**把非钉死版本当成归档输入**（这正是"浮动 tag"风险的现实体现） | ✅ **已修复（2026-09-13，用户批准）** —— **Redis** 已拉取钉死 tag 并记 digest；**MinIO** 因上游 Docker Hub 的钉死 tag 与 `latest` **均被拒**（`pull access denied`），当时**已换源到 `quay.io/minio/minio` 并按 digest 钉死**（quay 上为**同一 release** ⇒ 纯换源、不动版本；compose 解析正确、镜像可运行、**服务健康检查 `200`**）。⚠️ **其中 MinIO 已于同日被 SeaweedFS（Apache-2.0）替换，见 §11.12**。**连带发现（需合规判断）**：MinIO 许可为 **AGPLv3**、Redis 为 **RSALv2 + SSPLv1** ⇒ 已纳入许可清单（见 §11.8） |
| **③** | **基础镜像用 tag、不用 digest**（与段二 §4 的 `WORKBENCH_EXEC_IMAGE_DIGEST` 口径不一致） | `Dockerfile:13` 写 `python:3.12-slim`；`desktop`/前端**未声明 Node 版本**（无 `engines`） | tag 可变 ⇒ **归档与生产可能不是同一镜像**；段二已明确要求执行镜像按 digest 钉死 | ✅ **已修（2026-09-13，用户批准）** —— `Dockerfile` 基础镜像改为 **`python:3.12-slim@sha256:78387bc3…`**（**含反假测试：digest 写错必须失败**）；三端 `package.json` 新增 `engines.node>=22`；重建通过、镜像内 49/49 一致（见 §11.9）。**`docker-compose.yml` 三个镜像亦已全部改为 `tag@sha256`**（postgres/redis 补钉 + 对象存储换源钉死〔该服务**现已由 SeaweedFS 承担**，见 §11.12〕，**均已真起服务验证**，见 §11.10） |

### 11.3 未接入项（#2 / #3 / #4）的处置

**不在现在归档**（无版本可归档，归档无输入集）。建议**在其各自的接入规格里"同步钉死 + 同步归档"**，并把该要求写进对应门禁 —— **本轮只提出，未改任何规格**。

### 11.4 与 P0-2 的关系

本清单是第 0 层的**前置品**；**真归档动作仍卡在"目的地"**（同 P0-2）。**即便"其余 6 项"现在开工，也只是把待归档集做大，仍然无处可放。**

### 11.5 缺口①的修复（**第一步**，2026-09-13，用户批准）

**授权范围**：用户批准"**修缺口①（后端补 lockfile）**"，**原话明确为"会新增一个锁定文件"** ⇒ 本轮**只新增锁文件**，**未改 `Dockerfile`**、**未改 `requirements.txt`**。

**做了什么**：在**项目目标基础镜像 `python:3.12-slim`** 内（`Python 3.12.14` / `pip 25.0.1`）用 **pip-tools 7.6.1** 生成 [`requirements.lock`](file:///d:/徐徐AI学习/公司工作台/requirements.lock)，并做**离线可用性验证**。

| 项 | 实测 |
| --- | --- |
| 生成命令（锁文件头部自述） | `pip-compile --generate-hashes --no-emit-index-url --output-file=requirements.lock requirements.txt` |
| 锁文件规模 | **977 行**、**49 个包全部 `==` 锁定**、**835 条 `--hash=sha256:`**、**74,690 字节** |
| 关键版本 | `fastapi==0.141.1` / `uvicorn==0.52.4` / `pydantic==2.13.5` / `psycopg==3.3.5` / `redis==5.3.1` / `celery==5.6.3` / `cryptography==48.0.1` / `pypdf==5.9.0` / `pytest==8.4.2` |
| **离线验证** | **`--network none`** 容器 + **只用本地 wheel** + `--require-hashes` ⇒ **`INSTALL_EXIT=0`**（51 包全装）；**11 项 import 全部 OK**（fastapi / uvicorn / pydantic_settings / httpx / psycopg / psycopg_pool / redis / celery / cryptography / pypdf / pytest） |
| 离线输入集 | **51 个 wheel / 24.6 MB**，暂存仓库外 `_py-lockbuild\wheels\`（**待 P0-2 的目的地**） |
| 改动范围 | **只新增 `requirements.lock` 一个文件**；`requirements.txt` **未动**（mtime 仍为 09-11）；**`Dockerfile` 未动** |

**⚠️ 仍未闭环的三点（如实登记，不得省略）**：

1. ~~**锁文件是"范围内最新"，不等于"当前 CI 验证过的版本"**~~ → ✅ **已闭环（2026-09-13，选项 F）**：按 CI 原命令在**锁定依赖**下跑后端全量测试 ⇒ **`1434 passed`（0 failed）**，且 `compileall` 通过 —— **与文档基线（后端 1434）逐数一致**。详见 §11.7。
2. ~~**构建尚未消费它** ⇒ 缺口①只修了一半~~ → ✅ **已闭环（2026-09-13，用户批准选项 E）**：`Dockerfile` 已改为 `COPY requirements.lock` + `pip install --no-cache-dir --require-hashes -r requirements.lock`，并**构建 + 四项验证通过**（详见 §11.6）。
3. **锁文件头部命令回显含 `--no-index`**，与本次实际解析行为不符（生成命令并未传该参数，疑为 pip-compile 7.6.1 的回显问题）→ 标 **"待核"**；**不影响锁文件内容与离线验证结果**。

### 11.6 缺口①的第二步：**构建消费锁文件**（选项 E，2026-09-13，用户批准）

**改动（只动 `Dockerfile` 的依赖安装两行）**：

```dockerfile
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
```

（原为 `COPY requirements.txt` + `pip install -r requirements.txt`。**`requirements.txt` 本身未删、未改**，只是**不再被构建使用**。）

**验证（四项，均已实测）**：

| # | 项 | 结果 |
| --- | --- | --- |
| ① | **构建** | `docker build -t workbench-app:lockverify .` → **成功**；`pip install --require-hashes` 用 **35.7s** 装完 51 个包；镜像 manifest `sha256:13fa875fde99fa2b816e1b2f5287eb34b975c212ab60fd9f6da2de3419cf126b` |
| ② | **镜像内版本与锁文件逐条一致** | **`LOCK_PINS=49` / `MISSING=0` / `VERSION_MISMATCH=0`** |
| ③ | **import 冒烟** | `fastapi` / `uvicorn` / `pydantic_settings` / `httpx` / `psycopg` / `psycopg_pool` / `redis` / `celery` / `cryptography` / `pypdf` **全部 OK**（`IMPORT_OK_ALL`）；`uvicorn 0.52.4` |
| ④ | **反假测试（篡改必须变红）** | 把锁文件里 **835 条哈希全部改坏** ⇒ `pip install --require-hashes` **`EXIT=1`**，报错原文 `THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE … someone may have tampered with them.`；**对照组**（原锁文件）**`EXIT=0`** |

> **⚠️ 过程留痕（一次方法错误，如实登记）**：反假测试 **rev 1 无效** —— 我只改坏了 `amqp` 的**一个**哈希，而锁文件对同一包列出了**多个可接受产物**（wheel + sdist），pip 于是**合法回退**去装 sdist 并**成功**（`TAMPERED_INSTALL_EXIT=0`）。⇒ **rev 1 不能证明 `--require-hashes` 生效**；改成"**改坏全部 835 条哈希**"后才真正测到（rev 2）。**结论一律以 rev 2 为准。**

**仍未闭环（只剩一条）**：~~**这组锁定版本尚未经项目测试套件验证**~~ → ✅ **已闭环（2026-09-13，选项 F，见 §11.7）：`1434 passed`**。

**副作用（如实登记）**：镜像内**不再包含 `requirements.txt`**（构建不再需要它）。若希望镜像内保留依赖清单以便追溯，需另行加一行 `COPY` —— **本轮未加**。

### 11.7 缺口①的第三步：**测试套件验证**（选项 F，2026-09-13，用户批准）

**目的**：证明这组锁定版本**与既有基线兼容**（宪法「依赖升级四步」的验证环节）。

**方法（严格对齐 CI）**：CI 后端 job = `ubuntu-latest` + Python 3.12 + `pip install -r requirements.txt` + **`python -m pytest -o addopts=""`** + `compileall`（**不含任何服务容器**）。本次**同一命令、同一 Python 版本**，只把依赖换成**锁定的 wheel 集**（离线 + `--require-hashes`）；仓库以**只读**挂载，另加一个**可写 `tmp/` 叠加挂载**（确保不动仓库）。

| 步骤 | 结果 |
| --- | --- |
| 依赖安装 | 从本地 wheel 集离线安装（`--require-hashes`）⇒ **`INSTALL_EXIT=0`** |
| **后端全量测试** | **`1434 passed, 2 warnings in 29.61s`（0 failed）** ⇒ **`PYTEST_EXIT=0`** |
| `compileall` | **`COMPILEALL_EXIT=0`** |
| **与文档基线对照** | 基线"后端 **1434**" ⇒ **逐数一致** |
| **仓库是否被改动** | ✅ **未改动** —— `git status` 仅显示本次变更意图（`?? requirements.lock` / ` M Dockerfile`）；测试写入的 `tmp/relative.db` 落在**叠加挂载**中，**仓库内那份 mtime 仍为 2026-09-07** |

> **⚠️ 过程留痕（两次环境错误，如实登记）**：
> - **rev 1（作废）**：在**应用镜像**里跑 ⇒ `53 failed / 1381 passed`。失败集中于 `test_frontend_*` / `test_pwa_assets` / `test_staging_assets`，它们要读 `admin-web/`、`companion-pwa/`、`docs/`，而**应用镜像按 `.dockerignore` 刻意不含这些** ⇒ 属**"测错环境"**，**与依赖版本无关**。
> - **rev 2（作废）**：改为全仓库挂载后 ⇒ `1 failed / 1433 passed`；唯一失败是 `test_persistence_contract::…resolves_relative_path_from_project_root`，报 `sqlite3.OperationalError: attempt to write a readonly database` ⇒ 属**"只读挂载的环境限制"**，**与依赖版本无关**。
> - **rev 3（结论以此为准）**：只读仓库 + 可写 `tmp/` 叠加 ⇒ **`1434 passed`**。

**⇒ 缺口① 至此整条闭环**：**锁文件 → 构建消费（含反假测试）→ 测试套件验证通过**。

**仍未闭环**：**缺口 ② 只剩 MinIO（需裁决，见 §11.8）**；**#2/#3/#4 未接入**；**归档目的地**（P0-2 挂起）。

### 11.8 缺口②的修复：**钉死镜像的 digest 记录**（2026-09-13，用户批准）

> ⚠️ **本节已部分过时（保留作过程记录）**：其中 **MinIO 部分**（换源到 quay + 钉死）已于**同日**被 **§11.12 的 SeaweedFS 替换**取代 —— **当前对象存储是 SeaweedFS，不是 MinIO**。本节其余内容（Redis 的 digest 记录等）**仍有效**。

**做法**：按项目 `docker-compose.yml` 钉的 tag **逐个 `docker pull` + 记 digest**（`digest` 才是不可变的归档输入）。

| 组件 | 项目钉的 tag | 拉取结果 | **RepoDigest（不可变输入）** | 大小 |
| --- | --- | --- | --- | --- |
| PostgreSQL+pgvector | `pgvector/pgvector:0.8.0-pg16` | ✅ 本机已有 | `sha256:a132765ec351c65111b5b675928a3a0515a466a40f97277329db8b8209ad8bc9` | 156.3 MB |
| Redis | `redis:7.4-alpine` | ✅ **本次拉取成功** | `sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf` | 16.3 MB |
| **MinIO** | `minio/minio:RELEASE.2025-04-22T22-12-26Z` | 🔴 **不可获取** | —（见下） | — |
| 应用基础镜像 | （见 §11.9 已改 digest） | ✅ | `python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea` | 46.2 MB |
| 执行容器基础镜像 | `node:22-slim` | ✅ 本机已有 | `node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5` | 79.9 MB |

#### 🔴 新发现（阻塞项，**需用户裁决**）：**MinIO 的 Docker Hub 仓库已不可访问**

| 检查 | 实测结果 |
| --- | --- |
| `docker pull minio/minio:RELEASE.2025-04-22T22-12-26Z`（**项目钉的**） | ❌ `pull access denied for minio/minio, repository does not exist or may require 'docker login'`（**重试仍失败**） |
| `docker pull minio/minio:latest` | ❌ **同样被拒** |
| `docker pull quay.io/minio/minio:latest` | ✅ **可以拉** |
| 本机现有 `minio/minio:latest` | 存在，但是 **12 个月前的浮动 tag 快照**（`sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`）—— **不是钉死版本** |

**影响（这是"上游会变"落到我们身上的实例）**：

1. **`docker-compose.yml` 现在拉不起来 MinIO** —— 新机器/新环境按该 compose 启动会失败；本机之所以还能跑，是靠那份**12 个月前的浮动快照**。
2. **第 0 层拿不到归档输入** —— 钉死版本的镜像**无处可拉**，无法 `docker save` 归档。
3. **对象存储是 §9-6 里"用轮子"的组件**（`capability-ownership-map` 第 24 行标注 B 类），因此它的可得性直接影响段二/归档链。

**可选处置（属设计决策，我未擅自选）**：

| 选项 | 内容 | 代价 |
| --- | --- | --- |
| **① 换分发源** ✅ **已采纳并执行（2026-09-13）** | 改钉 `quay.io/minio/minio@sha256:…`（已证可拉） | 小；**已确认 quay 上有项目钉的同一 release**，故**纯换源、不动版本**；长期稳定性仍建议留意 |
| **② 换 S3 兼容实现** | 如 SeaweedFS / Garage / Ceph RGW（**许可均待核**），或改用云对象存储 | 中；需改 compose + 适配层回归 |
| **③ 接受浮动源** | 继续用 Docker Hub 但**放弃钉死** | ⚠️ **与第 0 层直接冲突，不建议** |

**✅ 已按选项 ① 执行并验证（2026-09-13，用户批准）**

| # | 项 | 结果 |
| --- | --- | --- |
| 1 | 前置确认：**quay 上是否有项目钉的那个 release** | ✅ **有**：`quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`，Created `2025-04-22T22:35:01Z`（与 tag 日期吻合）⇒ **本次是纯换源、不动版本** |
| 2 | 新引用（写入 `docker-compose.yml`） | `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z@sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`（**tag 供人读 + digest 保证不可变**，与 `Dockerfile` 同口径）；大小 **61.0 MB** |
| 3 | compose 解析 | `docker compose -p workbench -f docker-compose.yml config --images` ⇒ MinIO 行**正是该引用** ✅（另两行仍为 tag，见"仍未做"） |
| 4 | 镜像可运行 | `docker run --rm <ref> --version` ⇒ `minio version RELEASE.2025-04-22T22-12-26Z (commit-id=0d7408fc…)`、`go1.24.2 linux/amd64` ✅ |
| 5 | **服务真能起来** | 临时容器（宿主 `19000`，`--tmpfs /data`）⇒ **`/minio/health/live` 返回 `200`** ✅；**已随即删除该临时容器** |
| 6 | 端口冲突说明 | **本机 `9000/9001` 已被另一个项目的 `infra-minio-1` 占用** ⇒ 验证**刻意改用 `19000`**，避免干扰其它项目 |

**仍未做（如实登记）**：**`docker-compose.yml` 里另外两个镜像仍按 tag**（`pgvector/pgvector:0.8.0-pg16`、`redis:7.4-alpine`）—— 本轮批准的只是 **MinIO 换源**，**改不改它们待你定**；**`docker save` 归档未做**（无目的地，P0-2 仍挂起）。

#### 🔴 顺带发现的**许可事实**（新，**需合规判断**）

镜像启动 banner 明确声明：**`License: GNU AGPLv3`**（`RELEASE.2025-04-22T22-12-26Z`）。

- **事实层**：这是 MinIO **社区版一贯的许可**，**并非本次换源引入**（换源前后是**同一个 release**，许可不变）；**镜像内无 `/LICENSE` 文件**（`cat: /LICENSE: No such file`）⇒ **本轮只能依据 banner，未逐字比对许可正文**。
- **暴露出的流程缺口**：项目的许可清单 [`poc-license-checklist.md`](file:///d:/徐徐AI学习/公司工作台/docs/superpowers/poc-license-checklist.md) **完全没有覆盖基础设施组件**（grep `MinIO` / `PostgreSQL` / `Redis` / `AGPL` **零命中**）⇒ **对象存储这类"B 类用轮子"的组件，从未进入过许可核对范围**。
- **需要判断的点（我不做法务判断、也不代判）**：AGPLv3 的**网络交互条款（§13）**在"**使用未修改的 MinIO 作为自托管服务**"下，通常只要求向网络交互方提供**该服务自身的源码**（MinIO 源码本公开）；但**若将来修改 MinIO 并对外提供网络服务，义务会显著上升**。⇒ ✅ **已记入许可清单（2026-09-13，用户批准）**：见 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md) 文末新增的 **【基础设施组件纳管】** 一节 —— 本轮同时**从镜像内取证**到 `pgvector` 的 `LICENSE`（**PostgreSQL License，类 BSD**）与 PG 本体 `copyright`（`License: PostgreSQL`）；**Redis 因镜像内无任何许可文件而只能标"未核"**。**"是否接受 AGPL 组件进生产"仍待形成明确结论。**
- ⚠️ **本条只登记事实与影响，未改任何许可结论。**

### 11.9 缺口③的修复：**基础镜像 digest 钉死 + 前端声明 Node 版本**（2026-09-13，用户批准）

**改动（4 处）**：

| # | 文件 | 改动 |
| --- | --- | --- |
| 1 | [`Dockerfile`](file:///d:/徐徐AI学习/公司工作台/Dockerfile) `:14` | `FROM python:3.12-slim` → **`FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`**（并加注释说明"tag 可变、digest 不可变"，与段二 §4 `WORKBENCH_EXEC_IMAGE_DIGEST` 口径对齐） |
| 2 | [`admin-web/package.json`](file:///d:/徐徐AI学习/公司工作台/admin-web/package.json) | 新增 `"engines": {"node": ">=22"}` |
| 3 | [`companion-pwa/package.json`](file:///d:/徐徐AI学习/公司工作台/companion-pwa/package.json) | 同上 |
| 4 | [`desktop/package.json`](file:///d:/徐徐AI学习/公司工作台/desktop/package.json) | 同上 |

> `>=22` 的依据：CI（[`ci.yml`](file:///d:/徐徐AI学习/公司工作台/.github/workflows/ci.yml) `:56`）自己写的注释就是「**vite 8 / vitest 5 要求 Node 22+**」，且三个前端 job 均 `node-version: "22"`。

**验证（四项）**：

| # | 项 | 结果 |
| --- | --- | --- |
| ① | **重建** | `docker build -t workbench-app:digestpin .` → **成功**；构建日志显示 `resolve docker.io/library/python:3.12-slim@sha256:78387bc3… done`（即**确实按 digest 解析**） |
| ② | **反假测试（digest 写错必须失败）** | 用 `FROM python:3.12-slim@sha256:0000…` 构建 ⇒ **失败（exit=1）**，报 `…@sha256:0000…: not found` ⇒ **digest 钉死是承重的**，不是装饰 |
| ③ | **`package.json` 仍合法且已声明** | 三份均通过 JSON 解析，`engines.node = ">=22"` |
| ④ | **镜像内依赖未被影响** | `LOCK_PINS=49 / MISMATCH=0`（与锁文件逐条一致） |

**~~仍未做~~ → ✅ 已补做（2026-09-13，用户批准）**：`docker-compose.yml` 的三个镜像**现已全部为 `tag@sha256` 形式**（`postgres`/`redis` 本次补钉，`minio` 已于 §11.8 换源并钉死）—— **验证见 §11.10**。

### 11.10 基础设施镜像补钉 digest（`postgres` / `redis`）（2026-09-13，用户批准）

**改动（`docker-compose.yml`：两行 + 各一行注释）**：

| 服务 | 改前 | 改后 |
| --- | --- | --- |
| `postgres` | `pgvector/pgvector:0.8.0-pg16` | `pgvector/pgvector:0.8.0-pg16@sha256:a132765e…8bc9` |
| `redis` | `redis:7.4-alpine` | `redis:7.4-alpine@sha256:ff02b58f…eadf`（**→ 已于 §11.11 换为 Valkey**） |

（`minio` 当时已在 §11.8 完成换源 + 钉死 ⇒ **当时三个服务全部为 `tag@sha256`**；⚠️ **后于同日，对象存储那一项被换成 SeaweedFS（见 §11.12）⇒ 当前 compose 三镜像为 `pgvector@sha256` / `valkey@sha256` / `seaweedfs@sha256`**，与 [`Dockerfile`](../Dockerfile) 同口径。）

**验证（四项）**：

| # | 项 | 结果 |
| --- | --- | --- |
| 1 | compose 解析 | `docker compose -p workbench -f docker-compose.yml config --images` ⇒ **三条全部为 `tag@sha256:…`** ✅ |
| 2 | **Redis 真能服务** | 临时容器（宿主 `16379`）⇒ **`PING = PONG`**、`redis_version:7.4.11`（与 tag 一致）✅；随后删除 |
| 3 | **PG 真能服务** | 临时容器（宿主 `15432`、`--tmpfs` 数据）⇒ `pg_isready` **accepting connections** ✅；`PostgreSQL **16.10**`（与 `pg16` 一致）✅ |
| 4 | **pgvector 扩展真可用**（选这个镜像的意义所在） | `CREATE EXTENSION vector` **成功** ⇒ `pg_extension` 列出 **`vector 0.8.0`**（与 `0.8.0` 一致）✅ |

**验证方式说明**：本机 `5432/6379/9000/9001` **均被其它项目的容器占用**（`infra-postgres-1` / `infra-redis-1` / `infra-minio-1`），故验证**改用 `15432/16379` + `--tmpfs`** —— **未使用 compose 的命名卷、未触碰其它项目**。

**未做 / 未验证（如实登记）**：~~未跑 `docker compose up` 全栈~~ → **已部分补做**（见 **§11.11**：`up -d redis` 真起服务 + 用项目代码跑兼容套件 10/10）；**三个服务同时起的全栈仍未跑**；**未做 compose 级的"错 digest 必失败"反假测试**（该机制已在 §11.9 用 `Dockerfile` 证过：dockerd 对未知 digest 直接拒绝）。

### 11.11 Redis → Valkey 替换（路径④落地，2026-09-13，用户批准）

**背景**：裁决与推导见 **§8 第 8 项** 与 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md)【决策留痕】。

**改动（`docker-compose.yml` 的 `redis` 服务）**：

| 项 | 改前 | 改后 |
| --- | --- | --- |
| 镜像 | `redis:7.4-alpine@sha256:ff02b58f…eadf`（**Redis 7.4.11**） | **`valkey/valkey:8-alpine@sha256:d2e18f34…43d1`**（**Valkey 8.1.10**，19.0 MB） |
| 服务名 | `redis` | **仍为 `redis`**（compose 内主机名）—— 因为 `WORKBENCH_REDIS_URL=redis://redis:6379/0`（[`.env.example`](file:///d:/徐徐AI学习/公司工作台/.env.example) / [`docker-compose.app.yml`](file:///d:/徐徐AI学习/公司工作台/docker-compose.app.yml) / [`test_container_assets.py:119`](file:///d:/徐徐AI学习/公司工作台/tests/test_container_assets.py#L119)）依赖它；**改名会牵动应用配置与测试，属另一件事** |

**验证（六项，全部实测）**：

| # | 项 | 结果 |
| --- | --- | --- |
| 1 | **许可取证（按钉死版本）** | ✅ 上游 `COPYING` **@ tag `8.1.10`**（blob SHA `2254cb05c4434c5d2ec74282eca5b0d00323e228`）：**两份 BSD 3-Clause**（`Copyright (c) 2024-present, Valkey contributors` / `Copyright (c) 2006-2020, Redis Ltd.`）⇒ **无 copyleft**（上一轮基于 `unstable` ref 的证据由本条替代；另：**Valkey 镜像内不含任何许可文件**，故只能走上游原文） |
| 2 | **Streams 兼容性（用项目自身代码，非手搓命令）** | ✅ 写 `valkey-compat.py`，**import 项目的 [`RedisStreamEventBus`](file:///d:/徐徐AI学习/公司工作台/app/events.py#L87-L151)** 真连 Valkey，逐条跑它实际使用的命令 ⇒ **10/10 PASS**：`XADD`／`XGROUP CREATE`（含 **BUSYGROUP 幂等**）／`XREADGROUP`（且**不重复投递**）／`XPENDING`／**`XAUTOCLAIM`（返回形状 `result[1]` 兼容）**／`XACK`／`XREVRANGE`／`XINFO GROUPS` |
| 3 | **反假测试（这份验证必须会红）** | ✅ 地址指向不存在服务 ⇒ **`ConnectionError: Error 111 … Connection refused`，退出码 1** ⇒ 验证器**不吞错**（不是"永远绿"的假测试） |
| 4 | **对照组（旧服务端）** | ✅ 同一套验证跑 `redis:7.4-alpine`（Redis 7.4.11）⇒ **同样 10/10 PASS** ⇒ 两个服务端**在我们依赖的语义面上行为一致** |
| 5 | **compose 级真起服务** | ✅ `docker compose -p workbench up -d redis`（宿主端口改 `16381` 以避开其它项目占用）⇒ `workbench-redis-1 \| valkey/valkey:8-alpine \| Up`；`valkey-cli ping` ⇒ **`PONG`**；**并用项目代码对该 compose 服务再跑一次兼容套件 ⇒ 10/10 PASS** |
| 6 | **回归** | ✅ 后端基线 **`1434 passed, 0 failed`**（29.9s）＋ `compileall` 通过 |

**⚠️ 必须写清的边界**：**第 6 项的"1434 全绿"不能当作 Streams 兼容性证据** —— CI 后端 job **不含任何服务容器**，那 1434 项**不真连 Redis**；兼容性证据在 **第 2/4/5 项**。这是"跑绿 ≠ 兼容"的实例。

**清理**：验证用临时容器（`valkey-compat-srv` / `redis-ctl-srv`）与网络（`valkey-compat`）**已删除**；compose 起服务时新建的卷 **`workbench_workbench-redis` 已删除**（起服务前该卷不存在 ⇒ 已还原原状）。

**未做 / 未验证（如实登记）**：**未验证持久化（RDB/AOF）与主从/集群形态**（本项目当前未使用）；**未做压测**；**未改** `.env.example` / `docker-compose.app.yml`（**服务名未变，无需改**）。

### 11.12 对象存储 MinIO → SeaweedFS 替换（2026-09-13，用户批准）

**背景**：裁决与候选取证见 **§8 第 7 项** 与 [`poc-license-checklist.md`](superpowers/poc-license-checklist.md)【MinIO 替代候选取证】。**用户裁决的口径**：**服务名改 `seaweedfs` + S3 端口保持 9000 + 环境变量名暂不改**。

**改动**：

| 项 | 改前 | 改后 |
| --- | --- | --- |
| 服务名 | `minio` | **`seaweedfs`** |
| 镜像 | `quay.io/minio/minio:…@sha256:a1ea29fa…`（**AGPLv3**） | **`chrislusf/seaweedfs:4.46@sha256:08d516132314207d10c8e37cbffc1f32b147d870169688734cc61c6231625b62`**（**Apache-2.0**；195 MB，原 61 MB） |
| 启动方式 | `server /data --console-address ":9001"` | `entrypoint: ["/bin/sh","-c"]` + 脚本：**由 env 生成 `/tmp/s3.json` 凭据** → `exec /entrypoint.sh server -s3 -s3.port=9000 -s3.config=/tmp/s3.json -master.telemetry=false -s3.port.iceberg=0 -s3.port.lance=0` |
| 控制台端口 | 容器 `9001` | 容器 **`8888`**（filer UI）；**宿主端口仍为 `${WORKBENCH_MINIO_CONSOLE_PORT:-9001}` 不变** |
| [`docker-compose.app.yml`](file:///d:/徐徐AI学习/公司工作台/docker-compose.app.yml) | `WORKBENCH_OBJECT_STORAGE_URL: http://minio:9000` | **`http://seaweedfs:9000`**（**全仓唯一引用处，共 1 行**） |
| 变量名 / 卷名 | `WORKBENCH_MINIO_*` / `workbench-minio` | **沿用不改**（历史命名；改名会牵动 app 配置 / preflight / 测试 / 文档，属另一件事） |

**两个安全口径（本项目红线相关，均已在启动参数里写死）**：

1. 🔴 **遥测默认开启 → 已显式关闭**：`weed server --help` 原文显示 `-master.telemetry` **`(default true)`**、`-master.telemetry.url` 默认 **`https://telemetry.seaweedfs.com/api/collect`** ⇒ 已写死 **`-master.telemetry=false`**。
2. **额外暴露面已收敛**：上游 `server` 默认还起 **Iceberg REST(8181)** 与 **Lance(9101)** 两个本项目用不到的目录服务 ⇒ 已用 `-s3.port.iceberg=0 -s3.port.lance=0` 关闭。

**验证（四项，全部实测）**：

| # | 项 | 结果 |
| --- | --- | --- |
| 1 | compose 解析 | ✅ `compose config --images` ⇒ 三条全为 `tag@sha256`（含 SeaweedFS） |
| 2 | **服务真起** | ✅ `workbench-seaweedfs-1` `Up`；日志 `Start Seaweed S3 API Server 30GB 4.46 d997fba15 at http port 9000`（⚠️ **`d997fba15` 正是 tag `4.46` 的 commit，与许可取证交叉印证**） |
| 3 | **红线项复核** | ✅ **PID 1 参数** = `… server -dir=/data … -s3 -s3.port=9000 -s3.config=/tmp/s3.json -master.telemetry=false -s3.port.iceberg=0 -s3.port.lance=0`；✅ 日志**无 Iceberg / Lance 行** |
| 4 | **S3 真实冒烟（boto3，非手搓 HTTP）** | ✅ `CREATE_BUCKET` / `PUT_OBJECT` / **`GET_OBJECT`（内容 `b'seaweedfs-ok'` 一致）** / `LIST_OBJECTS=['hello.txt']` / `DELETE_OBJECT`（剩余 0）⇒ **`SMOKE_RESULT: ALL_PASS`** |
| 5 | **回归（后端基线）** | ✅ **`1434 passed, 0 failed`**（28.5s，锁定依赖）—— 本次改动含 **compose 文件**（测试会读），故按纪律重跑 |

**许可证据（按钉死版本）**：上游 `LICENSE` **@ tag `4.46`** = **Apache-2.0**（blob `c9c58bb5…`，commit `d997fba1575583a89cf0cc50dc0150642286c86d`）；**镜像自报构建 commit `d997fba15` 与之一致** ⇒ 证据链闭合。另：SeaweedFS 仓库根目录**无 `enterprise/` 类专有目录**（对比 OpenMausBot 的 carve-out 风险）。

**清理**：验证用的容器（`workbench-seaweedfs-1`）、网络（`workbench_default`）、本次新建卷（`workbench_workbench-minio`）**已全部删除**，复核**无残留**。

**已知限制（如实登记）**：**凭据须为 JSON 安全字符** —— 启动脚本把 env 值直接内插进 JSON，若凭据含 `"` 或 `\` 会生成非法文件、SeaweedFS 启动失败（**fail-closed，不会静默降级**）；如需支持任意字符，须再加一层转义。

**未验证**：多副本 / 纠删码、S3 分片上传、生命周期策略、跨版本升级、压测 —— 本项目当前均未使用。

**真源同步（2026-09-13 一致性巡检所得，**仅名称同步、未改任何设计要求**）**：以下三处仍写着旧组件名，已就地同步为 **Valkey / SeaweedFS** 并加日期注 —— ① [`feature-inventory.md`](feature-inventory.md) 的 E2 行；② [段二规格的测试计划第 9 行](superpowers/specs/2026-09-12-dsh-integration-design.md)（"看不到 PG/Redis/MinIO"）；③ [账号注册 spec](superpowers/specs/2026-09-10-account-registration-design.md) 的"全项目层面既有差距"注。
