# 「技能 ↔ 数字员工绑定」界面接口契约（第 9 轮）

> 状态：**v2 · 2026-09-20 · 契约已确认（用户 2026-09-20 四项裁决）并已交付**。
> **唯一权威在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)（§3「技能」两行 + **§13 第 9 轮补登记**）；
> 同域第 8 轮契约 = [`skills-mcp-api.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/skills-mcp-api.md)（技能包状态机 / 可见性收敛 / §7 已修缺陷）；
> 后端契约真源 = `docs/api-contract.md`（**已同步更正**，见其「技能（P4 技能层）」节）。
> 本文件只声明**绑定面所需的最小接口集**。
>
> **证据级别**：v1 落盘时为**源码判定**；**2026-09-20 已完成真机复测 6 项 + 交付**（工作树后端 + 真库
> `wiring-evidence`，超管 `13600000001` / 员工 `13600000002`，仅本机非生产）—— 复测结果回写 §1 / §2 / §6 / §7。

## 1. 接口清单与角色门禁

| 方法 | 路径 | 用途 | 角色门禁（**2026-09-20 实测**） |
| --- | --- | --- | --- |
| **GET** | `/api/v1/skills/bindings` | **🆕 本轮新增（已实现）**：绑定关系列表（`agent_key` / `skill_key` 可选过滤、`limit` 1–200 默认 50、`offset` ≥0；**必须分页**） | **仅 `super_admin`**（`ensure_can_bind`；实测四个非管理角色一律 `403`）；匿名 `401`；`limit=201` ⇒ `422` |
| POST | `/api/v1/skills/bindings` | 绑定（`{skill_key, agent_key}`，`extra="forbid"`；**UPSERT `active` 幂等**） | 仅 `super_admin`（`BIND_ROLES`） |
| DELETE | `/api/v1/skills/bindings?skill_key=&agent_key=` | 解绑（`active → disabled`；**已 `disabled` 幂等**） | 仅 `super_admin` |
| GET | `/api/v1/skills/agents/{agent_key}/tools` | 该员工工具面 = 已启用技能 `allowed-tools` 并集 ∩ 执行目录（**服务端解析，fail-closed**） | **2026-09-20 起**：四个业务角色可读；**`customer_admin` ⇒ `403`**（本轮修，见 §7；此前只看登录 ⇒ 四角色全放行） |

**为什么必须新增读端点**：`SkillStore.list_bindings` / `SkillService.list_bindings` **服务层与仓储层均已实现**，
但 **HTTP 面只有 `POST` / `DELETE`**（`app/main.py` 全文仅两处 `skills/bindings`）⇒ 没有读端点，
界面无法列出"该技能绑了哪些员工 / 该员工绑了哪些技能"。故本轮新增 `GET`，**只做暴露、不改业务逻辑**。

**响应形状（源码逐字 + 实测复核）**
- 绑定视图（🆕，**已实测**）：`{ skill_key, agent_key, status, created_by, created_at }`
  —— 字段取自 `SkillBinding` dataclass（`app/skills/models.py`），**刻意不含 `tenant_id`**（实测条目键恰为这五个）。
- 列表信封（🆕，与既有 `SkillListResponse` 同形）：`{ items: SkillBindingView[], total, limit, offset }`（实测键一致）
- 绑定 / 解绑（既有）：`{ skill_key, agent_key, status }`（`active` / `disabled`）

**错误映射（与既有技能端点同口径，`_raise_skill_http`；**均已实测**）**：`401` 未认证（匿名 ⇒ `{"detail":"缺少登录身份信息"}`）；
`403` 越权（非 `super_admin` ⇒ `{"detail":"只有超级管理员可以绑定或解绑技能"}`）；
`404` 指定 `agent_key` / `skill_key` 的绑定不存在（解绑时 ⇒ `{"detail":"binding <agent>/<skill>"}`）；
`422` 参数越界（`limit=201` ⇒ `detail` 是**数组** ⇒ 请求层回落本地固定文案「请求参数不合法，已拒绝。」）。

## 2. 绑定语义（**2026-09-20 真机实测**）

```
（无绑定行） ──bind──▶ active ──unbind──▶ disabled ──bind（UPSERT 覆盖）──▶ active
                         │                    │
                      bind 幂等            unbind 幂等
                   （原样返回既有行）      （原样返回既有行）
```

| 动作 | 前置 | 行为（逐字） | 结果 |
| --- | --- | --- | --- |
| `bind` | 无任何前置校验 | 内存：有 `active` 行 ⇒ 原样返回；否则 UPSERT；PG：`INSERT ... ON CONFLICT DO UPDATE` | 恒 `200` + `active` |
| `unbind` | 绑定行必须存在 | 存在且 `active` ⇒ 置 `disabled`；已 `disabled` ⇒ 原样返回；不存在 ⇒ `SkillNotFound` | `200` / `404` |

**三条必须如实登记的服务端事实**（源码判定 + **2026-09-20 实测证实**，界面不得据此"假装更强"）
—— **⚠️ 状态更新（2026-09-21 第 12 轮）**：下列三条**全部已修复**（①② 第 11 轮、③ 第 12 轮），
本节保留为**历史登记**（当时的真机事实），**当前行为以 `docs/api-contract.md` 绑定节为准**：

1. **`bind` 不校验技能是否存在** —— 实测 `POST bindings {"skill_key":"r9-ghost-skill"}` ⇒ **`200`**，且**查库确认**新增该行
   ⇒ 可写入**指向不存在技能的悬空绑定**（真实完整性缺口，用户裁决**本轮不改**，见 §5-#1）；**第 11 轮已改为 `404`**；
2. **`bind` 不校验技能是否 `enabled`** —— 实测绑 `r8-self-probe`（`submitted`）⇒ **`200`**；但**工具面不会放大**：
   `list_enabled_for_agent` 只取 `status = enabled` 的技能 ⇒ 展开侧 fail-closed（实测该员工工具面仍为原值）；**第 11 轮已改为 `409`**；
3. **`bind` 不校验 `agent_key` 是否在数字员工目录内** —— 实测：本租户目录 `total: 0`（`GET /workforce/agents` 实测），
   而绑定 `agent-ghost` ⇒ **`200`** ⇒ "不在目录的员工键"是**真实存在**的数据形态；**第 12 轮已改为 `409`**（③A 裁决），并顺带落地**键归一化**（④A）。
4. **审计留痕复用动作码**：绑定复用 `skill.enabled`、解绑复用 `skill.disabled`，靠 `detail` 的
   `{skill_key, agent_key}` 区分（`app/skills/service.py` 注释自述）⇒ 界面/文档**不得**读成"启用了技能包"。
   **第 12 轮 ⑥A**：**幂等命中不再重复写**（只"新建 / 状态翻转"时写）——真机实测原先同一 target 最多重复 8 条。

## 3. 页面契约（绑定块）—— **已按此交付**（浏览器走查 4 张截图见 §8）

| 块 | 数据源 | 交互 | 空态口径 |
| --- | --- | --- | --- |
| **数字员工绑定**（管理视图内；`super_admin` 可操作） | 🆕 `GET /skills/bindings`（分页）+ `GET /skills`（取 `enabled` 技能作候选）+ `GET /workforce/agents`（取 `active` 员工作候选）+ `GET /skills/agents/{agent_key}/tools`（工具面预览） | 「绑定」表单（技能下拉**仅 `enabled`** + 员工**只给目录候选**；**第 12 轮 ③A 起取消"手动录入"**，服务端已要求员工键已纳管且启用）→ 提交；行内「解绑」走**二次确认**（`DangerConfirm`：解绑会立即把该技能移出该员工的工具面）；行内「查看工具面」按需拉 `tools`；成功提示**只用服务端回读值**（含**归一化后的 `agent_key`**） | 「本租户还没有把技能绑定到任何数字员工」 |
| 同块（`ceo` 视角） | **不请求绑定数据** | 控件**全部禁用 + 给原因**「绑定 / 解绑由超级管理员执行」（不静默隐藏） | 同左（说明由 super_admin 执行） |
| 同块（员工视角：`skill.submit`） | **不请求任何数据** | 只给说明：绑定属治理面，仅超级管理员可用（沿用第 7 轮 `GovernanceOnlyBlock` 手法） | 同上 |
| **工具面预览** | `GET /skills/agents/{agent_key}/tools` | 只读展示交集键列表 | **三种空结果必须分开说明**：① 该员工无绑定；② 绑定存在但技能未启用；③ 已启用但 `allowed-tools ∩ 目录` 为空 |

**四态**：加载（骨架屏）/ 空（解释为什么空）/ 错误（可重试）/ 无权限（给原因，**不渲染编辑控件**）。
**二次确认范围**：解绑（移出工具面，可回退但当场生效）走 `DangerConfirm`；绑定为新增放行、不二次确认。
**不新增导航项**：绑定块挂在既有「Skill & MCP」页的管理视图内（矩阵 §3 未列"绑定"行，新增导航项属改口径）。

## 4. 本模块**不做**（逐条登记）

| 事项 | 原因 |
| --- | --- |
| 给 `bind` 增加服务端校验（技能存在 / `enabled` / 员工在目录内） | ~~**业务逻辑改动**，超出第 9 轮范围~~ ⇒ **已于第 11 轮（技能存在 `404` / 已启用 `409`）与第 12 轮（员工已纳管 `409`、键归一化 `422`）落地**，契约见 `skill-binding-gate-plan.md` §9/§11 |
| 批量绑定（一次选多个员工 / 多个技能） | 超范围；现有接口是单对单，批量属新接口设计 |
| `unbind` 的"物理删除" / 解绑历史 | 后端只有 `active → disabled` 状态迁移，无删除面 |
| 技能 ↔ 员工绑定的**冻结 / 授权时限 / 逐工具授权** | 属运行域（九步闸门 + 逐项授权），不在本模块 |
| MCP 服务器 / 工具的任何注册与开关 | 后端**零实现**（第 8 轮已登记） |
| 跨租户绑定共享 | 后续批次（ADR-0005「明确后置」） |
| 与目录面的**联动**（员工停用 ⇒ 自动解绑、岗位停用 ⇒ 连带） | 后端无该逻辑；本轮如实呈现"绑定行与目录状态互不感知" |

## 5. 待裁决（三项；含我的建议与依据）

| # | 问题 | 选项 | 建议与依据 |
| --- | --- | --- | --- |
| 1 | `bind` 的服务端校验缺口（§2 三条事实：可写悬空绑定 / 可绑未启用技能 / 员工键不在目录） | **A** 本轮**不改后端业务逻辑**，界面自我收敛（技能候选仅 `enabled`、员工候选给目录）+ 缺口如实登记待后续专项；**B** 本轮顺带修（`bind` 校验技能存在且 `enabled`、员工键必须在目录内） | **A**。依据：宪法「不顺手改已稳定功能」+ 本轮确认范围只含"读端点 + 界面 + 工具面预览"；B 会改变既有真机数据语义（现库 `probe-agent` 不在目录）与既有用例口径，属**改稳定业务逻辑**，应另立专项。**注意**：A 下"悬空绑定"是真实存在的完整性缺口，不是"已解决" —— **✅ 后续已收口：第 11 轮落地 ①②、第 12 轮落地 ③（用户裁决 ③A）** |
| 2 | 员工键输入方式 | **A** 目录下拉（`GET /workforce/agents?status=active`）**∪ 手动录入**；**B** 仅目录下拉 | **A**（第 9 轮裁决）。依据：第 6 轮 D-020 已就"候选 + 手动录入"作出同类裁决（知识范围绑定）；且本机测试租户目录为空，仅下拉做不出真机走查 —— **⚠️ 第 12 轮改判为 B**：既然服务端已要求员工键已纳管且启用（③A），"手动录入目录外的键"必然被拒 ⇒ 界面**取消手动录入**（只给目录候选，目录为空时引导先去纳管），否则就是"界面能填、服务端必拒"的假入口 |
| 3 | 绑定块位置 | **A** 既有「Skill & MCP」页内新增一块；**B** 新增独立导航项 | **A**。依据：矩阵 §3 未列"绑定"行 ⇒ 新增导航项会动"导航可见角色"口径（需矩阵支持）；页内分块不动口径 |

## 6. 未验证 → **2026-09-20 复测结果（写码第一步已执行）**

| # | 复测项 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 新增读端点是否已存在 | 修复前 `GET /skills/bindings` ⇒ **`405`** | 端点确实不存在 ⇒ 本轮新增（现已 `200`） |
| 2 | 解绑不存在的绑定 | **`404`** `{"detail":"binding agent-nope/r9-nope"}` | **第 8 轮 §6 备注「也返回 200、未区分」为误读** ⇒ 已在 `skills-mcp-api.md` §6 更正 |
| 3 | `bind` 技能不存在 | **`200`**，查库确认新增**悬空绑定** | 缺口证实（§2-#1；裁决本轮不改） |
| 4 | `bind` 技能未启用（`submitted`） | **`200`**，且工具面**不放大** | 缺口证实 + 展开侧 fail-closed 生效 |
| 5 | `bind` 员工键不在目录 | **`200`**（目录实测 `total: 0`） | 缺口证实（§2-#3） |
| 6 | 重复绑定 / 连解两次 | **`200`** 幂等 / **`200`** 幂等 | ✔ |
| 7 | 员工越权绑定 | **`403`**「只有超级管理员可以绑定或解绑技能」 | ✔ |
| 8 | 新增读端点门禁（§7） | `ceo` / `department_lead` / `employee` / `customer_admin` ⇒ **`403`**；匿名 ⇒ **`401`**；`limit=201` ⇒ **`422`** | ✔ |
| 9 | 工具面跨角色可读性 | 四个业务角色 ⇒ **`200`**；**`customer_admin` ⇒ `403`（本轮修）** | ✔（修复前四角色全放行） |
| 10 | 写路径闭环 | 绑定 ⇒ `200 active`；工具面 ⇒ `["fs.read"]`；解绑 ⇒ `200 disabled`；工具面 ⇒ `[]` | ✔ |

**仍未验证（不得读成已验）**：
- **未测并发 / 压测**；未验证跨租户绑定可见性（`tenant_id` 过滤）真机未构造（仓储按 `tenant_id` 过滤为源码判定）。
- ~~`bind` 的三条缺口在"修复后"的正确行为未验证~~ ⇒ **✅ 已补验：第 11 轮（真机 `404` / `409`）+ 第 12 轮（真机 `409` / `422` / 归一化回读 / 审计不重复），
  见 `skill-binding-gate-plan.md` §9 / §11.6**；仍**未验证**的是"**历史非规范键行**（如含大写 / 空白的旧行）的解绑"——本轮真机实测为 **0 行**，故无样本可测（必要时用修复脚本兜底）。
- 目录面与绑定面的**联动**（员工停用 / 岗位停用是否连带解绑）—— 后端无该逻辑，**未测也不存在**。
- 绑定块的**浏览器走查**已做（超管可操作 / 员工只给治理面说明 / 已解除行按钮禁用 + 原因 / 工具面预览），
  但 `ceo` 视角的**真实浏览器**画面未逐屏截图（API 层已实测 `403`；界面层由前端用例覆盖）；截图见 `docs/screenshots/ui-v2-r9-bindings/`（4 张）。

## 7. 安全要件（新增读端点的**硬约束**；**已落地并实测**）

⚠️ **`list_bindings` 在读路径上没有任何角色判定**：`SkillService.list_bindings` 直接转发仓储，
仓储只按 `tenant_id` 过滤（内存与 PG 两条实现同）。⇒ 若 `GET /api/v1/skills/bindings` 只做"登录校验"，
**任何已登录角色都能读到本租户全部技能 ↔ 员工绑定关系**（撞宪法「数据归属」与「隐藏不等于授权」双向红线）。

⇒ **已按此实现**：`SkillService.list_bindings` 补 `ensure_can_bind(context)`（与 `POST` / `DELETE` 同一判定函数、
同一 `BIND_ROLES`），路由再把 `PolicyError` 映射为 `403`（**服务层 + 路由双层 fail-closed**）。
**实测**：四个非 `super_admin` 角色一律 `403`；**反假**：去掉该行 ⇒ 5 例变红（4 个角色参数 + 服务层 fail-closed 一例）。

**同轮一并修复的相邻缺口（工具面）**：`GET /skills/agents/{agent_key}/tools` 原先**只看登录**
（实测四角色全放行，含 `customer_admin`）⇒ 与矩阵 §3 末列「技能域 `customer_admin` 一律 ❌」不符，
且构成"前端整页无权限、接口照给数据"（安全校验只做在前端）。
**裁决（用户 2026-09-20）**：新增 `AGENT_TOOLS_ROLES = SUBMIT_ROLES`（四个业务角色）+ `ensure_can_view_agent_tools`
（`app/skills/models.py`），在 `SkillService.expanded_tools_for_agent` 处判定 ⇒ `customer_admin` ⇒ `403`
（实测原文「当前岗位不能查看数字员工的工具面」）；**不新收紧业务角色**。
**反假**：去掉该判定 ⇒ 2 例变红。

## 8. 变更留痕

- 2026-09-20：v1 建立（第 9 轮，用户确认范围「读端点 + 绑定界面 + 工具面预览」）。**证据级别 = 源码判定**，
  §6 复测清单列为写码第一步；§5 三项待用户裁决。
- 2026-09-20：**裁决回写**——§5 三项均按建议通过（① `bind` 缺口**本轮不改**、界面自我收敛；② 员工键**目录候选 ∪ 手动录入**；
  ③ 绑定块**挂在既有页内**）；**新增第五问裁决**：工具面对 `customer_admin` 放行属缺口 ⇒ **本轮修（排除 `customer_admin`）**。
- 2026-09-20：**交付回写（本文件即本轮验收依据）**——
  ① 后端：`GET /api/v1/skills/bindings`（`SkillBindingView` / `SkillBindingListView` / `_binding_view`）、
  `SkillService.list_bindings` 补 `ensure_can_bind`、`AGENT_TOOLS_ROLES` + `ensure_can_view_agent_tools`
  （`app/skills/{models,service,__init__}.py`）；`docs/api-contract.md` 同步更正（改接口先改文档）；
  ② 前端：`workbench-web/src/features/skillsMcp/components/BindingPanel.tsx`（绑定表单 + 绑定列表 + 二次确认解绑 + 工具面预览三种空因）
  + 服务层 6 个新函数（`fetchBindings` / `bindAgentSkill` / `unbindAgentSkill` / `fetchAgentTools` / `fetchAgentCandidates` 等）
  + 类型与归因纯函数；能力 `skill.bind`（仅 `super_admin`）；页面内挂载（`ceo` 见禁用 + 原因、员工见治理面说明且不请求数据）；
  ③ 门禁：后端 `2545 passed / 0 failed / 140 skipped` + `compileall` 0；前端 `tsc` 0 / `vitest` **333** / `build` 成功
  + 产物 grep（本模块样例键与 `console.log` = **0**；「示例数据」= **1**，来自第 6 轮既有缺口，非本轮引入——
  本轮自查时曾抓到**自己新引入的第 2 处**（工具面回退文案未做 DEV 门控），**已修**）；
  ④ 反假四组（去 `ensure_can_bind` ⇒ 5 红；去 `ensure_can_view_agent_tools` ⇒ 2 红；前端忽略 `canBind` ⇒ 2 红；
  放开"已解除可重复解绑" ⇒ 1 红）；
  ⑤ 真机（§6 表 10 项）+ 浏览器走查 4 张截图（`docs/screenshots/ui-v2-r9-bindings/`）；
  ⑥ 本轮探测写入的绑定行**逐条登记**进 `decision-log.md` 清理清单。
