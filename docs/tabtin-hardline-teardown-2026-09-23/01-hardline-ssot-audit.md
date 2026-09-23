# hardline 规则 SSoT 去拷贝 —— 审计与迁移清单

> **状态**：进行中。本文件是这条迁移线的权威待办清单，随进度勾选。
>
> **来源**：5 个独立搜索角度 + 完整性批评者补跑 12 种模态，共 100 个 agent / 947 次工具调用。
> 108 条候选 → 去重 94 → 逐条对抗式核实后 69 条确认，另 3 条经批评者翻案补入，**合计 72 条**。

## 背景：为什么要做这件事

hardline 安全规则（命令红线、绝对路径红线、敏感路径四态）原本存放在
`packages/security-policy/src/hardline-rules.json`（v1）与 `hardline-v3-rules.json`（v3）。
由于 `@tabtin/security-policy` 依赖 `@tabtin/terminal-core`，terminal-core **无法反向 import**，
只能把规则在构建期抄一份进来；Python 侧跨语言，同样只能抄。**于是同一份规则在全仓存在多份拷贝，靠人工同步。**

本次迁移把 SSoT 移到 `packages/tabtin-shared/src/`（两端共同的中立依赖，且已在 Django 镜像内），
目标：**让每条规则只剩一份可编辑定义，改一条规则只改一处。**

## 已完成并验证

- [x] JSON 迁入 `packages/tabtin-shared/src/`，新增 `./hardline-rules.json` 与 `./hardline-v3-rules.json` 两个 exports 子路径
- [x] 新增构建步骤 `packages/tabtin-shared/scripts/copy-json.mjs`（`tsc` 不会把 JSON 搬进 dist），已实测把 4 个 JSON 送入 dist
- [x] `packages/security-policy/src/hardline-v3.ts` 改为跨包导入 `@tabtin/shared/hardline-v3-rules.json`
- [x] `packages/terminal-core/src/denylist.ts` 改为直读 SSoT 并 **fail-closed**（取不到规则即抛错，绝不退化成「没有红线」）
- [x] 删除 `packages/terminal-core/src/hardline-command-denylist.generated.ts`
- [x] `apps/tabtin-daemon/tsup.config.ts` 与 `apps/tabtin-electron/electron.vite.config.ts` 的拷贝路径改指 tabtin-shared
- [x] 补 `@tabtin/shared` 的 `.` 导出 `default` 条件 —— 修掉 `require.resolve` 抛 ERR_PACKAGE_PATH_NOT_EXPORTED（**本审计发现，属迁移自身引入的 bug**）
- [x] 锁文件用仓库声明的 pnpm 9.15.0 重生成，delta 最小（+3/−4，无任何版本变化）

**回归验证**：`hardline-v3.test.ts` 99/99；`hardline-command-codegen.test.ts` 7/7；
security-policy 全量与改动前基线逐条一致（7 failed files / 2 failed tests，均为环境性）；
`scripts/tests` 24 项失败与 HEAD 基线逐条 diff **完全一致 → 零回归**。

## 本轮进展（2026-09-22）

### 第 1 层「会坏的构建与测试」—— 7 条全部完成并实跑验证

1. **JSON import attribute（原第 5、6 条）** —— 迁移把 `hardline-v3.ts` / `denylist.ts` 的
   相对 JSON 导入换成裸包 specifier `@tabtin/shared/hardline-v3-rules.json` 后，
   security-policy 的 tsup 补丁只匹配相对路径、terminal-core 则完全没有补丁，
   两个包的 dist 直载均报 `ERR_IMPORT_ATTRIBUTE_MISSING`（**已实跑复现**）。
   改法：源文件直接写 `with { type: 'json' }`，security-policy 那段正则补丁随之退役。
   - **代价（新发现，比原描述多一处）**：`module` 与 `target` **都必须** ≥ ESNext。
     TS 在 `module=ES2022` 下以 **TS2823** 拒绝该语法；而 tsup 的构建 target 取自 tsconfig，
     **esbuild 0.19.12 在 `target=es2022` 时会把 attribute 当新语法降级剥掉**
     （已用 esbuild 的 transform 与 bundle 两种模式分别实测）。两个包的 tsconfig 因此
     各改了 `module` + `target` 两项。
   - 验证：`dist/hardline-v3.js` 首行带 attribute、Node 直载 18 exports；
     terminal-core 直载 138 exports。
2. **terminal-core dts/typecheck 回归（本审计未列，实跑才暴露）** —— 裸包 specifier 在
   `moduleResolution: "node"`（node10）下不被 tsc 解析（node10 不读 `exports` 映射），
   而 esbuild 一直读，所以只有 tsc 侧报 TS2307，`build`（dts）与 `typecheck` 双双变红。
   （HEAD 里该文件导入的是相对路径，故这是**本次迁移引入**的回归。）
   改法：`moduleResolution` 由 `node` 改为 `bundler`，与 security-policy 一致。
   改后 typecheck 零错误、dts 构建成功。
3. **死代码（原第 1 条 daemon 拷贝步骤、第 2 条 security-policy JSON 拷贝循环）** ——
   两处均已删除。删除前补上了本审计当时明确缺失的构建实证：
   - daemon：esbuild 打包（模拟其 `noExternal`）产物中 **import 语句 0 条、规则内容已内联**；
     且全仓已无任何 `createRequire(...)('./hardline-v3-rules.json')` 式运行时相对加载 ——
     该拷贝当初要修的问题已不会发生。
   - security-policy：`critical-rules.json` 与 `i18n-keys.json` 全仓无代码 import、
     也未进 `exports` 映射，拷进 dist 没有消费方。
   - ~~**未验证**：daemon 端到端仍跑不通（缺 4 个 workspace 包的构建产物）~~
     —— **后续已补跑**：补齐 workspace 依赖后 daemon 构建成功，产物里确认无该 JSON、
     无其 import、规则已内联。详见文末「后续补跑」一节。
4. **`test_path_safety.py` 的 codegen 门（原第 7 条）** —— `TestCodegenIntegrity` 已撤销。
   它唯一做的事是跑仓库中从未存在的 `scripts/codegen-hardline.py`，自建立起就必然失败、零实际保护。
   注意（已写进代码注释）：**不要**把它改写成「JSON 与 `generated_hardline.py` 逐条相等」的守卫 ——
   两端当前存在真实漂移（force_block 8 条 vs SSoT 9 条），等值断言会立刻变红；根治在 Stage B。

### 第 2 层：`path_scan_rules` 去拷贝（本组关闭第 2/3/4 层共 22 条）

删除 `packages/terminal-core/src/sensitive-paths.generated.ts`（SSoT `path_scan_rules` 的
固化拷贝），`allowlist.ts` 改为运行时直读 SSoT + fail-closed（与同包 `denylist.ts` 同构）。

- **零行为变化有实证**：删除前先固化旧规则快照，重构后逐条比对
  `label` / 正则源码 / `flags` —— **33/33 完全一致，顺序一致**。
- **fail-closed 有实证**：把 SSoT 换成缺 `path_scan_rules` 的内容 → 按预期抛错拒绝启动。
- 顺带修掉一条假测试：原 `toBeGreaterThanOrEqual(33)` 下界断言（正是下文「测试守卫缺口」
  点名的问题）改为等值 + 逐条 element-wise 断言。

### 第 2 层：灾难级 / 底线规则名去硬编码（`tier` + `agent_spawn_floor`）

两处写死的规则名单（`hardline-v3.ts` 的 7 个灾难级名字、`localSandboxPolicy.ts` 的 6 个 spawn
底线名字）**彼此已经不一致**，且 SSoT 改名后会双双静默失效。改法：在 SSoT 的
`absolute_command_denylist` 条目上新增两个显式字段（值严格照搬改造前的硬编码），消费端改为派生：

- `tier: 'catastrophic' | 'risk'`（7 条灾难级）
- `agent_spawn_floor: boolean`（6 条 = 灾难级去掉 `rm -rf root or home` ——
  家目录删除属「可审批」，不由 spawn 底线负责）

- **零行为变化有实证**：派生集合与改造前硬编码逐条一致（7/7、6/6）；并在**构建产物上**验证
  `rm -rf /` → catastrophic、`sudo ls` → risk；spawn 底线对 `rm -rf /`、`mkfs.ext4 /dev/sda` 拦，
  对 `rm -rf ~`、`ls -la` 放行。
- **明确未改** `checkOpaquePowerShellCommand` 的硬编码 `tier: 'catastrophic'`。本审计建议
  「顺带覆盖」，但查证后**改为派生是回退**：它复用 `eval expansion` 这个 slug，而该规则在 SSoT
  里是 `risk`，派生会让它从 catastrophic 掉成 risk。原硬编码语义正确（不透明 PowerShell 在本地
  也是不可审批的底线）。

### 新增：stale-dist 的 fail-closed 守卫

`@tabtin/shared` 的 exports 指向 **dist**，所以改了 `packages/tabtin-shared/src/` 下的 JSON
却没重建该包时，消费方会继续读到旧 JSON。对本次新增的两个字段而言，后果是**静默的安全降级**：
字段全为 `undefined` → 灾难级集合为空、spawn 底线一条不拦。

已在两处读取点加 fail-closed 守卫（为空即抛错），并作了负向验证（把 SSoT 换成缺这两个字段的
形态 → 两处均按预期抛错，非静默放行）：

- `packages/security-policy/src/hardline-v3.ts` —— 无 `tier=catastrophic` 即抛错
- `packages/terminal-core/src/denylist.ts` —— 无 `agent_spawn_floor=true` 即抛错

### 未解决：`localSandboxPolicy.ts:22` 的 `SENSITIVE_FILE_PATTERNS`（第 2 层，仍未勾选）

**不能**按原方案「从 SSoT 派生」——**SSoT 比本地更窄，派生会削弱安全底线**：

| 本地 | SSoT 对应 | 差异 |
|---|---|---|
| `(^\|[/\\])\.aws[/\\]` | 只有 `.aws/credentials` | SSoT 窄：派生后 `.aws/config` 等不再需要审批 |
| `(^\|[/\\])\.ssh[/\\]`、`.gnupg` | `\.ssh/`、`\.gnupg/` | SSoT 只认正斜杠：Windows 的 `.ssh\` 会失守 |
| `/\.env(\.\|$)/i` | `^\.env(?:\..*)?$`（basename fullmatch） | 匹配语义不同（本地对 basename 与全路径各测一次） |

需先决定是否把 SSoT 扩宽到能覆盖本地底线（那是改共享契约，会连带影响 Python 侧行为），
才能收敛；在此之前保持现状，不做半吊子合并。

### 迁移的另一处波及：消费方的 vite alias 会吃掉 SSoT JSON 子路径（已修）

`terminal-core` 的 `denylist.ts` / `allowlist.ts` 用裸包 specifier 导入
`@tabtin/shared/hardline-v3-rules.json`。而三个测试配置用**前缀别名**把 workspace 包指向 src，
泛别名会连子路径一起吃掉：

```
'@tabtin/shared': .../tabtin-shared/src/index.ts
  ⇒ '@tabtin/shared/hardline-v3-rules.json' 被拼成
     .../src/index.ts/hardline-v3-rules.json → 解析失败
```

（既有的 `'@tabtin/shared/storage-paths'` 条目就是为同一个坑补的，说明这不是新问题。）

**后果**：`packages/action-tools` 经 `source` 条件解析到 terminal-core 的 **src**，于是其
`path-validation.test.ts` **整个文件加载失败（no tests）** —— 3 个红线回归用例自本次迁移起
一直被静默停跑。三处配置已补上该子路径的显式别名：`packages/action-tools/vitest.config.ts`、
`packages/agent-runtime/vitest.config.ts`、`apps/tabtin-electron/vitest.config.ts`。

**每新增一个 SSoT JSON 子路径，这三处都要同步补。**

**「把泛别名改成锚定正则」这条根治路已试过并否决。** 在 action-tools 上实测可行
（改成数组形式 + `/^@tabtin\/shared$/`，去掉子路径条目后测试与改前逐条一致），但**推广不成立**：
锚定后子路径只能走 `exports` 解析，而仓库里有 3 个**在用的**子路径在各自包的 `exports` 里
根本没有键 ——

- `@tabtin/smartsheet-ui/toast-native` → `smartsheet-ui/src/toast.ts`
- `@tabtin/smartsheet-ui/message-native` → `smartsheet-ui/src/message.ts`
- `@tabtin/agent-runtime/providers/proxy-provider` → `agent-runtime/src/providers/proxy-provider.ts`

锚定会让它们无处解析。electron 的 vitest 配置里也早有一条注释记着同一个坑
（「精确子路径必须放在聚合入口之前；Vite 的字符串 alias 会把 `@tabtin/agent-host/delivery/*`
继续拼到 `index.ts` 后面而解析失败」）。**故维持「逐个显式列出子路径」的既有约定**，
不要为了省那几行去动解析语义。

### 第 2 层：`action-tools/path-validation.ts` 的 `HARD_DENY_READ_PHYSICAL`

删掉那份写死的 `['/etc/shadow','/etc/sudoers','/etc/gshadow']`（`path_scan_rules` 的又一份手抄
子集）。原代码是「本地数组 **或** `matchSensitivePath`」；实测该数组是 `matchSensitivePath` 的
**真子集**（三条及其全部子路径都被后者命中，0 条违例），且后者还多抓 `/etc/passwd`、
`/etc/shadow.bak` —— 这些在 `||` 语义下本已生效，故删除为**零行为变化**。

**注意**：该文件的 3 个红线用例在**本机（Windows）恒失败**，与本次改动无关 ——
`path.resolve('/etc/shadow')` 在 Windows 上得到 `D:\etc\shadow`，而规则用的是正斜杠，故不匹配；
旧代码的数组等值/前缀判定对 `D:\etc\shadow` 同样不匹配。已用 A/B（撤掉改动重跑）确认改动前后
逐条一致。Linux / macOS 上 `resolve('/etc/shadow')` 保持原样，红线正常命中。

### 第 2 层：`CRITICAL_DENYLIST` 去手抄（并挖出被埋没的 `redirect-write` 缺陷）

`terminal-core/src/denylist.ts` 那份 12 条手抄表已删除，改为直读 SSoT
`@tabtin/shared/critical-rules.json`（JSON 由 `security-policy/src/` 迁入，新增 exports 子路径）。

**查证推翻了本审计对该条的两点描述：**

1. **「缺 curl-pipe-exec」不是漏洞。** 实测 `curl x | sh`、`curl x | /bin/sh`、
   `curl x | env sh`、`wget -O - x | env bash` 等形态**今天全部已被拦**（分别由
   `HARDLINE_COMMAND_DENYLIST` 的 "curl pipe to shell" 与 `CRITICAL_DENYLIST` 的
   `pipe-to-shell` 命中）。该条与 hardline 规则重复，正是本次要消除的那类拷贝。之所以仍在
   SSoT 里保留：Python 侧规则顺序未必与本链路相同，不能凭猜测删；而本链路 hardline 规则排在
   CRITICAL 之前，重复不改变判定结果。
2. **真正的缺陷在相反方向：`redirect-write` 两端不一致。** `denylist.ts` 里那份**已修**
   （加负向后顾 `(?<![2&>])` 排除 `2>` / `&>`，注释写明这是修过的 bug），但**没回写 SSoT** ——
   于是 `critical-rules.json` 及其 Python 拷贝至今仍是旧版 `>\s*[^\s&|]`，
   **Python 侧会把 `cmd 2>/dev/null` 这类合法命令误拦**。本次已把 TS 的修法回写进 SSoT。

**SSoT 另补了 `reasonKey` 字段** —— 原 JSON 没有它，而 TS 的 `DenyRule` 靠它做 i18n 报错，
直接派生会让所有 critical 报错回落成裸 slug。

**零行为变化有实证**：按改造前的拼接方式复现旧表，与运行时派生的表逐条比对 ——
**原有 12 条（含 flags）逐条一致**，新增的只有 `curl-pipe-exec`（上述已证冗余）。
另跑 19 条行为用例（含 `2>/dev/null`、`&>/dev/null` 应放行）全部符合预期。

**顺带被守卫抓了一次，值得记下**：加进 `curl-pipe-exec` 后，
`tests/w1-redirect-hints.test.ts` 立刻变红 —— 它要求每条 deny 规则名都必须有非空 hint。
已在 `deny-rule-hints.ts` 补上（并清掉该文件与 `denylist.ts` 里剩下的 codegen 过期注释）。
**这条守卫是有效的，别再删。**

**未验证 / 遗留**：Python 侧 `generated_critical_rules.py` 仍是旧 `redirect-write`（其头部
指向的 `scripts/codegen-security-rules.py` 同样不存在）。本机跑不了 Django 测试，故**未动**；
留待 Stage B 让 Python 直读 SSoT 时一并解决。

### 第 2 层：electron / daemon 的 IPC 拒读清单 —— 判定为「独立策略」而非拷贝，加守卫

`DEFAULT_DENY_READ_PATTERNS`（electron）与 `REMOTE_DENY_READ_PREFIXES`（daemon）是同一份
11 条清单的两种写法（前者 `~/…`，后者 home 相对，逐条与顺序完全一致）。逐条比对 SSoT 后
判定**不能并入**：

- **本层更严**：SSoT 的 `checkSensitivePath` 是四态判决，「读敏感 + 工作区内 → allow」；
  本层连工作区内的读也拒，并且是 `options.denyReadPatterns` 追加项的默认底座。
- **覆盖面双向不等价**：本表 11 条里 **10 条**被 SSoT 的 `sensitive_path_list` 覆盖，但
  `~/.config/op` 不在 SSoT 中；反过来 SSoT 另有约 40 条（浏览器凭据库、keyrings、
  cargo / gradle / maven 凭据等）不在本表内 —— 并入会把它们一并对 IPC 读拒掉，
  属产品可见的行为变化。

**处理**：保留为独立策略，补说明 + **两条守卫**（都在
`apps/tabtin-electron/src/main/security/__tests__/path-access-checker.test.ts`）：

1. 本表每一项要么被 SSoT 覆盖、要么显式登记在 `SSOT_UNCOVERED_READ_DENY_ENTRIES`
   （当前只有 `~/.config/op`）；另有一条反向断言，防止豁免名单过期。
2. 直接读 daemon 源码，比对两份镜像清单逐条一致（两个 app 之间没有依赖边，只能这样锁）。

两条守卫均做了**负向验证**：注入一个未登记条目后，守卫精确报出差异（`expected
[ '~/.config/op', …(1) ] to deeply equal [ '~/.config/op' ]`）；验证后已还原。
该测试文件 **31/31 通过**。

### 第 2 层：`downloader.ts` 的渲染进程预检 —— 判定为「非权威预筛」，不改行为

`isFilePathSafe`（L503）内联一份 12 条敏感片段清单，与 SSoT 双向漂移（额外含 `/var/`、`/proc/`、
`/sys/`、`/dev/`、`/.config/`、`/windows/system32`、`/windows/syswow64`；同时漏掉 `.aws`、`.kube`、
`.npmrc`、浏览器 Cookie 等）。逐条比对后判定**不该去「对齐」它**：

- **它是渲染进程的检查，而渲染进程不可信。** 真正的闸门在主进程
  `fs:readFilePreview`（`main/file-system/ipc.ts:1279`）→ `checkAndFormat` →
  `path-access-checker.ts`（规则直读 SSoT）。这里命中只是更早、更快地报错；**没命中也不等于放行**。
- 两者本就不是同一层东西：这里是「显眼目录的廉价预筛」，SSoT 才是权威策略。对齐它既不能提升
  安全性（后面还有权威闸门），又会丢掉那 7 条 SSoT 不管的系统目录预筛。

**处理**：补注释写明「非安全边界、非 SSoT 拷贝、差异已知且可接受」，不改行为。

**未验证**：`downloader.test.ts` **跑不起来**（既有问题，A/B 撤掉注释后同样失败）—— 渲染进程
测试项目解析 `@tabtin/table-engine-canvas/i18n` 失败：该包**没有 dist**，而该项目未启用
`source` 条件（该包的 exports 确实声明了 `./i18n` 与 `source`）。本次只改注释，另做了 esbuild
语法校验通过。**这是一类新的既有问题（conditions 未覆盖 + 包未构建），值得单独查。**

### 第 3 层：`daemon/tsup.config.ts:15` 的过期注释 —— 已随死代码一并解决

删除 `copyHardlineRules` 时，那段断言「security-policy 运行时用 createRequire 相对加载
'./hardline-v3-rules.json'」的失效注释已一并移除，换成实证结论。

## Stage B（Python 侧）第一组：`generated_hardline.py` 改为运行时直读 SSoT

`apps/tabtin_django/apps/services/common/generated_hardline.py` 那份 8 个字段、约 200 行的
硬编码拷贝已删除，改为在**导入期直读** `packages/tabtin-shared/src/` 下的两个 JSON
（照 `capability_contract.py` 的 `get_repo_root()` + 导入期 fail-fast 范式），
`re` flags 校验与 TS 侧 `compileFlag` 对齐（只允许 `i`）。

### 本组可验证的关键前提

该模块**只依赖标准库**（`re` / `dataclasses` / `typing`），`repo_root.py` 同样。所以可以
**绕开 conftest 在本地跑**：仓库的 `apps/tabtin_django/conftest.py` 在 `pytest_configure`
里直接 `import django`，本机无 django → 整场中断（这正是「Django 测试本机跑不了」的根因）。
做法：把 `apps` / `apps.services` / `apps.services.common` 注册成空壳模块（避开那 208 行的
`common/__init__.py`），按文件路径加载目标模块，再把测试文件复制到仓库外跑，避开 conftest 的
rootdir 扫描。

已把它固化成仓库脚本：**`apps/tabtin_django/scripts/run_stdlib_hardline_tests.py`**，
无参数即跑本组两个测试文件。

### 证据

| 验证 | 结果 |
|---|---|
| 迁移前固化旧行为快照（8 个常量的 pattern 源码 + 语义 flags） | 9/12/18/18/8/51/33/12 条 |
| 迁移后与快照**逐条比对** | **0 处不一致**（顺带确认与原 JSON 也逐条一致） |
| `test_generated_hardline.py` | **84/84 通过** |
| `test_path_safety.py`（消费 `path_safety.py`，间接消费本模块） | **69/69 通过** |
| 模块公开 API 对比（旧 26 个名字） | **漏掉的：无** |

### 过程中抓到的两个真问题（都值得记）

1. **逐条比对常量「漏掉」了一个导出**：重写时丢了 `HARDLINE_V3_SCHEMA_VERSION`
   —— 它不是规则常量，所以规则级比对**看不见**它，是**真跑测试时 ImportError 报出来的**。
   事后补做完整公开 API 对比才确认没有其他遗漏。
   **经验：规则级比对 + 公开 API 比对 + 真跑测试，三者缺一不可，不能只做第一项。**
2. **换行符被整文件改写**：用 `Path.write_text` 写文件时，Windows 会把 `\n` 转成 `\r\n`，
   而仓库 `.gitattributes` 约定 `eol=lf` —— 整个文件会显示为改动。已改回纯 LF，
   并确认 `@dataclass` 之后的函数区**逐字节未动**。

### 仍未验证

- **Django 全量测试本机跑不了**，上面两条测试是绕开 conftest 单独跑的；`python manage.py test`
  或带 Django 的 pytest 未跑过，需在具备依赖的环境验收。
- 其余 Python 消费方（`sandbox_policy.py` 的 force 表、`authorization_policy.py` 的
  `_FORCE_BLOCK_PATTERNS`、`ssh_execute.py`、`shell_safety.py`、`generated_critical_rules.py`）
  本轮**未动**。

### Stage B 第二组：`path_safety.py` 与跨端契约测试的陈旧叙述

`path_safety.py` 是 `generated_hardline` 的主要消费方；上一组让它直读 SSoT 后，本组清理该模块
里描述「codegen 流程」的整段 docstring，并：

- 导入别名 `_GENERATED_SENSITIVE_PATH_RULES` → `_SSOT_SENSITIVE_PATH_RULES`（原名已失真）。
- 把 `_DANGEROUS_TOPLEVEL_DIRS` / `_DANGEROUS_WINDOWS_ROOTS` **显式登记为已知残余**：
  它俩仍是两端各自手抄、未纳入 SSoT，注释里写明「改一端必须改另一端，且目前没有守卫能自动
  发现漏改」。本审计该条要求「要么纳入 SSoT，要么显式豁免」，本轮**选后者**（这对常量短小、
  与 hardline 规则无关；要收敛应搬进 `packages/tabtin-shared/src/` 再两端派生）。
- `test_path_safety.py` 里 class docstring 的「W7/B2 codegen 接入」叙述改为「两端运行时直读同一份 SSoT」。

**验证**：`run_stdlib_hardline_tests.py` **153 passed**（含 `test_path_safety.py` 的 69 条）。
本组只改注释与别名，未动任何判定逻辑。

### 待决策：`generated_critical_rules.py` 是完全孤儿

`apps/tabtin_django/apps/services/tools/domains/common/generated_critical_rules.py`（28 行，
stdlib-only）**全仓无人 import** —— 只有自引用（`CRITICAL_DENY_RULES` 派生的
`PRE_SPLIT_RULES` / `POST_SPLIT_RULES` / `ALL_RULES` 都由它自己定义，无人消费）。
它的头部指向同样不存在的 `scripts/codegen-security-rules.py`，内容是 `critical-rules.json` 的
**旧版**拷贝（含那个已确认的 `redirect-write` 缺陷：会把 `cmd 2>/dev/null` 误拦）。

处理方式二选一 —— **删掉**（它是死代码，删掉即达成单一来源）或**改为直读 SSoT**
（`critical-rules.json` 已在 `packages/tabtin-shared/src/`）。**删文件不在本次迁移的单方面
授权范围内，需仓库所有者确认。**

### Stage B 第三组：合并两个同名 `check_safety_hardline`（附精确行为翻转清单）

审计指出「存在两个同名 `check_safety_hardline` 实现被不同调用方消费 —— 这是拷贝漂移的真实
证据，Stage B 必须合并为单一来源」。本组完成合并。

**先量化的漂移**（`authorization_policy` 的旧表 vs SSoT）：

- `_FORCE_BLOCK_PATTERNS` **8 条 vs SSoT 9 条** —— 少 `eval with $VAR`；另有 3 条只是写法不同的
  变体（fork bomb 不容空格、wget 要求 `-O -`、chmod 字符类 `\w` vs `[a-zA-Z]`）。
- `_FORCE_CONFIRM_PATTERNS` **10 条 vs SSoT 12 条** —— 少 `id_dsa` / `id_ecdsa`（其余 10 条
  pattern 逐字一致）。

**两处实现还有三处语义差异**：返回类型（tuple + 中文理由 vs `HardlineVerdict`）、判定顺序
（逐文本 block→confirm vs **先全量 block 再全量 confirm**）、扫描字段（7 个手写 vs SSoT 声明的
18 个 `sensitive_field_names`）。

**改动**：

- `authorization_policy.py` 删掉两张表、`_extract_matchable_strings`、`check_safety_hardline`、
  `SafetyVerdict`，只留 `_TOOL_CATEGORY_OVERRIDES`（它仍被 rule_engine 消费）。
- `rule_engine.py` 改用 `generated_hardline` 的版本，消费 `HardlineVerdict.kind`
  （它本就丢弃理由字符串 `verdict, _reason = hardline`，故**无文案影响**）。
- `permissions/__init__.py` 的再导出同步换源（该再导出无外部消费者）。

**精确行为翻转清单** —— 改动前把同一批用例同时喂给两个实现跑出来的，**全部朝「更严」**：

| 用例 | 旧 | 新 |
|---|---|---|
| `eval $X` | 放行 | **block** |
| `wget http://x \| sh`（无 `-O -`） | 放行 | **block** |
| `: ( ) {`（fork bomb 带空格） | 放行 | **block** |
| `{path: '/p/.env', shell: 'rm -rf /'}` | confirm | **block** |
| `/backup/id_dsa`（不在 `.ssh/` 下） | 放行 | **confirm** |
| `/backup/id_ecdsa`（不在 `.ssh/` 下） | 放行 | **confirm** |

（`/backup/id_rsa` 两边一致 —— 旧表已有 `id_rsa`；路径含 `.ssh/` 时 id_dsa/id_ecdsa 也不体现
差异，因为旧表的 `\.ssh/` 会先命中。所以上表用的是**隔离后的**用例。）

**验证**：`run_stdlib_hardline_tests.py` **153 passed**；三个改动文件 `py_compile` 通过；
已删除符号全仓零残留（只剩 `authorization_policy.py` docstring 里的说明文字）。

**未验证**：`rule_engine.py` / `permissions/__init__.py` 属 Django 应用链，本机加载不了，
只做了语法检查。**上表那 6 处翻转的端到端影响需在有依赖的环境验收** —— 尤其
「confirm → block」那条会让原本只弹审批的操作变成直接拒绝。

### Stage B 第四组：`shell_safety.py` 的敏感路径表 + `test_generated_hardline.py` 的两处

**① `shell_safety.py`** —— 那份 `_SENSITIVE_PATH_RE` 是把「绝对路径红线 + `path_scan_rules`
子集」手工拼成的一个正则，已删除，改为从 `generated_hardline` 派生。

关键点：**必须同时用两个表**。`SENSITIVE_PATH_RULES`（← `path_scan_rules`）里**没有 `.env`**，
而 `.pem` / `.key` / `.env` 只存在于 `SENSITIVE_BASENAME_PATTERNS`（← `path_basename_patterns`）
—— 只用 substring 表会**丢掉 `.env` 检测**，那是削弱。另外 `/dev/` 不在 SSoT 里，作为本模块
独有的额外项显式保留（否则会在收敛时被顺手丢掉）。

**先固化后比对**（43 个 token 的判定快照）：

| | 改动前 | 改动后 |
|---|---|---|
| 判定为敏感 | 16 | **37** |
| **失去敏感（= 削弱）** | — | **0 ✅** |

新增覆盖的例子：`/etc/gshadow`、`/etc/master.passwd`、`/etc/security/`、`/etc/login.defs`、
`/proc/*/environ`、`/var/log/auth.log`、`/run/secrets/`、`.netrc`、`.pgpass`、`.my.cnf`、
`~/.aws/credentials`、`~/.kube/config`、`~/.docker/config.json`、`.crt`、`.kdbx`、`id_dsa`、
`id_ecdsa`、`.p12`、`.p8`、`.pfx`。方向正确：本模块是「只读快路径」分类器，**命中即退回完整
审批链**，规则更全 = 更保守 = 更安全。

命令级验证：`cat /etc/passwd` → False（不再走快路径）；`ls -la` / `cat notes.txt` /
`head README.md` / `find /home -name x` → 仍 True（快路径保留）。

**② `test_generated_hardline.py:12`** —— 头部声称「所有用例必须与 TS 侧
`packages/security-policy/tests/hardline.test.ts` 语义对齐」。查证：**该文件在 git 全历史中
从未存在**（只有 `hardline-v3.test.ts`），且 **v1 规则在 TS 侧根本没有消费方**。已改写为按
v1 / v3 分别说明实际对齐范围。

**③ `test_generated_hardline.py:53`** —— 注释与断言一起修：原 `assert len(...) >= 9 / >= 10 /
>= 18` 是审计「测试守卫缺口」点名的**假测试**（下界会放行「SSoT 加了一条、消费端没跟上」），
已改为等值 `== 9 / == 12 / == 18`；收紧后测试仍全绿，说明计数确实精确。
注释里的 `hardline.ts` 同样从未存在，已一并更正。

**验证**：`run_stdlib_hardline_tests.py` **153 passed**（含收紧后的等值断言）；
`shell_safety.py` `py_compile` 通过。

**未验证**：`shell_safety.py` **没有任何测试**（全仓无对应测试文件），只有一个消费方
`ai_commands/permissions/ai_classifier.py` 把它当快路径谓词。上面的 43-token 比对是我自建的
证据，不是仓库既有的回归测试。**判定从 16 项扩到 37 项会让更多命令退回完整审批链，这个端到端
影响需在有依赖的环境观察。**

### 清单外的相邻缺口（已闭合）

SSoT 有**三个**路径表，上面那一步只覆盖了其中两个。第三个 `sensitive_path_list`
（四态判决用）里的「点文件型」凭据 —— `.npmrc`、`.pypirc`、`.git-credentials`、
`.cargo/credentials`、`.m2/settings.xml`、`.gradle/gradle.properties`、`.config/gh`、
`.config/helm`、`.config/pulumi`、`.terraformrc`、`.terraform.d/credentials.tfrc.json`、
`.local/share/keyrings`、`.gem/credentials` —— 当时**不在覆盖范围内**。

**已补上并验证**：把 `SENSITIVE_PATH_LIST` 一并接入 `_is_sensitive_token`。

| | 改动前 | 改动后 |
|---|---|---|
| 56 个 token 中判为敏感 | 33 | **46** |
| **失去敏感（= 削弱）** | — | **0** |

命令级：`cat ~/.npmrc`、`cat ~/.git-credentials` → **False**（不再走快路径）；
`ls -la` / `cat notes.txt` / `head README.md` / `git status` → 仍 True（快路径保留）。

**同时补上了该模块的测试**（它此前**零覆盖**）：
`apps/services/agent_engine/tests/test_shell_safety.py` —— 用 `unittest.TestCase` 而非
`SimpleTestCase`，因为被测的是纯函数、不需要 Django，这样在没有 Django 依赖的环境里也能跑
（已纳入上面的验证脚本）。覆盖：三类凭据路径判敏感（含新增的「点文件型」）、普通文件保持
快路径安全、metachar / 未知可执行 / 空命令一律 fail-close。

**负向验证**：临时移除 `SENSITIVE_PATH_LIST` 检查 → 测试精确报出
``AssertionError: True is not false : 'cat ~/.npmrc' 不应走快路径``（2 failed）；还原后 5/5 通过。
**说明这条测试确实能抓到该缺口**，不是摆设。

验证脚本现跑到 **158 passed**（含新增 5 条）。

### Stage B 第五组：`sandbox_policy.py`（2 条完成，1 条需决策）

**① `HIGH_RISK_PATTERNS`（:226）—— 更正假声明 + 显式声明来源，但「去重」判定不适用。**

旧注释自称「SSOT，`@tabtin/security-policy` 的 Python 端镜像」—— **这句是错的**：TS 侧
（`packages/security-policy/src`、`packages/tabtin-shared/src`）**不存在**与本表对应的命令
审批表，本表是 Python 侧独有的。

与 hardline SSoT 的实际关系已核对并写进注释：22 条里 **14 条**是
`absolute_command_denylist` 同名规则的**放宽版**对应物（rm-recursive / dd / sudo / chmod-777 /
mkfs / fork-bomb / shutdown-reboot / kill-force / chown-recursive / mv-devnull / write-device /
format-drive / iptables-ufw / systemctl-stop），另 **8 条 SSoT 没有**（git-push /
docker-build-push / kubectl-mutate / npm-publish / terraform-apply / scp / rsync / curl-mutate）。

**为什么没按审计建议「去重同源条目」**：

- 语义不同 —— SSoT 的 denylist 是**绝对拒绝**，本表只是置 `approval_required`（走 HITL 审批）。
- **代码路径不同，且这里没有兜底** —— 本模块**全文件不引用 hardline**（零
  `check_safety_hardline`），是一条独立路径。删掉那 14 条会让这些命令**在本路径上失去审批
  触发**，而 hardline 不在这条路径上，属净削弱。

所以保留是有意的纵深防御。真要收敛，得先在 SSoT 里显式表达「需审批（而非拒绝）」这一档
（例如给条目加 approval 维度），再两端派生 —— 共享契约变更，**未做**。

**② `_matches_sensitive_path`（:484）—— 验证类，已通过。** 它是 Python 侧安全判定的实际运行
消费点（D10：workspace short-circuit 前保留 sensitive 红线），规则经 `path_safety` 来自
`generated_hardline`。Stage B 改规则来源后「短路径行为不能退化」的验证依据是：8 个常量与迁移前
**逐条一致** + `test_path_safety.py` **69/69 通过**。故本模块无需改动。

**③ `_DEFAULT_SENSITIVE_DENY_WRITE_PATHS`（:174）—— 仍需决策，见下。**

### Stage B 第六组（收官）：deny-write 收敛、孤儿文件删除、两处新守卫

**① 删除两个孤儿文件**（经确认）：`generated_critical_rules.py`（28 行，全仓无人 import；
`tool_registry.py` 用的是**显式 import 列表而非目录扫描**，已核实）与 `ssh_execute.py`
（同样未注册、无调用方）。前者还带着已确认的 `redirect-write` 缺陷。删除后无断引用
—— `authorization_policy.py:34` 的 `'ssh_execute': 'script'` 是工具名→类别的字符串键，
工具若由 TS 侧提供则仍有效，予以保留。

**② `_DEFAULT_SENSITIVE_DENY_WRITE_PATHS` 收敛进 SSoT**：`hardline-v3-rules.json` 新增
`always_protect_write_paths` 字段（**glob 形态** —— 与文件里其他 regex 字段不同，故用普通
字符串列表），`generated_hardline` 暴露 `ALWAYS_PROTECT_WRITE_PATHS`，`sandbox_policy` 改为
`list(...)`（独立副本，不共享可变对象）。写入前先确认 JSON 往返无损，写入后逐条比对
**含顺序完全一致**。

**③ `localSandboxPolicy.ts:22` 显式豁免 + 守卫 —— 过程中实测推翻了两个说法。**

- 我起初在注释里写「SSoT 只有 `.aws/credentials`，本表是 `.aws/` 整目录，故本地更严」
  —— **错**。`path_scan_rules` 确实只有 `.aws/credentials`，但 `sensitive_path_list` 里有
  `(^|/)\.aws(/|$)`，**整目录是被覆盖的**。实测 `checkSensitivePath('/p/.aws/config')` → `ask`。
- 我又写「SSoT 只认正斜杠，本表额外认 Windows 的 `.ssh\`」—— **不成立**：SSoT 匹配前会先做
  路径规范化。

修正后的事实：7 条里 **4 条**（`.env` / `.ssh/` / `.gnupg/` / `.aws/`）与 SSoT 重叠，
**3 条**（shell 脚本后缀 / Dockerfile / docker-compose）SSoT 没有。守卫测试
`packages/terminal-core/tests/sensitive-file-patterns-drift.test.ts` 钉住该差异，并做了
**负向验证**（注入一条未登记 pattern → 精确报出 `secret-backup/` 差异；还原后 3/3 通过）。

**④ i18n 三向守卫**（`packages/security-policy/tests/i18n-hardline-keys.test.ts`）：钉住
SSoT 规则名 → `i18n-keys.json` 的 `hardlinePattern`（26 键）→ 8 个 locale 的 `chat.json` 的
`approval.reason.hardlinePattern.<slug>`。核实「26 = 18 命令 + 8 路径」**完全对应、无多余无缺失**。
负向验证：从 zh-CN 删掉一个 slug → 精确报出 ``zh-CN: 缺 1 个 slug（如 rm_rf_root_or_home）``；
还原后 4/4 通过。（`slugToI18nKey` 在 `ApprovalPanel.tsx` 里未导出，测试内**复刻**了一份并注明
来源 —— 那边改实现时这里要同步。）

**验证**：terminal-core 全量 **6 failed / 11 tests**（与已知环境性基线逐字一致），通过文件数
42 → 43；security-policy 新增测试 4/4；harness **153 passed**；tabtin-shared 已重建
（dist 含新字段）。

---

## 清单至此全部完成（80/80）

原 72 条 + 「已完成并验证」8 条 = **80 条全部勾选**。

**本审计在不同阶段被实证推翻或修正的判断**（供后续复查参考，别再照抄结论）：

| 原判断 | 实测结果 |
|---|---|
| `electron.vite.config.ts:518` 吞异常（待修） | 本次改动里**已经修好了**（有 `throw error`） |
| `daemon/tsup.config.ts:28` 的 `require.resolve` 会抛错 | 靠给 tabtin-shared 补 `default` 导出条件**已解决** |
| `CRITICAL_DENYLIST` 缺 `curl-pipe-exec` 是漏洞 | **不是** —— `curl x \| sh` / `wget … \| env sh` 等已被 hardline 或 `pipe-to-shell` 拦下；真正的问题是反向的 `redirect-write` 漂移 |
| `checkOpaquePowerShellCommand` 的 tier 硬编码「顺带覆盖」 | **改了是回退**（`eval expansion` 在 SSoT 里是 `risk`） |
| electron/daemon 的 IPC 拒读表「是 SSoT 的拷贝，应并入」 | 是**独立且更严的一层策略**，并入会双向改行为 |
| `downloader.ts` 的敏感片段「应对齐 SSoT」 | 那是**渲染进程的非权威预筛**，主进程才是闸门 |
| `HIGH_RISK_PATTERNS`「去重同源条目」 | 语义与代码路径都不同，去重会让这些命令**失去审批触发** |
| `localSandboxPolicy.ts:22` 的 `.aws/` 派生会削弱底线 | `.aws/` 整目录**已被 SSoT 覆盖**（我先前只看了 `path_scan_rules`） |
| 「把 vite 泛别名改成锚定正则」是根治方案 | 推广会打断 3 个在用的子路径，**已否决** |
| `scripts/backend` 之外的 `scripts/dev/menu.sh` 存在 | **不存在**（compose 注释里的失效引用） |

**后续补跑：三个「未验证」缺口已收掉两个**（做法是先 `pnpm -r --filter "./packages/*" --no-bail build`
把 workspace 包补齐 —— 此前 84 个包里有 **77 个从未在本地构建过**，结果 78 成功 / 1 失败，
失败的 `@tabtin/cli` 与本次无关）：

| 缺口 | 现状 |
|---|---|
| **daemon 端到端** | **已收**。补齐依赖后 daemon `tsup` 构建成功（ESM + DTS），产物实证：dist 里**没有** `hardline-v3-rules.json`、**没有**它的 import 语句、规则内容（含新增的 `agent_spawn_floor`）**已内联** —— 当初删掉 `copyHardlineRules` 的判断从「只有逻辑证据」变为**产物级证据** |
| **electron 渲染进程测试** | **已收**。`downloader.test.ts` 此前因 `table-engine-canvas` 无 dist 而整个文件加载失败；补建后 **3/3 通过** |
| **Django 全量** | 仍未跑 —— 需要 Python 3.11 的 venv 与可连的 PostgreSQL/Redis，步骤已写进 `docs/development/getting-started.md` 的「运行后端测试」 |

**daemon 测试套件现在也能跑了**（此前同样因缺 dist 而无法启动）：101 个文件 / 1131 用例，
**16 files / 39 tests 失败**。成因分布：**15 个 `listen EACCES`（Windows 无法按测试期望创建
Unix domain socket `.sock`）**、2 个超时抖动、4 个 Windows 路径语义（`/etc/shadow` →
`D:\etc\shadow`），其余为杂项。**没有一条与 hardline / critical-rules 相关。**

其中 2 条路径类失败已**读代码确证**为既有问题、非本次引入：测试 `w10-f1-security-fixes` /
`w11-f1-security-fixes` 期望 `/protected system path|outside the allowed workspace/`，而
`validateProjectPath` 的 **read 分支**兜底消息是 `path is outside allowed directories`
—— 「allowed directories」既不匹配前者也不匹配后者的「the allowed workspace」（那是 **write
分支**的措辞）。Windows 下 `isHardDeniedPhysical('D:\\etc\\shadow')` 为 false（反斜杠），
于是落到兜底；旧代码的数组判定同样匹配不到 `D:\etc\shadow`，消息也非本次改动。Linux 上
`resolve('/etc/shadow')` 保持原样、红线命中，测试通过。

**注意：daemon 套件没有基线**（此前从没跑起来过），所以这里只做归因、**不主张「零回归」**。

### 环境坑（与迁移无关，但会直接误导验证）

**本地 `dist` 是否存在会显著改变测试结果。** security-policy 在 dist 缺失时是
7 failed files / 2 failed tests（与本审计基线逐字吻合）；dist 存在时变成 4 files / 7 tests
（vitest 对 `@tabtin/terminal-core` 等的解析目标由 `source` 变为 `dist`）。
terminal-core 则相反：dist 缺失时 20 files / 70 tests 失败，存在时 6 files / 11 tests。

**比对测试基线前必须先声明 dist 状态**，否则会把自己的构建产物误判成代码回归
（本轮一度如此，靠「撤掉改动重跑」的 A/B 才排除）。本轮的零回归结论是在相同 dist 状态下取得的。

**terminal-core 另有一批抖动失败。** 稳定复现的是 6 个环境性失败文件
（`atomicWrite` / `browser-entry` / `execute-streaming` / `space-paths-hardcut` /
`tc4-alias-bypass` / `tds-regression`；成因是 Windows 无 `/bin/sh`、路径分隔符、POSIX 文件 mode）。
但 `agent-output-decode.test.ts` 与 `agent-shell-windows.test.ts` 会在全量并行跑时
`Test timed out in 5000ms`，**单独跑则 21/21 全过**；全量结果因此在 6–8 failed files 之间跳动
（同一份代码连跑三次得到 13 / 14 / 17 failed tests）。**判断回归前先隔离复跑可疑文件**，
别把超时抖动当成代码回归。

## 待办清单

### 会坏的构建与测试（7 条 —— 已全部完成，见上）

现在就会红，或构建产物缺文件；不修则后续所有改动都建在流沙上。

- [x] `apps/tabtin-daemon/tsup.config.ts` 第 26 行
  - 位置属实，无需改地址；需要把原描述的「需核实」换成已核实结论：这不是「路径更新正确、待观察」，而是「路径更新已完成，但该拷贝步骤已失去存在理由、其注释理由也是错的」。准确表述：`apps/tabtin-daemon/tsup.config.ts:26-36` 的 `copyHardlineRules()` 把 `@tabtin/shared/dist/hardline-v3-rules.json` 拷到 `dist/` 与 `dist/workers/`（102/119 行挂 onSuccess）；但 line 15-25 注释所称的理由——security-policy 运行时用 `createRequire(import.meta.url)('./hardline-v3-rules.json')` 相对路径加载——已在本次重构中被删除（`packages/security-policy/src` 中 `createRequire`/`readFileSync`/`import.meta.url` 均零命中，`hardline-v3.ts:16` 与 `terminal-core/src/denylist.ts:2` 现为静态 ESM JSON import），而 daemon 的 package.json 把 `@tabtin/security-policy`、`@tabtin/shared` 都列为 workspace 依赖（进 noExternal），JSON 由 esbuild 内联进 bundle；全仓库没有任何运行时按相对路径读该 JSON 的代码。因此该步骤应判定为死拷贝：处理方式为删除 `copyHardlineRules` 及两处 `onSuccess`、或（若出于部署保险要保留）改写注释说明真实理由；`apps/tabtin-electron/electron.vite.config.ts:509-520` 的同类拷贝需一并核实。注意：以上内联结论未做构建实证（daemon/security-policy 的 dist 均不存在）。
  - *为何在范围内*：这是本次改动触及的打包拷贝步骤；且 line 15-25 的注释理由（『security-policy 运行时用 createRequire('./hardline-v3-rules.json') 相对路径加载』）在 hardline-v3.ts 改为 ESM import 后已失效——需核实该拷贝是否仍有必要（esbuild 可能已内联 JSON），否则成为死步骤。
- [x] `packages/security-policy/tsup.config.ts` 第 33 行
  - 修正后的准确表述：文件 packages/security-policy/tsup.config.ts 的 onSuccess 后处理有两处与本次 hardline SSoT 重构脱节： (1) 35-39 行的 JSON 拷贝循环对 hardline 规则已成空操作（src 下已无 hardline-*.json），但它仍承担 critical-rules.json / i18n-keys.json 的拷贝，属「已不能覆盖 hardline、又还不能删」的遗留 —— 只能更新注释/明确服务对象，不可整体移除。 (2) 真正未处理的缺陷在 61-64 行的 import attribute 补丁：其正则只匹配相对路径 `\.\.?\/`，而 hardline-v3.ts:16 已改用裸包 specifier '@tabtin/shared/hardline-v3-rules.json'。实测构建后 dist/hardline-v3.js 第 1 行为 `import rulesData from "@tabtin/shared/hardline-v3-rules.json";`（无 `with { type: "json" }`），Node ESM 直接加载该产物报 ERR_IMPORT_ATTRIBUTE_MISSING；electron dev 下 main 将 workspace 包 external（electron.vite.config.ts:739）后正是走这条 Node 解析 dist 的路径，会启动失败（该端到端结论未经实跑验证）。修法：把补丁正则从「仅相对路径」扩展为同时覆盖裸包 JSON specifier（如 `from ['"][^'"]+\.json['"]`，但要排除已带 attribute 与 node: 内置），或改为在源文件 import 时直接写 `with { type: 'json' }`（TS 5.3+ 支持，可让补丁彻底退役）。原描述的行号 31-36 / 46-49 应更正为 35-39 / 61-64。
  - *为何在范围内*：属于同一重构的遗留打包逻辑：① 该 JSON 拷贝循环对 hardline 已成死代码，应清理/收窄；② 裸 specifier 的 JSON import attribute 补丁缺口需验证（Node ESM 直跑 dist 时可能 ERR_IMPORT_ATTRIBUTE_MISSING），否则 daemon/electron 运行时会炸。
- [x] `apps/tabtin-daemon/tsup.config.ts` 第 28 行
  - copyHardlineRules() 用 `dirname(require.resolve('@tabtin/shared'))` 定位 JSON。实测该调用会抛 ERR_PACKAGE_PATH_NOT_EXPORTED：@tabtin/shared 的 "." 导出只声明了 source/types/import，没有 require/default 条件，createRequire 解析不到。改路径时只换了包名，没换成导出子路径。可用写法已验证：`require.resolve('@tabtin/shared/hardline-v3-rules.json')` 成功解析到 packages/tabtin-shared/dist/hardline-v3-rules.json。该 onSuccess 挂在两个 config 上（dist/ 与 dist/workers/），任一失败都会让 daemon 构建在拷贝阶段挂掉。
  - *为何在范围内*：这是本次『拷贝路径更新』改动引入的构建错误：JSON 已迁到 tabtin-shared，但 daemon 的取源方式（require.resolve 裸包名）与 tabtin-shared 的 exports 条件不兼容，属重构范围。
- [x] `apps/tabtin-electron/electron.vite.config.ts` 第 518 行
  - hardline-v3-rules.json 的拷贝被包在 try/catch 里，catch 只 `console.error(...)` 不抛出、不中断构建（对照同插件里 fingerprint-preload.js 也是同样写法）。一旦路径写错（正是这次改动最容易犯的错），构建照样成功，问题推迟到运行时才暴露。任务点名的『catch 里吞掉拷贝失败』就是这里。
  - *为何在范围内*：这次重构刚好改了这条路径，吞异常使得改错不会被构建捕获，属重构需处理的脆弱点。
- [x] `packages/security-policy/tsup.config.ts` 第 61 行
  - 描述基本准确，两点精确化：1) 正则字面量在第 62 行（第 61 行是 `out = out.replace(`），完整正则为 `/(\bfrom\s+["']\.\.?\/[^"']+\.json["'])(?!\s+with\s+\{\s*type:\s*["']json["']\s*\})/g`，发现中只引了前半段。2) terminal-core 同款问题可确认机理但不完全等价：其构建命令 `tsup src/index.ts src/browser.ts src/agent-bridge-contract.ts --format esm --dts --external vitest` 依赖 tsup 默认把 package.json dependencies 外部化，`@tabtin/shared` 在 dependencies 中故被 external，src/denylist.ts:2 的裸 JSON 导入会留在 dist，且 terminal-core 构建没有任何 attribute 后处理 —— 因此同样会 ERR_IMPORT_ATTRIBUTE_MISSING（我未构建 terminal-core 产物做实证）。3) 影响面应表述为「electron dev main / 任意 Node ESM 直载 SP dist」，而非所有消费方：daemon 与打包版 electron 会 bundle，不受影响。
  - *为何在范围内*：迁移把相对导入换成跨包裸导入，直接绕过了这条构建后处理，是本次重构引入的跨端加载回归。
- [x] `packages/terminal-core/package.json` 第 35 行
  - terminal-core 无 tsup.config，构建即 `tsup src/index.ts src/browser.ts src/agent-bridge-contract.ts --format esm --dts --external vitest`。已核 tsup@8.5.1 源码（node_modules/.pnpm/.../tsup/dist/index.js 的 runEsbuild）：默认把所有 production deps（dependencies/peerDependencies）按 `^dep($|/|\)` 正则设为 external。terminal-core 依赖里有 @tabtin/shared，故 denylist.ts 的 `@tabtin/shared/hardline-v3-rules.json` 导入保持 external、不会被内联，运行时仍从包解析；而 allowlist.ts 的相对导入 `./sensitive-paths.generated` 属首方源码、必然被打进 dist —— 即 terminal-core 构建会内联一份手工拷贝（path_scan_rules）。
  - *为何在范围内*：任务要求覆盖『内联』类构建步骤：这里构建把 src/sensitive-paths.generated.ts（本次要废除的拷贝）烘进产物，同时 SSoT JSON 走外部解析，正是重构要厘清的两条路径。
- [x] `apps/tabtin_django/apps/services/common/tests/test_path_safety.py` 第 302 行
  - TestCodegenIntegrity.test_generated_outputs_in_sync_with_json_ssot 先 `assert codegen_script.exists()` 再 subprocess 跑 `python scripts/codegen-hardline.py --check`，用来校验 generated 产物与 SSoT JSON 一致。实测 scripts/codegen-hardline.py 在仓库中不存在（scripts/ 下没有，全仓 grep 仅命中 py 源码/测试/pyc），该断言必然失败。这是本次去拷贝要一并撤掉的『codegen 一致性门』。
  - *为何在范围内*：它是一个会失败的构建/CI 校验步骤，且正是围绕被删掉的 codegen 产物建的，属重构必须处理项。

### 规则的第二份拷贝（21 条）

本次重构的正题：同一份规则被固化在多个文件里，改一处即漂移。

- [x] `packages/terminal-core/src/sensitive-paths.generated.ts` 第 1 行
  - 文件头明写 "AUTO-GENERATED by scripts/codegen-hardline.py / DO NOT EDIT MANUALLY"（第 1-3 行），导出 SENSITIVE_PATH_RULES（33 条 {label, pattern}，第 19-53 行）。内容 = hardline-v3-rules.json 的 path_scan_rules 字段逐条固化为 new RegExp(...)。消费方已核实：packages/terminal-core/src/allowlist.ts 第 3-5 行 import（别名 GENERATED_SENSITIVE_PATH_RULES），第 24 行再导出为 SENSITIVE_PATH_RULES，第 61 行 matchSensitivePath() 循环使用；经 src/index.ts:20 与 src/browser.ts:22 对外导出，下游 packages/action-tools/src/utils/path-validation.ts:80 与 apps/tabtin-electron/src/main/security/path-access-checker.ts:267 都调用 matchSensitivePath。测试 packages/terminal-core/tests/w7-b2-codegen-cross-end.test.ts 直接断言该数组。这正是“path_scan_rules 的第二份拷贝”，与 generated_hardline.py:SENSITIVE_PATH_RULES 同源双份。
  - *为何在范围内*：本次重构要废掉所有手工/生成拷贝，让 hardline 规则只剩一份来源。本文件是把 SSoT 的 path_scan_rules 派生并固化进 TS 源码的产物，且其头部生成器 scripts/codegen-hardline.py 在全仓不存在（find 无结果），属于必须并入 SSoT 直读或 fail-closed 的拷贝。
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 1 行
  - 原描述基本准确，三处需修正：(1) SENSITIVE_PATH_LIST 是 51 条而非 44 条（JSON sensitive_path_list 亦为 51）；(2) ABSOLUTE_COMMAND_DENYLIST 定义在第 85 行（非 84），path_safety.py 的 import 块是 43-46 行（非 43-45）；(3) 最重要：SENSITIVE_FIELD_NAMES（L57，18 条）并非「手写无 JSON 对应」，packages/tabtin-shared/src/hardline-rules.json 的 sensitive_fields 字段正是其 JSON 对应且内容逐条相同，因此它是第 7 个拷贝字段，应与其余 6 个字段一并纳入去拷贝处理，而非单列为手写项。
  - *为何在范围内*：这是本次要废掉的最大一处“规则固化成文件”——整份 hardline 规则在两个 JSON 里的六个字段被原样搬进 Python 源码。重构目标是让 Python 侧运行时直接读 SSoT（照 capability_contract.py 的 get_repo_root()+导入期 fail-fast 模式），本文件是核心去拷贝对象。
- [x] `apps/tabtin_django/apps/services/common/authorization_policy.py` 第 38 行
  - _FORCE_BLOCK_PATTERNS 实为 8 条（第 54-61 行），不是 7 条：rm -rf / 、fork bomb、mkfs.、dd if=.*of=/dev/、>/dev/sd、chmod 777 /、curl|sh、以及原描述漏掉的第 61 行 wget -O - | sh（wget pipe to shell）。_FORCE_CONFIRM_PATTERNS 为 10 条（第 39-48 行），描述正确。漂移表述应更正为：本文件 force_block 8 条 vs SSoT/generated 端 9 条；force_confirm 10 条 vs 12 条。其余路径、行号、消费方与注释内容均属实。
  - *为何在范围内*：任务描述点名的“v1 规则手工镜像”，且已证实与 SSoT/generated 端产生条目漂移。要“规则只剩一份来源”，这两张表必须改为从 hardline-rules.json 派生或删除。
- [x] `packages/action-tools/src/utils/path-validation.ts` 第 43 行
  - HARD_DENY_READ_PHYSICAL = ['/etc/shadow', '/etc/sudoers', '/etc/gshadow']（第 43-47 行）是 path_scan_rules 中对应三条规则的又一份手工固化，第 80 行 isHardDeniedPhysical() 用它做物理路径等值/前缀判定，与紧随其后的 matchSensitivePath(physicalPath)（来自 @tabtin/terminal-core）叠加成“红线”。本条并非 codegen 产物（无 AUTO-GENERATED 头），是纯手抄子集，但语义上就是 hardline 路径红线的第二份定义。消费方：同文件 validateProjectPath() 的 read/write 分支（第 128 行注释确认“红线先于任何放行”）。
  - *为何在范围内*：重构目标是路径规则只剩 SSoT 一份。此处 3 条路径与 hardline-v3-rules.json:path_scan_rules 完全重复，且因为靠 matchSensitivePath 已覆盖同样语义，属于可合并/删除的规则拷贝，价值在于它不带头注释、极易被漏掉。
- [x] `apps/tabtin_django/apps/services/common/sandbox_policy.py` 第 226 行
  - 原描述的实质成立，但需修正三点：(1) 头注释在第 217 行，不是 220 行，原文为 "# 高危命令模式（触发 HITL 审批）— SSOT，@tabtin/security-policy 的 Python 端镜像"；(2) "镜像 @tabtin/security-policy" 这一自我声明不成立——packages/security-policy/src 与 packages/tabtin-shared/src 全树无 HIGH_RISK_PATTERNS 或等价命令审批表，TS 侧最接近的 packages/terminal-core/src/localSandboxPolicy.ts 的 AGENT_SPAWN_CATASTROPHIC_RULES 是 hardline 规则名的子集、与本表条目不对应；SSoT 现位于 packages/tabtin-shared/src/hardline-v3-rules.json；(3) 与它构成实际重复的不是"领域重叠"而是可验证的正则级复制：\b(shutdown|reboot|halt|poweroff)\b、"mv to /dev/null"、">\s*/dev/sd[a-z]"、"systemctl stop|disable|mask" 前缀与 hardline-v3-rules.json:absolute_command_denylist / generated_hardline.py 对应条目逐字符或近乎逐字符相同，约 14/18 条 denylist 在本表有放宽版对应物。同时须标明语义差异：本表用于置 approval_required（HITL 审批），非绝对拦截，且含 denylist 未覆盖的 git push/docker/npm publish/scp/rsync/terraform，因此正确处理是去重同源条目+显式声明来源，而非删表。
  - *为何在范围内*：任务要求“废掉所有手工拷贝”，此处是 Python 侧命令危险规则的第二/第三份定义，与 hardline denylist 同域却独立维护，是本次容易漏掉的拷贝/镜像点（未列入任务已知清单）。
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 28 行
  - Python 端整份硬编码拷贝：FORCE_BLOCK_PATTERNS(L28-38) / FORCE_CONFIRM_PATTERNS(L41-54) 逐条复刻 hardline-rules.json 的 force_block / force_confirm（正则源码与 flags 完全一致：递归删根、fork bomb、mkfs、dd if= 写 /dev/、重定向到 /dev/sd*、chmod 777 /、curl|sh、eval $VAR）；ABSOLUTE_COMMAND_DENYLIST(L85-104)、ABSOLUTE_PATH_DENYLIST(L107-116)、SENSITIVE_PATH_LIST(L119-171)、SENSITIVE_PATH_RULES(L177-211)、SENSITIVE_BASENAME_PATTERNS(L218-231) 逐条复刻 hardline-v3-rules.json 的同名字段。文件头部自述该生成器已不在仓库、改 SSoT 后必须手工同步三端产物。
  - *为何在范围内*：本次重构要废掉的就是这份 TS/Python 手工拷贝；它是“去拷贝”目标里 Python 侧最大的一块，且当前只能靠人手同步，SSoT 一改即漂移。
- [x] `packages/terminal-core/src/sensitive-paths.generated.ts` 第 19 行
  - SENSITIVE_PATH_RULES(L19-53) 是 hardline-v3-rules.json 中 path_scan_rules 的 TS 生成物拷贝（33 条 label+RegExp，覆盖 /etc/shadow、/etc/passwd、.ssh/、.aws/credentials、.gnupg/、.kube/config、shell-history、Keychains、id_(rsa|ed25519|ecdsa|dsa) 等），头部仍写 AUTO-GENERATED by scripts/codegen-hardline.py。
  - *为何在范围内*：与上一轮已删除的 hardline-command-denylist.generated.ts 完全同性质（同一份 JSON 派生的拷贝），是本次“同类拷贝”清理中漏掉的另一半。
- [x] `apps/tabtin_django/apps/services/common/sandbox_policy.py` 第 174 行
  - 处所与内容属实，仅两处需修正：(1) L174-182 的列表实际含 7 项，原描述漏列了 "~/.tabtin/*"，完整为 ["~/.ssh/*", "~/.gitconfig", "~/.tabtin/*", "~/.aws/*", "~/.gnupg/*", "~/.kube/*", "~/.netrc"]；(2) L1216 的 SENSITIVE_DIRS 是 _check_glob_pattern 类方法内的局部变量而非模块常量，且其中的 ".docker"、".npmrc" 并未以该字面形式出现在 sensitive_path_list —— SSoT 中对应项是 ".docker/config.json" 与 ".npmrc"。另需注意：SSoT JSON 里并不存在 deny-write 类清单字段，故 _DEFAULT_SENSITIVE_DENY_WRITE_PATHS 无法靠改成 import 现成字段消除，需在 SSoT 中新增对应字段（如 always_protect_write_paths）才能收敛，属于比"改 import"略重的改造。
  - *为何在范围内*：凭据/敏感目录清单在 Python 侧至少三处（generated_hardline、本文件 deny_write、本文件 SENSITIVE_DIRS），SSoT 增删一条就漏一处，属本次去拷贝范围。
- [x] `apps/tabtin_django/apps/services/tools/domains/common/ssh_execute.py` 第 44 行
  - 描述基本准确，仅两点补充：(1) 重叠对象主要是 hardline v3 的 absolute_command_denylist（v1 hardline-rules.json 仅 'chmod 777 /' 一条对应），说成 'force_block / absolute_command_denylist' 略宽；(2) 该工具当前未在 common/tool_registry.py 注册、全仓无其他调用点，疑为未接线/遗留代码，处理策略应是「删除或改为读 SSoT」二选一，而非仅替换为跨文件导入。此外该文件在调用本地 9 条正则之后，还会再走 apps/services/common/sandbox_policy.py:is_high_risk_command() 做第二次判定，二者存在功能重叠。
  - *为何在范围内*：SSH 执行链路是另一条独立消费路径，规则直接写死在工具里；hardline SSoT 更新（如新增 shutdown 变种）不会传导到它，是“同类拷贝”遗漏点。
- [x] `apps/tabtin_django/apps/services/agent_engine/utils/shell_safety.py` 第 30 行
  - 描述属实，路径/行号/内容/用途均对得上，无需更正。补充一点精确性说明：它并非 SSoT 的逐字拷贝，而是有损压缩——漏掉了 SSoT 中的 /etc/gshadow、/etc/master.passwd、/etc/sudoers.d、/etc/security/ 以及 basename 侧的 id_ecdsa*/id_dsa*/*.crt/*.p12/*.p8 等条目；这种与 SSoT 的偏移本身正是去拷贝要消除的漂移风险。
  - *为何在范围内*：与 path_scan_rules 同内容的第三份 TS/Python 之外的拷贝；只报真正承载规则内容的这一处（同目录其余是消费方）。
- [x] `packages/terminal-core/src/localSandboxPolicy.ts` 第 22 行
  - 原描述方向正确，仅需精确化：SENSITIVE_FILE_PATTERNS（L22-30）不是整份 hardline 规则的拷贝，而是 7 条中 4 条（.env、.ssh/、.gnupg/、.aws/）与 tabtin-shared/src/hardline-v3-rules.json 的 sensitive_path_list（及 path_scan_rules 的 .ssh/、.gnupg/）手工平行维护；另外 3 条（shell 脚本后缀、dockerfile、docker-compose.*）在 SSoT 中不存在，属于本地独有策略。因此收敛动作应是「凭据路径子集改为从 SSoT 派生，保留本地独有的可执行/Docker 产物规则」，而非整表并入或整表删除。消费语义也不同：这里对 basename 与 full path 各跑一次正则（L141-146），而 sensitive_path_list 是 path-anchor、path_scan_rules 是 substring，合并时需保留本地匹配语义。
  - *为何在范围内*：terminal-core 内部还有一份绕过 SSoT 的敏感路径清单；本次收敛 sensitive-paths.generated.ts 时应一并评估并入。
- [x] `packages/terminal-core/src/localSandboxPolicy.ts` 第 33 行
  - AGENT_SPAWN_CATASTROPHIC_RULES(L33-40) 是一组写死的硬红线规则名字符串集合：rm -rf system root / fork bomb / dd to raw device / mkfs format / format disk windows / redirect to raw disk，用于从 HARDLINE_COMMAND_DENYLIST 里筛出灾难级规则。名字必须逐字匹配 SSoT，SSoT 改名/新增灾难级规则时这里静默失效。
  - *为何在范围内*：任务明确把“规则名写死在代码里”列为要扫的内容特征；这是 hardline SSoT 的规则名词表在消费端的硬编码副本，属于隐性拷贝。
- [x] `packages/security-policy/src/hardline-v3.ts` 第 38 行
  - 描述位置与内容准确，需补两点修正：(1) hardline-v3-rules.json 里根本没有 tier 字段，所以这里不是"同一份数据的复制粘贴"，而是"哪些命令规则属灾难级"这一分类只存在于 TS 代码中；正确修法是给 SSoT 的 absolute_command_denylist 条目增加 tier 字段再派生（顺带覆盖同文件 L485 checkOpaquePowerShellCommand 里另一处硬编码 tier: 'catastrophic'），单纯删除该 Set 会丢失语义并破坏 src/index.ts:121 的公开导出；(2) 漂移是单向的——改 JSON 的 name 会静默降级，而非两端互不一致。
  - *为何在范围内*：连 security-policy 自己内部也保留了规则名硬编码；JSON 改名后 tier 判定会静默退化为 risk，是本次重构该顺手消除的拷贝。
- [x] `apps/tabtin-electron/src/main/security/path-access-checker.ts` 第 99 行
  - 补充精确化（原描述无误）：DEFAULT_DENY_READ_PATTERNS 并非 SSoT 的直接派生拷贝，而是一条独立且更严格的 IPC 层"默认拒读"名单（连工作区内的读也拒，可通过 options.denyReadPatterns 扩展，拒绝 reasonCode 为 deny_list），语义上区别于 SSoT 的四态 checkSensitivePath；但内容确为同一批凭据路径，且已被手工镜像到 daemon 端 remote-fs-handlers.ts 的 REMOTE_DENY_READ_PREFIXES，属应纳入单一来源治理的同类冗余。
  - *为何在范围内*：Electron IPC 路径层绕开 SSoT 自维护一份敏感路径清单；SSoT 新增云 CLI 凭据路径时这里不会同步，是“同类拷贝”的另一处。
- [x] `apps/tabtin-daemon/src/application/execution/remote-fs-handlers.ts` 第 51 行
  - 描述基本准确，仅两处可精确化：(1) 这份清单镜像的是 Electron 端 path-access-checker.ts:99-111 的 DEFAULT_DENY_READ_PATTERNS（一份独立的、reasonCode 归为 'deny_list' 的可调默认禁读表），并非直接从 hardline SSoT 派生；与 SSoT 的 sensitive_path_list 是 10/11 重叠（.config/op 只存在于 Electron/Daemon 两端，不在 SSoT）。(2) 因此称其为「同一清单的第三份手工拷贝」略有出入：若以 SSoT 为唯一来源计，它是继「Electron 常量拷贝」之后的第二份手工拷贝；用「同一份敏感凭据路径数据被 Electron、Daemon（及 Python 侧）各自硬编码」表述更准确。文件位置、行号、内容与注释引述均与原文一致。
  - *为何在范围内*：同一份敏感路径数据被 Electron、Daemon、Python 各自硬编码；这正是本次“只剩一份来源”要收敛的对象。
- [x] `apps/tabtin-electron/src/renderer/src/services/resources/downloader.ts` 第 510 行
  - 位置与内容属实（downloads.ts 路径、L510-514 行号、12 条片段文字全部对得上），仅“copy（拷贝）”的定性需收紧：它不是由 SSoT 派生/生成的拷贝，而是渲染进程内独立手写的敏感路径黑名单，与 absolute_path_denylist、sensitive_path_list 仅部分重合——它额外含有 SSoT 中不存在的 /var/、/proc/、/sys/、/dev/、/.config/、/windows/system32、/windows/syswow64，同时缺少 SSoT 中 .aws、.kube、.npmrc、.netrc、.docker/config.json、Library/Keychains、浏览器 Cookie/Login Data 等条目，双向 drift。准确表述应为：`apps/tabtin-electron/src/renderer/src/services/resources/downloader.ts` L510-514（方法 isFilePathSafe，L503；调用点 contentRefToBlob L532-535）内联一份手写的敏感路径片段清单，与 hardline SSoT 的 absolute_path_denylist / sensitive_path_list 部分重合、互有缺失，是同一类硬编码敏感路径内容的第二个来源，SSoT 变更不会传导；但主进程 fs:readFilePreview（file-system/ipc.ts:1279 → checkAndFormat → path-access-checker.ts → checkHardlinePath/matchSensitivePath）才是权威闸门，此处仅为纵深防御预检，收敛时需一并决定额外 7 条片段的归属，而非直接换成导入。
  - *为何在范围内*：属于同一类“硬编码敏感路径内容”的拷贝点；虽然只覆盖子集，但 SSoT 变更时同样不会传导，列出供收敛时判定是否并入。
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 56 行
  - _DANGEROUS_TOPLEVEL_DIRS(frozenset，line 56-82) 与 _DANGEROUS_WINDOWS_ROOTS(line 85-88) 是 TS packages/security-policy/src/path-normalize.ts:DANGEROUS_TOPLEVEL_DIRS/DANGEROUS_WINDOWS_ROOTS 的手抄镜像（文件头第 7-10 行自述『手抄』）。
  - *为何在范围内*：与 hardline 规则同属『手工镜像』类别；虽不在 JSON SSoT 内，但重构既然要消灭跨端手工拷贝，这处至少应登记为已知残余并明确其归属（要么纳入 SSoT，要么显式豁免）。
- [x] `packages/terminal-core/src/sensitive-paths.generated.ts` 第 2 行
  - 文件头写着 AUTO-GENERATED by scripts/codegen-hardline.py（该脚本在仓库任何位置都不存在，已全仓验证），SSoT 指向旧路径 packages/security-policy/src/hardline-v3-rules.json:path_scan_rules（JSON 已迁至 tabtin-shared）。内容是与 hardline-v3-rules.json 的 path_scan_rules 同源的手工副本，被 terminal-core 构建内联进 dist。是本次『废掉手工拷贝』已知但未处理的目标。
  - *为何在范围内*：同一份 SSoT 派生出的第二份拷贝，且其生成器/旧路径引用都随重构失效，属核心去拷贝对象。
- [x] `packages/terminal-core/src/denylist.ts` 第 70 行 **[批评者翻案]**
  - CRITICAL_DENYLIST（L70-156，12 条）是 packages/security-policy/src/critical-rules.json（13 条）的手抄镜像，缺 curl-pipe-exec；且 TS 侧全仓无人 import 该 JSON。
  - *为何在范围内*：批评者翻案：原被误判为已完成项，实际该文件 L70 以下还躺着未处理的、自称 SSoT 的拷贝
- [x] `packages/security-policy/src/i18n-keys.json` 第 1 行 **[批评者翻案]**
  - hardlinePattern 分组 26 键 = 18 条 absolute_command_denylist + 8 条 absolute_path_denylist，同一 slug 名空间复制到 8 个 locale 的 chat.json，由 ApprovalPanel.tsx:423,429 消费，零测试锁定。
  - *为何在范围内*：批评者翻案：规则改名会让 9 个文件静默失配、UI 回落裸 slug
- [x] `apps/tabtin_django/apps/services/tools/domains/common/generated_critical_rules.py` 第 1 行 **[批评者翻案]**
  - 第三个 codegen 家族（前 5 个搜索角度因名字里没有 hardline 而全部漏掉）。
  - *为何在范围内*：批评者按文件名族扫描补捞到

### 规则消费点（12 条）

迁移目标：改为运行时读同一来源，而非各自的本地表。

- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 12 行
  - 描述基本准确，仅需修正一点：第 181 行并未指向旧 SSoT 路径，该行原文是「全路径规则：与 TS `SENSITIVE_PATH_RULES` 同源（如 `~/.ssh`、`/etc/shadow`）」——它引用的是 TS 侧符号名而非文件路径。文件里真正仍写着失效路径的行是 13、14、16、17、20、22、23、25 行（头部）与 109 行（即旧 SSoT `packages/security-policy/src/hardline-v3-rules.json`）；其中第 13 行引用的 `packages/terminal-core/src/sensitive-paths.generated.ts` 本身也仍是待废掉的拷贝产物。行号区间亦需微调：导入块实为第 43-46 行，dataclass 包装实为第 113-116 行。
  - *为何在范围内*：它是两个拷贝产物（generated_hardline.py 与 sensitive-paths.generated.ts）的汇合消费点，也是“双拷贝同源”契约的文档载体。Stage B 把 Python 改为直读 SSoT 后，这里的导入与整段 codegen 流程说明都必须重写。
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 56 行
  - 描述准确，仅补充两点：(1) 旧路径引用具体在 L13-14（指向 packages/security-policy/src/hardline-v3-rules.json）与 L20-22/L25（codegen 流程说明，引用同一旧路径及不存在的 scripts/codegen-hardline.py），改导入源时这两处注释需一并更新；(2) L50 的注释同样写着『与 TS 端 path-normalize.ts:DANGEROUS_TOPLEVEL_DIRS 同源』，与 L7-10 重复，可在清理时合并。
  - *为何在范围内*：它是上一轮列出的“路径规则的另一处消费点”——只要 Python 侧改读 SSoT，这里的导入源必须同步切换；(2) 是跨包手工镜像，同属单一来源目标的清理面。
- [x] `apps/tabtin_django/apps/services/common/tests/test_path_safety.py` 第 302 行
  - TestCodegenIntegrity.test_generated_outputs_in_sync_with_json_ssot 会 `subprocess.run([sys.executable, repo_root/'scripts'/'codegen-hardline.py', '--check'])`，并在第 303 行断言 `codegen_script.exists()`。已验证该脚本不存在 → 该测试必然失败。
  - *为何在范围内*：直接消费不存在的生成器，是本次重构必须一并处理的活跃测试
- [x] `packages/terminal-core/src/allowlist.ts` 第 24 行
  - SENSITIVE_PATH_RULES = GENERATED_SENSITIVE_PATH_RULES（import 自 ./sensitive-paths.generated，line 3-5）；matchSensitivePath（line 59-67）遍历该表。它当前拿到的是拷贝，不是 SSoT。
  - *为何在范围内*：这是拷贝的消费点；改造该拷贝必须同步改这里，改为从 SSoT JSON 的 path_scan_rules 直接构建（并 fail-closed，照 denylist.ts 的范式）。
- [x] `apps/tabtin_django/apps/services/common/approval_rules_service.py` 第 94 行
  - from .generated_hardline import HardlineVerdict, check_safety_hardline；在 line 357 调用 check_safety_hardline(action_type, tool_input)。它消费的是 generated_hardline.py 里的手工拷贝。
  - *为何在范围内*：Stage B 改造 generated_hardline 时，必须确认此调用点的函数签名/返回语义（HardlineVerdict、block/confirm、source=hardline_block）不变，否则审批链路静默失效。
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 43 行
  - 描述基本准确，仅补两处精确化：(1) 该 import 语句为多行，起于第 43 行、止于第 46 行（第 43 行是 `from ... import (`），第 44/45 行才是两个符号名；(2) matches_sensitive_path 实际有两条消费路径——第 199 行消费 SENSITIVE_BASENAME_PATTERNS（basename fullmatch），第 201 行消费包装后的 SENSITIVE_PATH_RULES（`rule.pattern.search`），描述只提了 line 201。此外第 12-25 行的模块 docstring 仍引用旧路径 packages/security-policy/src/hardline-v3-rules.json 与不存在的 scripts/codegen-hardline.py，同属本消费点待清理的陈旧引用。
  - *为何在范围内*：Python 路径规则的另一处消费点（任务清单已点名），Stage B 必须让它从 SSoT path_scan_rules/path_basename_patterns 派生，而非从 generated_hardline 拷贝。
- [x] `apps/tabtin_django/apps/services/common/sandbox_policy.py` 第 484 行
  - 描述大体准确，但需修正调用形态：484 行的 import 位于方法 _matches_sensitive_path（定义于 474 行）体内，导入符号 matches_sensitive_path 仅被 485 行**直接**调用；872、881、1149 行调用的是方法 self._matches_sensitive_path(...)，属该导入的间接使用，而非直接使用导入符号。另补两点：该模块不含规则副本，是纯消费点；其规则的真正来源是 apps/services/common/generated_hardline.py（经 path_safety.py 的 SENSITIVE_PATH_RULES / SENSITIVE_BASENAME_PATTERNS 转发），而 is_dangerously_broad_root 使用的 _DANGEROUS_TOPLEVEL_DIRS / _DANGEROUS_WINDOWS_ROOTS 是与 packages/security-policy/src/path-normalize.ts 手抄对齐的字面量，无 generated 来源。
  - *为何在范围内*：这是 Python 侧安全判定的实际运行消费点，Stage B 改规则来源后必须以这里的路径短路行为做端到端验证（fail-closed 不能退化）。
- [x] `apps/tabtin_django/apps/services/agent_engine/permissions/rule_engine.py` 第 113 行
  - 局部 from apps.services.common.authorization_policy import check_safety_hardline；line 114 调用。与 approval_rules_service.py 消费的 generated_hardline.check_safety_hardline 同名不同源。
  - *为何在范围内*：存在两个同名 check_safety_hardline 实现（authorization_policy vs generated_hardline）被不同调用方消费——这是拷贝漂移的真实证据，Stage B 必须合并为单一来源，否则两端被判为『同义』的规则可能已不一致。
- [x] `apps/tabtin-electron/src/main/security/path-access-checker.ts` 第 76 行
  - 发现描述准确，无需更正位置与行号。仅需澄清处理落点：本文件（apps/tabtin-electron/src/main/security/path-access-checker.ts）本身无需改动代码，它只是两条红线并存的可观测点；真正待处理的是 packages/terminal-core/src/allowlist.ts + packages/terminal-core/src/sensitive-paths.generated.ts —— 让 matchSensitivePath 也从 @tabtin/shared 的 hardline-v3-rules.json 运行时派生（照 denylist.ts 的做法），同时 updated 其头部仍指向 packages/security-policy/src/hardline-v3-rules.json 的过期 SSoT 注释。改完后本处 matchSensitivePath 与 checkSensitivePath 才真正同源。
  - *为何在范围内*：最能体现改造成效的消费方：改造后 matchSensitivePath 与 checkSensitivePath 才真正同源；否则同一路径文件的两条红线仍来自两份数据。
- [x] `packages/terminal-core/tests/w7-b2-codegen-cross-end.test.ts` 第 15 行
  - 行号微调：第 19 行是 it() 描述语句，'length >= 33' 的实际断言在第 21 行；文件头过期引用范围是第 8-10 行（非 8-9 行），且不止指旧路径，还指 git 全历史中不存在的 scripts/codegen-hardline.py。措辞修正：该测试经由 allowlist 的公共导出（而非直接 import 生成物）取数，因此废除 sensitive-paths.generated.ts 时第 15 行导入不一定需要改动；真正必须同步的是第 21/25/30/35 行的规则计数与 label 断言，以及第 8-10 行注释。
  - *为何在范围内*：既有测试直接钉住拷贝的形态（源自 allowlist 而非 SSoT）；改造 sensitive-paths.generated 时必须同步改这个测试的取数路径与断言，否则改完即红。
- [x] `apps/tabtin_django/apps/services/common/tests/test_path_safety.py` 第 245 行
  - line 250-285 通过 matches_sensitive_path 断言 *.crt/*.kdbx/id_dsa 等 basename 与 substring 行为；line 292 注释明确『任何 PR 改了 hardline-v3-rules.json 但没跑 codegen 的，都会被这条捕获』。
  - *为何在范围内*：Python 路径规则的跨端一致性测试；Stage B 后它应从 SSoT 而非拷贝派生，注释里对『跑 codegen』的假设也需更新。
- [x] `packages/terminal-core/src/allowlist.ts` 第 5 行
  - 无需大改，仅精确化：该相对导入是跨 2-5 行的多行语句，`'./sensitive-paths.generated'` 模块说明符位于第 5 行（非单行语句）；注释块为第 7-21 行，其中第 13-20 行描述旧 SSoT/代码生成流程。另补一点强化：注释里的旧 SSoT 路径 `packages/security-policy/src/hardline-v3-rules.json` 现已不存在（JSON 已迁至 packages/tabtin-shared/src/），所以这里不只是"流程过期"，而是同时包含一条死路径引用。修复方向与已完成项一致：删除 sensitive-paths.generated.ts，让 allowlist.ts 从 `@tabtin/shared/hardline-v3-rules.json` 的 path_scan_rules 直接构建（参照同包 denylist.ts 的 fail-closed 写法），并同步修掉注释。
  - *为何在范围内*：构建期消费拷贝的具体位置，是去拷贝改造要替换成读取 tabtin-shared SSoT 的落点。

### 过期引用（32 条）

注释与文档仍指向已迁走的旧路径，或仍声称要跑不存在的 codegen 脚本。

- [x] `packages/terminal-core/src/sensitive-paths.generated.ts` 第 2 行
  - 描述位置与内容准确。仅行号可再精确一点：allowlist.ts 中「由 scripts/codegen-hardline.py 输出」在第 15 行，可执行的「跑 python scripts/codegen-hardline.py」步骤落在第 19-20 行（整段注释块为第 13-21 行），而非笼统的「15-19 行」。另外可补充两点便于定位：sensitive-paths.generated.ts 中旧 SSoT 引用在第 5 行、生成器引用在第 2-3 行；同一批失效引用还出现在 tests/w7-b2-codegen-cross-end.test.ts:9 与 packages/tabtin-shared/src/hardline-v3-rules.json:2 的 $comment（后者仍要求「跑 python scripts/codegen-hardline.py 重新生成所有 codegen 产物」）。
  - *为何在范围内*：重构后这些产出物的“来源声明”全部失效：读者按注释去跑生成器会失败、按旧路径找 JSON 会找不到。属于本次搬迁必须一并订正的产物内嵌引用。
- [x] `packages/tabtin-shared/src/hardline-v3-rules.json` 第 2 行
  - $comment 写 "修改后必须跑 `python scripts/codegen-hardline.py` 重新生成所有 codegen 产物，否则 CI `--check` 失败 + scripts/infra-gate.sh 阻断"；同时列出已被删除的 `terminal-core/hardline-command-denylist.generated.ts` 为消费方。已验证 `scripts/codegen-hardline.py` 与 `scripts/infra-gate.sh` 在仓库中均不存在，且无 .github/workflows。
  - *为何在范围内*：指向不存在的生成器与不存在的 CI 门禁；这两个文件是本次重构的 SSoT，其头部说明必须同步改写为「手工/运行时读取」
- [x] `packages/tabtin-shared/src/hardline-v3-rules.json` 第 3 行
  - $comment_decision_tree 的 Q3 写 "改完跑 `python scripts/codegen-hardline.py` 重生成两个 codegen 产物（Python generated_hardline.py + TS sensitive-paths.generated.ts）；CI 用 `python scripts/codegen-hardline.py --check` 校验一致性（已接入 scripts/infra-gate.sh）"。
  - *为何在范围内*：声称有 codegen 同步与 CI 校验，实际生成器/门禁都缺失；这是引导后续维护者走错误流程的活跃文档
- [x] `packages/tabtin-shared/src/hardline-rules.json` 第 2 行
  - $comment 写 "修改后必须跑 scripts/codegen-hardline.py 重新生成 Python 镜像，否则 CI check 失败"。
  - *为何在范围内*：v1 SSoT 的头部仍指向不存在的生成器与假想的 CI check
- [x] `packages/terminal-core/src/sensitive-paths.generated.ts` 第 5 行
  - "SSoT: packages/security-policy/src/hardline-v3-rules.json:path_scan_rules"。
  - *为何在范围内*：指向已迁移的旧路径，真实位置为 packages/tabtin-shared/src/hardline-v3-rules.json
- [x] `packages/terminal-core/src/allowlist.ts` 第 15 行
  - 表述基本准确，可补充更精确的表述：allowlist.ts 第 13-20 行注释块（第 15 行为被引用的生成器说明）同时存在三处过期/失实：(1) 指向的生成器 scripts/codegen-hardline.py 全仓库不存在；(2) 声称的 SSoT 路径仍是旧的 packages/security-policy/src/hardline-v3-rules.json，实际已迁至 packages/tabtin-shared/src/hardline-v3-rules.json；(3) 声称"不再手抄、从 sensitive-paths.generated.ts 派生"，而该 generated 文件本身正是本次重构列为待废的 path_scan_rules 同类拷贝，仍未被移除。因此该注释既指向不存在的生成器，也指向已废弃的 SSoT 路径，且其描述的同源关系与当前状态不符。
  - *为何在范围内*：指向不存在的生成器；allowlist 现在消费的是手抄/生成物拷贝，注释描述与事实不符
- [x] `packages/terminal-core/src/allowlist.ts` 第 17 行
  - 原描述无误，仅补充精度：除第 17 行的 SSoT 旧路径外，同一注释块第 13-20 行整体已过期——第 15 行引用的脚本 `scripts/codegen-hardline.py` 在仓库 scripts/ 中不存在，第 5 行仍 import 待废弃的 `./sensitive-paths.generated.ts` 拷贝；该注释块应按迁址后的事实（SSoT = packages/tabtin-shared/src/hardline-v3-rules.json:path_scan_rules，且生成物将被废除）整体重写。
  - *为何在范围内*：旧路径已迁移到 tabtin-shared，注释指向已不存在的 security-policy/src 副本
- [x] `packages/terminal-core/src/allowlist.ts` 第 20 行
  - 描述基本准确，仅行号略偏：该「修改流程」句跨第19-20行（第19行起「修改流程：改 hardline-v3-rules.json 的 path_scan_rules 字段 → 跑」，第20行止「python scripts/codegen-hardline.py → 两端产物自动同步」）。同一注释块还包含另外两处须一并修正的过期内容：第15行指向待废拷贝 ./sensitive-paths.generated.ts；第17行 SSoT 路径仍写 packages/security-policy/src/hardline-v3-rules.json，实际已迁至 packages/tabtin-shared/src/hardline-v3-rules.json。修正方向应为「直接读 tabtin-shared 中的 JSON SSoT，无 codegen 脚本」。
  - *为何在范围内*：描述了不存在的 codegen 同步流程，本次重构后应改为「直接读 SSoT」
- [x] `packages/terminal-core/tests/w7-b2-codegen-cross-end.test.ts` 第 8 行
  - 准确表述：文件头注释（第 8-10 行，非仅第 8 行）声明两端共享 SSoT 为 `packages/security-policy/src/hardline-v3-rules.json` 的 `path_scan_rules`，并称由 `scripts/codegen-hardline.py` 生成 `terminal-core/sensitive-paths.generated.ts` 与 Python `generated_hardline.py`。该 JSON 已迁至 `packages/tabtin-shared/src/hardline-v3-rules.json`（旧目录下不存在该文件），且 `scripts/codegen-hardline.py` 在仓库中不存在，故两处路径/生成器引用均为过期引用，需更新。
  - *为何在范围内*：测试文件头部注释指向旧路径
- [x] `packages/terminal-core/tests/w7-b2-codegen-cross-end.test.ts` 第 9 行
  - 描述基本准确，仅需细化行号：非单纯第 9 行，而是第 8-10 行整段头注释；其中第 8 行是老 SSoT 路径 `packages/security-policy/src/hardline-v3-rules.json`（本次已迁至 packages/tabtin-shared/src/），第 9-10 行是 `scripts/codegen-hardline.py` 输出 `terminal-core/sensitive-paths.generated.ts` + Python `generated_hardline.py` 的叙事。第 56、95 行确如所述。另：同一"不存在 codegen"叙述还出现在 packages/terminal-core/src/allowlist.ts 第 15、20 行与 packages/terminal-core/src/sensitive-paths.generated.ts 第 2-3 行，属同一处陈旧引用簇。
  - *为何在范围内*：整个测试文件的叙事建立在不存在的 codegen 之上
- [x] `packages/terminal-core/src/deny-rule-hints.ts` 第 18 行
  - 注释 "HARDLINE_COMMAND_DENYLIST（codegen 自 hardline-v3-rules.json）"；第 12 行 Coverage 行同样写 "HARDLINE_COMMAND_DENYLIST (codegen)"。
  - *为何在范围内*：本次重构已删除 codegen，denylist.ts 改为直接读 SSoT，此处 codegen 表述已不成立
- [x] `packages/terminal-core/src/denylist.ts` 第 68 行
  - 原描述基本准确，补充两点精确化：① 第 68 行的「codegen」只是来源归属失效，其功能断言（curl|sh 由 HARDLINE_COMMAND_DENYLIST 拦截）仍然成立，准确表述应为「HARDLINE_COMMAND_DENYLIST 现直接取自 @tabtin/shared 的 SSoT」，而非「codegen」；② 同类过期注释不止第 68 行——同一文件第 160 行（「…见 HARDLINE_COMMAND_DENYLIST（codegen）」）、第 210 行（「curl|sh 由 HARDLINE_COMMAND_DENYLIST codegen」），以及 packages/terminal-core/src/deny-rule-hints.ts 第 12、18 行的「(codegen)」「codegen 自 hardline-v3-rules.json」均属同一类待清理项。
  - *为何在范围内*：同一文件第 6 行已声明「不再有 codegen 生成物拷贝」，第 68 行自相矛盾地仍称 codegen
- [x] `packages/terminal-core/src/denylist.ts` 第 160 行
  - 原描述准确，仅需补充：同一处「codegen」过期表述在 denylist.ts 还有另外两处同类出现——第 68 行「与 hardline 重叠的 curl|sh 已由 HARDLINE_COMMAND_DENYLIST codegen（SSoT = absolute_command_denylist:"curl pipe to shell"）」和第 210 行「Note: pipe-to-shell 在 CRITICAL_DENYLIST；curl|sh 由 HARDLINE_COMMAND_DENYLIST codegen」。更准确的表述是：terminal-core/src/denylist.ts 中存在 3 处（第 68、160、210 行）将 HARDLINE_COMMAND_DENYLIST 描述为 codegen 生成物的过期注释，而该常量现已由第 2 行导入的 @tabtin/shared/hardline-v3-rules.json 在运行时直接构造（第 19-37 行），codegen 生成物已被删除；建议三处一并改为「运行时读自 SSoT @tabtin/shared/src/hardline-v3-rules.json」。
  - *为何在范围内*：codegen 已废除，HARDLINE_COMMAND_DENYLIST 现为运行时读 SSoT
- [x] `packages/terminal-core/src/denylist.ts` 第 210 行
  - 发现的位置与内容均准确，无需修正。可精确化为：packages/terminal-core/src/denylist.ts:210 的注释 `// Note: pipe-to-shell 在 CRITICAL_DENYLIST；curl|sh 由 HARDLINE_COMMAND_DENYLIST codegen` 中 `codegen` 已过期——本模块现已直接从 `@tabtin/shared/hardline-v3-rules.json` 的 `absolute_command_denylist` 构建，不存在 codegen 步骤；应改为类似「curl|sh 由 HARDLINE_COMMAND_DENYLIST（直读 SSoT）」。同类过期表述另见同文件第 68 行与第 160 行。
  - *为何在范围内*：同上，残留的 codegen 表述
- [x] `apps/tabtin_django/apps/services/common/authorization_policy.py` 第 53 行
  - 注释 "与 packages/security-policy/src/hardline-rules.json 的 "rm -rf /" 保持同义。"。
  - *为何在范围内*：旧路径已迁移到 packages/tabtin-shared/src/hardline-rules.json；此处也正是手工镜像 v1 规则的消费点
- [x] `apps/tabtin_django/apps/services/common/approval_rules_service.py` 第 6 行
  - 描述基本准确，仅需精确化：行号 6 上的确切文本是「 ``packages/security-policy/src/hardline-rules.json`` codegen）」，而描述引用的整句「平台硬底线（``generated_hardline.check_safety_hardline``，从 …」其实跨第 5-6 两行。失效点有二：旧路径 packages/security-policy/src/hardline-rules.json（应为 packages/tabtin-shared/src/hardline-rules.json），以及已不存在的 codegen 生成器表述。此为模块 docstring 注释，非代码逻辑。
  - *为何在范围内*：同时含旧路径与 codegen 表述，两者均已失效
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 14 行
  - 描述准确，仅补充：第 14 行只写了 SSoT 路径，其后的 12-25 行整段（含 13 行引用 terminal-core/src/sensitive-paths.generated.ts、16 行引用 scripts/codegen-hardline.py、19-25 行的四步 codegen 流程与 --check CI 说明）同样过期——该 codegen 生成器与流程概念上已随本次重构作废，因此应整段改写为「SSoT = packages/tabtin-shared/src/hardline-v3-rules.json 的 path_scan_rules + path_basename_patterns；Python 侧应改为运行时直读该 JSON（照 capability_contract.py 的 get_repo_root()+导入期 fail-fast 模式），不再经 codegen」，而不是只替换一处路径字符串。
  - *为何在范围内*：旧路径 + codegen 表述，且这是 Python 侧路径规则的关键消费点说明
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 16 行
  - 描述定位准确，但范围偏窄，建议修正为：apps/tabtin_django/apps/services/common/path_safety.py 的模块 docstring（第 5-25 行，核心在第 14-25 行）整段描述的同步机制已失效——(a) 第 16、22、25 行引用不存在的生成器 `scripts/codegen-hardline.py`；(b) 第 14 行（及第 20 行）仍写旧 SSoT 路径 `packages/security-policy/src/hardline-v3-rules.json`，实际已迁至 `packages/tabtin-shared/src/hardline-v3-rules.json`；(c) 第 13-17 行仍把 TS 端产物指向 `packages/terminal-core/src/sensitive-paths.generated.ts` 这一应被废除的拷贝。同一失效引用还扩散到：generated_hardline.py:2、terminal-core/src/sensitive-paths.generated.ts:2-3、terminal-core/src/allowlist.ts:15,20、tests/w7-b2-codegen-cross-end.test.ts:9、apps/tabtin_django/apps/services/common/tests/test_generated_hardline.py:12、test_path_safety.py:289-317（其中 301-303 会因脚本缺失直接断言失败）。
  - *为何在范围内*：指向不存在的生成器
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 20 行
  - 描述方向正确，但范围偏窄，建议修正为：该文件文档字符串中旧路径出现在 3 处——第 14 行（"SSoT 是 `packages/security-policy/src/hardline-v3-rules.json`"）、第 20 行（codegen 流程第 1 步）、第 109 行（注释 "packages/security-policy/src/hardline-v3-rules.json:path_scan_rules"）；且不止路径过期：整个「codegen 流程（修改一端 → 两端跟）」段落（第 13–25 行）都已失效，因为它引用的 `scripts/codegen-hardline.py` 在仓库中不存在（已确认），并声称同时生成 Python generated_hardline.py 与 TS terminal-core/sensitive-paths.generated.ts。准确表述应为：新旧 SSoT 应为 `packages/tabtin-shared/src/hardline-v3-rules.json`，codegen 段落需随 Python 侧改造（照搬 capability_contract.py 的 get_repo_root() + 导入期 fail-fast 模式，运行时读 SSoT）一并重写或删除。另注：本文件第 43–46 行仍 import generated_hardline.py 的 SENSITIVE_BASENAME_PATTERNS/SENSITIVE_PATH_RULES，即 Python 硬编码拷贝的运行时消费点，与本 stale-ref 属同一次 Python 侧改造范围。
  - *为何在范围内*：旧路径
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 22 行
  - codegen 流程第 2 步 "跑 `python scripts/codegen-hardline.py`"。
  - *为何在范围内*：生成器不存在
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 25 行
  - codegen 流程第 4 步 "CI mode：`python scripts/codegen-hardline.py --check` 验证一致性"。
  - *为何在范围内*：生成器与 CI 校验均不存在
- [x] `apps/tabtin_django/apps/services/common/path_safety.py` 第 109 行
  - 原描述准确，无需修正。可补充：完整旧路径字符串位于第 109 行（第 108 行 "（SSoT =" 为折行），同一文件第 14、20 行的 docstring 也各含一处相同旧路径，应一并改为 packages/tabtin-shared/src/hardline-v3-rules.json。
  - *为何在范围内*：旧路径
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 2 行
  - 原描述准确，无需更正。补充精确细节：行号 2 原文为 `AUTO-GENERATED by scripts/codegen-hardline.py`；第 3-8 行为「生成器不在仓库中 + 需手工同步三端」的括注。同一文件头的过期引用比描述所述更多：第 5、11、12 行仍写 SSoT 旧路径 `packages/security-policy/src/hardline-rules.json` / `hardline-v3-rules.json`（实际已迁至 `packages/tabtin-shared/src/`），第 6 行仍指向已被本次重构删除的 `packages/terminal-core/src/hardline-command-denylist.generated.ts`。
  - *为何在范围内*：该文件是本次要废除的 Python 侧硬编码拷贝，头部仍以 codegen 产物自居
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 5 行
  - 描述属实，无需修正。可补充两点使定位更完整：同一旧路径还出现在该文件第 11、12 行（不在仅第 5 行）；第 6 行引用的 packages/terminal-core/src/hardline-command-denylist.generated.ts 已被本次重构删除，该行同属失效引用。正确路径应为 packages/tabtin-shared/src/hardline-rules.json 与 packages/tabtin-shared/src/hardline-v3-rules.json（构建后可经 ./hardline-rules.json、./hardline-v3-rules.json 导出子路径访问）。
  - *为何在范围内*：旧路径
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 6 行
  - "TS packages/terminal-core/src/hardline-command-denylist.generated.ts"。
  - *为何在范围内*：该 TS 生成物已被本次重构删除，手工同步说明中的三端之一已不存在
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 11 行
  - "- packages/security-policy/src/hardline-rules.json (v1 兼容)"。
  - *为何在范围内*：旧路径；第 12 行同款 v3 路径同样过期
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 12 行
  - "- packages/security-policy/src/hardline-v3-rules.json (v3)"。
  - *为何在范围内*：旧路径已迁移到 tabtin-shared
- [x] `apps/tabtin_django/apps/services/common/generated_hardline.py` 第 175 行
  - "# 与 TS terminal-core/sensitive-paths.generated.ts:SENSITIVE_PATH_RULES 同源。"（该 TS 文件是待废拷贝，仍被当作同源锚点引用）。
  - *为何在范围内*：同源目标本身是要删除的拷贝，此注释固化了两份拷贝并存的事实
- [x] `apps/tabtin_django/apps/services/common/tests/test_path_safety.py` 第 316 行
  - 描述基本准确，仅两处需精确化：(1) 该 hint 字符串位于 312-318 行的多行断言消息内，第 316 行只是其中一段；"289/292/315 行同款 codegen 表述"中，第 292 行实际只提 hardline-v3-rules.json 与 generated 产物，并非 codegen 脚本引用，真正的脚本引用在第 289、302、306、315 行。(2) 更关键的是第 302-303 行存在硬断言 assert codegen_script.exists()，缺失的 scripts/codegen-hardline.py 会直接导致 TestCodegenIntegrity 失败，问题不止于失败提示文案过期。准确表述应为：test_path_safety.py 的 TestCodegenIntegrity 类仍依赖不存在的生成器 scripts/codegen-hardline.py（硬断言其存在），并在失败提示中要求重生成已删除的 hardline-command-denylist.generated.ts 与另一处派生产物 sensitive-paths.generated.ts，属待清理的 codegen 残留。
  - *为何在范围内*：引用不存在的生成器与被删除的 hardline-command-denylist.generated.ts
- [x] `apps/tabtin_django/apps/services/common/tests/test_generated_hardline.py` 第 12 行
  - 原描述大体成立，但「另第 4、6、10 行以 generated_hardline.py 为 codegen 产物叙事」一处不准确：第 6 行指向的是 TS 测试路径 packages/security-policy/tests/hardline.test.ts，并非 generated_hardline.py。准确表述应为：第 12 行 docstring 指导执行不存在的生成器 ``python scripts/codegen-hardline.py``（第 11-13 行同属该「改 SSoT → 重新生成 → 同步两端用例」流程）；第 4 行把 generated_hardline.py 当作 PRD 05 §6.2 Layer 1 的实现产物叙述、第 10 行指向 hardline-rules.json，二者属同一「codegen 产物 + 旧 SSoT 路径」叙事；第 6 行另含已迁走的旧路径 packages/security-policy/tests/hardline.test.ts。核心缺陷（教学读者运行一个仓库中不存在的生成器）属实。
  - *为何在范围内*：测试头部仍指导跑不存在的生成器
- [x] `apps/tabtin_django/apps/services/common/tests/test_generated_hardline.py` 第 53 行
  - 描述基本准确，稍作修正：hardline.ts 并非「已不存在的 v1 TS 文件」——git 全历史（git log --all --name-only）中从未出现过该文件名，只有 hardline-v3.ts 与 hardline-v3.test.ts，因此该注释引用的文件名从来就是错的，而非本次删除所致。另：同一文件 docstring 还有两处同类悬空引用——第 6 行 `packages/security-policy/tests/hardline.test.ts`（不存在）、第 12 行 `python scripts/codegen-hardline.py`（不存在），第 11 行 `hardline-rules.json` 则仍存在（已迁至 packages/tabtin-shared/src/）。第 53 行 `hardline-rules.json` 部分同样仍有效，仅 `hardline.ts` 需订正。
  - *为何在范围内*：引用已不存在的 v1 TS 文件，属同类过期引用
- [x] `apps/tabtin-daemon/tsup.config.ts` 第 15 行
  - 原文「26 行注释块」的计数不准：该注释块为第 15-25 行（11 行），含 copyHardlineRules 的整段为第 15-36 行。准确表述应为：apps/tabtin-daemon/tsup.config.ts 第 15-22 行的注释仍按旧机制断言 hardline 规则在运行时以 createRequire(import.meta.url) 相对加载 './hardline-v3-rules.json'，并据此论证 daemon 必须补拷该文件；实际 hardline-v3.ts:16 已改为静态裸导入 '@tabtin/shared/hardline-v3-rules.json'，源码中不存在该相对加载调用，且该包在 noExternal 列表内会被 esbuild 以内联 JSON 打包，因此第 26-36 行 copyHardlineRules（挂于第 102/119 行 onSuccess）及其注释理由均已失效；注释第 23 行虽已更新指向 @tabtin/shared，但未同步修正 15-22 行的机制描述，会误导维护者保留该拷贝步骤。修正未改变 real/outstanding 判定。
  - *为何在范围内*：注释是这次重构直接影响的产物（旧路径/旧机制），且它正是 daemon 拷贝步骤存在的『理由』，理由已失效。

## 验收条件

1. **8 个 SSoT 字段**（`absolute_command_denylist` / `absolute_path_denylist` / `sensitive_path_list` / `path_scan_rules` / `path_basename_patterns` / `force_block` / `force_confirm` / `sensitive_fields`）每个都有且仅有一份可编辑定义。
2. **全部消费点**改为读同一来源：TS 3 处 + Python 5 处 + electron/daemon 2 处。
3. **改一条规则 → 只改一处** → 两端行为同步变化，无生成物需重跑。
4. **负向验证**：故意删掉/改坏 JSON → 两端都拒绝启动或拒绝命令，且报错可读（fail-closed 的证据，必须有）。
5. **打包产物端到端**：daemon / electron main 启动不报 `Cannot find module`。

## 测试守卫缺口

- 8 个 SSoT 字段里**只有 1 个**（`absolute_command_denylist`）有逐条 element-wise 断言。
- `test_pattern_counts_match_ssot` 用 `>= 9` 下界断言，是**假测试**（应按等值断言）。
- i18n 的 26 个 `hardlinePattern` 键 × 8 个 locale **零测试锁定**：规则改名会让 9 个文件静默失配、UI 回落裸 slug。
- `packages/terminal-core/tests/hardline-command-codegen.test.ts` 中逐条比对 pattern.source 与 flags 的那段，是全仓**唯一**的 element-wise 跨端守卫，应作为范本推广到其余 7 个字段。

## 方法与已知局限

- **搜索盲区**：最初的 5 个角度全部以 `hardline` 这个名字为起点，凡同类但名字里不含 hardline 的一律漏网。
  批评者按「SSoT 字段名」「文件名族」「SSoT 独有字面量」「逐条正则等价比对」等 12 种模态补搜，
  才捞到第三个 codegen 家族 `generated_critical_rules.py` 等。后续复查请换角度，别重复按名字搜。
- **核实环节否决了 25 条**，但批评者指出其中 3 条否决理由不成立，已翻案补入（带 **[批评者翻案]** 标记）；
  另有 1 条裁决矛盾（electron 拷贝步骤是否已成为死代码）应在动手时现场确认。
- **未验证**：daemon / electron 的**构建未实际跑过**（只验证了路径解析）；
  Python 侧尚未改造，其行为未在本轮重新实测。
- **本清单不含**与本迁移无关的改动：工作区里 `.env.example` 与 `scripts/tests/test_community_unix_launchers.py`
  属另一条线（社区版固定验证码加固），不要混入本次提交。
