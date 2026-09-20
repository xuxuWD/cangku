# 「Skill & MCP」界面接口契约（第 8 轮）

> 状态：**v1 · 2026-09-20 · 契约先行（本文件确认后才写码）**。
> **唯一权威在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)（§3「技能」行）；
> 技能层规格 = `docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md`；
> 后端契约真源 = `docs/api-contract.md`（**只引用、不修改**）。
> 本文件只声明**界面所需的最小接口集**。
>
> **证据级别**：v1 落盘时为源码判定；**2026-09-20 已按用户裁决完成真机复测**（工作树后端 + 真库 `workbench_test`，
> 超管 `13600000001` / 员工 `13600000002`，仅本机非生产），实测结果已回写 §1 / §2 / §8；
> 复测额外抓到 3 条源码未显的**请求校验**与 **1 条真缺陷**（`bind` 恒 500，见 §8）。仍未取证项见 §6。

## 1. 接口清单与角色门禁

| 方法 | 路径 | 用途 | 角色门禁（**实测** 2026-09-20） |
| --- | --- | --- | --- |
| POST | `/api/v1/skills` | 提交技能包（申报，不生效；**幂等**：同 `skill_key@version` 返回既有） | **提交行**：`employee` / `department_lead` / `ceo` / `super_admin`；`customer_admin` ❌ |
| GET | `/api/v1/skills` | 列表（`status` 可选、`limit` 1–200、`offset`；**必须分页**） | 全部登录角色，但**可见性收敛**：管理员全看；他人仅 `approved`/`enabled`/`disabled` 可见（`submitted`/`rejected` ⇒ 按"未找到"处理） |
| POST | `/api/v1/skills/{skill_key}/versions/{version}/review?approved=<bool>` | 审核（**`approved` 必填 query**） | **管理行**：`ceo` / `super_admin`（2026-09-20 裁决对齐矩阵，见 §5）；**且不能审自己提交的包** |
| POST | `…/{version}/enable` | 启用 | `ceo` / `super_admin`（同上） |
| POST | `…/{version}/disable` | 停用 | `ceo` / `super_admin`（同上） |
| POST | `/api/v1/skills/bindings` | 绑定技能到数字员工（`{skill_key, agent_key}`，`extra="forbid"`） | 仅 `super_admin`；**2026-09-20 已修复**（原恒 `500`，见 §7）：实测 `200` + 绑定形状 |
| DELETE | `/api/v1/skills/bindings?skill_key=&agent_key=` | 解绑（`active → disabled`） | 仅 `super_admin`；实测 `200` + 绑定形状（声明与返回同形） |
| GET | `/api/v1/skills/agents/{agent_key}/tools` | 该员工已启用技能的 `allowed-tools` ∩ 执行目录**交集**（服务端解析，fail-closed） | 四个业务角色可读；**`customer_admin` ⇒ `403`**（2026-09-20 第 9 轮修正：此前只看登录 ⇒ 四角色全放行，见 `skill-bindings-api.md` §7） |
| GET | `/api/v1/skills/{skill_key}/versions/{version}/content` | 技能包**正文**（详情专用，避免拖大列表） | 本人或管理员；他人未审包按 `404`（避免探测存在性） |
| POST | `…/{version}/memories` | 把使用经验沉淀为事实类记忆（`{content}` ≤2000；**幂等**） | 技能须对操作者可见；记忆层未接线 ⇒ **`503`**（fail-closed，不静默降级） |

**响应形状（源码逐字）**
- `SkillView`：`skill_key / version / name / description / license / allowed_tools[] / status / source_key / owner_id / reviewed_by / created_at / updated_at`（**不含正文**）
- 列表：`{ items: SkillView[], total, limit, offset }`
- 正文：`{ skill_key, version, content_body, content_sha256 }`
- 工具交集：`{ agent_key, tools: string[] }`
- 经验沉淀：`{ skill_key, version, fact_id, idempotency_key, tagged_content }`
- 绑定 / 解绑：`{ skill_key, agent_key, status }`（`active` / `disabled`）

**提交入参（`extra="forbid"`）**：`skill_key`(≤64) / `version`(≤32) / `name`(≤64) / `description`(≤800) /
`license`(≤32) / `allowed_tools[]` / `source_key`(≤64) / `content_sha256`(**恰 64**) / `content_body`(可空，体积上限 `skill_content_max_bytes`)。

**复测额外抓到的三条校验（源码未显，均为 `422` 且文案原文如下）** —— 界面必须**如实呈现服务端原文**、
且**不在前端复算**这些规则（前端只做非空/长度这类易用性校验）：

| 规则 | 实测文案 | 含义 |
| --- | --- | --- |
| `version` 必须是**语义版本** | 「version 必须是 major.minor.patch 语义版本号」 | `1` 会被拒，须 `1.0.0` |
| `content_sha256` 必须与 `content_body` **指纹一致** | 「content_sha256 与技能包正文指纹不一致」 | 前端**不代算**指纹（避免与后端算法不一致造成假通过） |
| `allowed_tools` 必须是**执行工具目录内的键** | 「allowed-tool 不在工具目录内：read_file」 | 合法键形如 `fs.read` / `fs.list` / `cmd.run` 等（目录见 `app/tool_execution/catalog.py`）；界面**不提供自造键** |

## 2. 状态机（**2026-09-20 真机实测**）

```
submitted ──review(approved=true)──▶ approved ──enable──▶ enabled ──disable──▶ disabled
    │                                                          ▲                  │
    └──────review(approved=false)──▶ rejected                  └────enable────────┘
```

| 当前状态 | review(true) | review(false) | enable | disable |
| --- | --- | --- | --- | --- |
| `submitted` | → `approved`（置 `reviewed_by`） | → `rejected` | ❌ `409`「仅 approved / disabled 状态的技能包可启用」 | ❌ `409`「仅 enabled 状态的技能包可停用」 |
| `approved` | ❌ `409`「仅 submitted 状态的技能包可审核」 | ❌ `409` | → `enabled` | ❌ `409` |
| `rejected` | ❌ `409` | ❌ `409` | ❌ `409` | ❌ `409` |
| `enabled` | ❌ `409` | ❌ `409` | ✅ **幂等**（原样返回） | → `disabled` |
| `disabled` | ❌ `409` | ❌ `409` | → `enabled` | ✅ **幂等** |

- **审核自审批拦截**：`skill.owner_id == 调用者` ⇒ `403`「不能审核自己提交的技能包」（职责分离）。**已实测**：超管提交 `r8-self-probe` 后审自己 ⇒ `403` 原文如上。
- **来源白名单（fail-closed）**：`source_key` 不在部署注入的 `skill_source_allowlist` ⇒ **`403`**（`SkillSourceDenied`）。
- 其他错误映射：`409` 状态冲突 / `422` 包校验（许可、工具键、描述注入扫描）/ `404` 不存在或不可见 / `503` 记忆层未接线。

**实测证据（员工提交 → 超管审核 → 启停，逐条 `curl`，真库核对状态一致）**

| # | 操作 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 员工提交（`1.0.0` + 正确指纹 + `fs.read`） | **`201`**，回读 `status=submitted`、`owner_id=<员工>`、`reviewed_by=null` | ✔ |
| 2 | 同载荷重复提交（幂等） | **`201`**，返回既有记录 | ✔ 幂等 |
| 3 | 员工审核（越权） | **`403`**「只有超级管理员可以审核或启用技能包」 | ✔ |
| 4 | 超管审核通过 | **`200`**，回读 `status=approved`、`reviewed_by=<超管>` | ✔ 职责分离生效 |
| 5 | 重复审核（已 `approved`） | **`409`**「仅 submitted 状态的技能包可审核」 | ✔ 与本表一致 |
| 6 | 启用 → 停用 → 重复停用 | `200`（`enabled`）→ `200`（`disabled`）→ **`200`（幂等）** | ✔ |
| 7 | 本人读正文 | **`200`** `{content_body, content_sha256}`（指纹与提交值一致） | ✔ |
| 8 | 经验沉淀 | **`200`**（`fact_id` / `idempotency_key` / `tagged_content` 前缀 `[skill:…@…]`） | ✔ 记忆层已接线 |
| 9 | 员工列表（已审 ⇒ 可见） | **`200`**，含该包（`disabled`） | ✔ 可见性收敛生效 |
| 10 | 超管审自己提交的包 | **`403`**「不能审核自己提交的技能包」 | ✔ |

## 3. 页面契约（两视图 + MCP 说明）

| 块 | 数据源 | 交互 | 空态口径 |
| --- | --- | --- | --- |
| **技能包 · 管理视图**（`ceo` / `super_admin`） | `GET /skills`（分页） | 列表（`skill_key@version` / 名称 / 许可 / `allowed_tools` / 状态 / 来源 / 提交人 / 审核人）+ 行内「审核（通过/退回）」「启用/停用」按 §2 合法前置状态**启用**，不合法一律**禁用 + 给原因**（不静默隐藏）+ **不能审自己的包**（`403` 服务端判定，界面按"提交人=自己"预置禁用 + 原因）+ 详情抽屉（含正文，按需拉 `content`） | 「本租户还没有提交任何技能包」（解释为什么空） |
| **技能包 · 员工视图**（`employee` / `department_lead`） | `POST /skills` + `GET /skills`（**可见性收敛**：本人未审包可见、他人未审包不可见） | 「提交技能包」表单（`skill_key` / 语义版本 / 名称 / 描述 / 许可 / `allowed_tools` / 来源 / 指纹 / 正文）+ 本人可见列表（**只读**：审核 / 启停四个动作**一律禁用并给出"由谁执行"的原因**，不静默隐藏、也不放开点击） | 「你还没有提交过技能包；提交后由企业负责人或超级管理员审核」 |
| **MCP** | **无接口** | 只读说明：**后端零实现** ⇒ 如实呈现「尚未接入」，**不伪造服务器 / 工具清单** | 「MCP 服务器注册中心尚未接入」 |

**四态**：加载（骨架屏）/ 空（解释为什么空）/ 错误（可重试）/ 无权限（`PermissionGuard`，给原因，**不渲染编辑控件**）。
**导航**：`skills-mcp` 入口由 `ADMIN_ONLY` 改为四个角色可见（矩阵 §3「技能：提交」含 `employee` ✅）。

## 4. 本模块**不做**（逐条登记）

| 事项 | 原因 |
| --- | --- |
| MCP 服务器 / 工具的任何注册、连通性测试、开关 | 后端**零实现**（`app/` 无任何 `mcp` 引用 ⇒ 无端点可接） |
| 技能包**上传文件**（zip / 目录） | 现有提交接口是**声明式 JSON**（含 `content_sha256` 与可选 `content_body`），前端不代算指纹、不做包解析 |
| 工具逐项授权 / 九步闸门可视化 | 属运行域（工具授权在运行链路内），不在本模块 |
| 技能经验沉淀的编辑 / 删除 | 只有"写入一条事实记忆"一个接口，无读 / 改 / 删面 |
| **技能 ↔ 数字员工「绑定」界面** | 后端 `POST /skills/bindings` 曾恒 500；**2026-09-20 已修复**（§7），但绑定界面仍**不在本轮范围**（本轮只做"技能包"两视图 + MCP 说明），留待下一轮单独立项 |
| 跨租户技能市场 / 第三方技能安装 | 后续批次（ADR-0005「明确后置」） |

## 5. 与已签矩阵的**偏差**及其处置（用户 2026-09-20 裁决）

`permission-matrix.md` §3 写「技能：复核/启用/停用 = `employee` ❌ / `department_lead` ❌ / `ceo` ✅ / `super_admin` ✅」，
但实现里 `app/skills/models.py:41` `REVIEW_ROLES = frozenset({"super_admin"})` ⇒ **`ceo` 复核 / 启用 / 停用一律 `403`**
（与第 7 轮知识域的 P0 **同一类**：实现窄于矩阵）。另：矩阵 §3「技能：提交」含 `employee` ✅，
但前端导航 `skills-mcp` 的可见角色是 `ADMIN_ONLY`（仅 `super_admin`）⇒ **员工侧入口缺失**。

**用户 2026-09-20 裁决**：① 技能复核/启停对 `ceo` ⇒ **对齐矩阵**（`REVIEW_ROLES` 扩为 `{ceo, super_admin}`，
与知识域同手法：实现向矩阵对齐、不改矩阵口径）；② 员工侧提交入口 ⇒ **同轮开放**（导航 + 员工侧提交表单）。
⇒ 下方 §3 页面契约相应扩为**两视图**（员工：提交 + 本人可见列表；管理：全量治理 + 复核/启停）。

## 6. 未验证（不得读成已验）

- ~~本文件全部端点形状与状态机为源码判定，未真机复测~~ ⇒ **已补：2026-09-20 真机复测 10 项（见 §2 表）**。
- `source_key` 白名单的**完整取值集合**未穷举（本轮验证了 `manual` 通过；白名单由部署配置 `WORKBENCH_SKILL_SOURCE_ALLOWLIST` 注入）。
- `content_body` 体积上限（`skill_content_max_bytes`，默认 64 KiB）**边界未实测**；描述注入扫描的触发样例未构造。
- `allowed_tools` 与执行目录"交集"的**完整键集合**未穷举（实测 `read_file` 被拒、`fs.read` 通过）。
- 记忆层**未接线**时 `…/memories` 的 `503` 未复现（本机记忆层已接线，实测走通 `200`）。
- ~~**`bind` 恒 500（见 §7）**：其"修复后"的正确行为未验证~~ ⇒ **已补（2026-09-20 修复后真机复测）**：
  `200` + `{skill_key, agent_key, status:"active"}`、`tools` 展开 `["fs.read"]`、员工 / `ceo` 绑定均 `403`。
- ~~`unbind` 对不存在的绑定"未区分（也返回 200）"~~ ⇒ **2026-09-20 第 9 轮复测更正为 `404`**：
  `DELETE /skills/bindings?skill_key=r9-nope&agent_key=agent-nope` ⇒ **`404`** `{"detail":"binding …"}`
  —— 源码判定（内存与 PG 两条实现都抛 `SkillNotFound`）本就正确；第 8 轮那条 `200` 是**绑定行确实存在**
  （旧 `bind` 500 缺陷在序列化前写入，已查库证实）⇒ 原备注「未区分」为**误读**。已 `disabled` 的绑定再解 ⇒ `200` 幂等（实测）。
- **绑定面的服务端校验缺口（2026-09-20 真机实测，用户裁决本轮不改）**：`bind` **不校验**技能是否存在 / 是否 `enabled` /
  `agent_key` 是否在目录内（三者均 `200`，可写入悬空绑定）；界面自我收敛 + 缺口登记，详见
  [`skill-bindings-api.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/skill-bindings-api.md) §2 / §5。
- `ceo` 的**真机**复核 / 启停走的是**开发模式头身份**（本机无真 `ceo` 账号；造 ceo 需走注册 + 审批流程），
  生产环境不允许头身份 ⇒ 「真 ceo 账号走登录令牌复核」这一路径**未在真机验证**（API 层用例已覆盖，机制同一份判定）。
- **前端工具键下拉是"提示集合"**（13 个键，来源 `app/tool_execution/catalog.py`）：后端新增工具键时前端须同步，
  该同步缺口**未自动化**（无生成器 / 无 CI 校验）。
- 未测并发 / 压测；未验证跨租户可见性（`SkillNotFound` 的 404 语义）真机未构造。

## 7. 真机复测发现的**真缺陷**（2026-09-20 发现；用户裁决「本轮修复」——**已修复并复测**）

**`POST /api/v1/skills/bindings` 恒 `500 Internal Server Error`**（技能存在与否都一样）。**状态：已修复（2026-09-20）**。

- **根因（后端日志异常栈 + 只读源码）**：路由声明了 `response_model=SkillView`，但处理函数返回的是
  **绑定形状** `{"skill_key": …, "agent_key": …, "status": "active"}`（`app/main.py:2855-2862`）
  ⇒ FastAPI 序列化时抛 `ResponseValidationError: 7 validation errors`（缺 `version` / `name` / `description` /
  `license` / `allowed_tools` / `source_key` / `owner_id`）⇒ 500。
- **旁证**：`DELETE /api/v1/skills/bindings`（解绑，`app/main.py:2865`）**未**声明 `response_model` ⇒ 正常返回 `200`
  —— 同一形状的两端，一个 500 一个 200，指向声明错误而非业务逻辑。
- **影响**：技能 ↔ 数字员工 的**绑定动作完全不可用**（解绑可用）；`GET /skills/agents/{agent_key}/tools`
  因此实测恒为空交集（`{"tools":[]}`，无绑定可展开）。
- **修复建议（最小）**：把该路由的 `response_model` 改为绑定响应模型（如新增 `SkillBindingResponse`）
  或移除声明；**不涉及业务逻辑**。**用户 2026-09-20 裁决：本轮修**（修复与验证证据将回写本文件 §1/§8）。
- ⚠️ **副作用核对（已按此执行）**：500 发生在**序列化阶段**（handler 已 `return`）⇒ 绑定写入**确实已成功**。
  2026-09-20 修复前查库证实：`workbench_skill_bindings` 存在 `probe-agent ↔ r8-probe-skill`（`active`，
  `created_by = acct-1339f8b340df`，租户 `wiring-evidence`）⇒ 修复后该次 `bind` 走**幂等**返回既有记录。
  残留行按"测试库探针数据"登记进清理清单（见 `decision-log.md`）。
- **修复内容（逐行）**：`app/main.py` 新增 `SkillBindingResponse(skill_key, agent_key, status)` 并在
  `POST` / `DELETE /api/v1/skills/bindings` 两处声明（`DELETE` 原先未声明、返回同形，**无行为变化**）；
  业务逻辑零改动。`docs/api-contract.md`「技能（P4 技能层）」节同步更正（改接口先改文档）。
- **回归锚点**：`tests/test_skills_role_matrix.py` 的 `test_bind_returns_binding_shape_and_tools_expand`
  / `test_bind_is_idempotent_and_survives_repeat` / `test_unbind_returns_binding_shape_and_empties_tools`
  —— 把 `response_model` 改回 `SkillView` ⇒ 立即复现 `ResponseValidationError`（7 项缺失），**反假已实测**。

**同轮一并修复的**：矩阵 §3「技能：复核/启用/停用」行对 `ceo` 的偏差（`REVIEW_ROLES` 由 `{super_admin}`
扩为 `{ceo, super_admin}`，文案改「只有企业负责人或超级管理员可以审核或启用技能包」）；
**绑定口径刻意不动**（矩阵未列该行，仍仅 `super_admin`，新增独立 `BIND_ROLES` 以免被复核对齐顺带放开）。

## 8. 变更留痕

- 2026-09-20：v1 建立（第 8 轮，用户裁决「先出契约」）。**证据级别 = 源码判定**，真机复测列为写码第一步。
- 2026-09-20：**真机复测回写**——§1 表头改实测、`bind` 行标 500、新增三条请求校验（语义版本 / 指纹一致 / 工具目录）；
  §2 改实测并补 10 项证据表；§5 记录两项偏差的裁决（对齐矩阵 + 员工入口同轮开放）；§6 更新；
  新增 §7（`bind` 恒 500 的真缺陷与根因）。
- 2026-09-20：**裁决回写**——`bind` 500 由用户裁决**本轮修复**（§7 标题与结尾）；§3 扩为两视图（员工 / 管理）+ 导航口径；
  §4 增列「绑定界面不做」（依赖 §7 修复）。
- 2026-09-20：**交付回写（本文件即本轮验收依据）**——
  ① 后端修复：`REVIEW_ROLES` 对齐矩阵（`ceo` + `super_admin`）+ `bind` 响应模型修复（§7）；
  ② 前端交付：`workbench-web/src/features/skillsMcp/**`（两视图 + MCP 说明 + 四态 + 提交表单 + 详情正文）、
  导航 `skills-mcp` 由 `ADMIN_ONLY` 改为四角色可见（`src/app/navigation.ts`）、
  能力分档 `skill.manage`（ceo/super_admin）+ `skill.submit`（四角色）（`src/app/session.tsx`）、
  **会话新增本人账号标识**（`workbench.user`，为"不能审自己的包"的界面预置禁用所需）；
  ③ 门禁：后端 `2527 passed / 0 failed`（含新增 `tests/test_skills_role_matrix.py` 18 例）+ `compileall` 0；
  前端 `tsc` 0 / `vitest` 300 passed / `npm run build` 成功 + 产物 grep（skill 样例键 `sample-*` = 0、`console.log` = 0）；
  ④ 反假 5 组实测：`REVIEW_ROLES` 回退 ⇒ 2 例红；去 owner 闸门 ⇒ 2 例红；`response_model` 回退 ⇒ 复现 500；
  导航回退 `ADMIN_ONLY` ⇒ 3 例红；去自审预置 ⇒ 2 例红；
  ⑤ 真机（`127.0.0.1:18112` + 真库 `wiring-evidence`）：`bind 200` + `tools ["fs.read"]` +
  员工 / ceo 绑定 `403` + ceo 复核 / 启停 `200` + 查库与审计逐条对上（证据见 §7 与 `decision-log.md`）；
  ⑥ **遗留登记**：产物 grep 命中 1 处「示例数据」——来源是**第 6 轮 `permissionsService.ts` 的
  `SAMPLE_DESCRIPTION` 未做 DEV 门控**（本轮未改动该文件，属既有缺口，已登记待裁决，不在本模块范围内）。
