# 「数字员工注册中心」界面接口契约（第 5 轮 · 第 6 轮接线批 2 回写）

> 状态：**v2 · 2026-09-19**（第 5 轮草案 + 第 6 轮「接线批 2」差异回写：列表 / 启停已接真接口）。
> 与 `docs/api-contract.md`（后端真源）：**只引用、不修改**；未定义 / 未接入的显式标注。
> **与 `docs/contracts/my-agents-api.md` 的关系**：同一实体的两个视角（员工侧「我的」/ 管理侧「全员」），
> **字段命名必须一致**；管理侧**多**创建者（`created_by`）与使用统计（`usage`），**不含** `ownership`。
> 字段名与 `src/features/agentRegistry/types.ts` **逐字一致**。
>
> **第 6 轮差异清单（本文件即回写结果）**：
> ① 列表 / 启停**已接线**（同一对后端端点，权限口径与本页正好一致：仅 `super_admin`）；
> ② 指标**仍无聚合接口**（实测 `GET /workforce/agents/stats` → `405`）⇒ **从真实列表派生**；
> ③ `draft`（草稿）**后端无此枚举**（库列 `CHECK (status IN ('active','disabled'))`）⇒ 类型改为 `number | null`，
>    http 下为 `null`，指标卡显示「未验证」、总数卡标签由「全部（含草稿）」改为「全部」；
> ④ 运行口径（`usage.run_count` / `success_rate` / `last_run_at` / `ran_last_7d`）后端不提供 ⇒
>    http 下恒非就绪（`unverified` / `insufficient_sample`），**绝不显示 `0` / `0%` / "成功"**；
> ⑤ **按创建者 / 名称的筛选后端不支持**（未知查询参数被静默忽略）⇒ 类型保留但 http 下**禁用 + 给原因**，服务层抛 `not_connected`；
> ⑥ `RegistryListPayload.sample` / `RegistryStatsPayload.sample` 由字面量 `true` 改为 `boolean`；
> ⑦ `template` 由 `RoleTemplate` 改为 `RoleTemplate | null`（与员工侧同步，后端不下发模板）；
> ⑧ 管理侧只读详情**仍未接入**（后端无该口径）。

## 0. 权限口径（本页仅管理角色可见）

界面：员工访问 ⇒ `PermissionGuard` 渲染**无权限态（原因 + 申请入口）**，**不请求数据、也不渲染空表格**。
接口：既有 `/api/v1/workforce/*` **仅 `super_admin`**（其他角色 `403`「只有超级管理员可以管理岗位与数字员工目录」）——
与本页的界面口径**一致**，故本批的列表 / 启停是"界面与后端同权"的直连。

## 1. 列表（含筛选 / 分页）· 复用既有接口（**本批已接线**）

| 项 | 内容 |
| --- | --- |
| 方法 / 路径 | `GET /api/v1/workforce/agents` |
| 查询参数（**后端支持**） | `status`（`active`/`disabled`）、`role_key`（自由字符串）、`limit`（1–200，默认 50）、`offset`（≥0，默认 0） |
| 查询参数（**后端不支持**） | `created_by`、`keyword`、`status=draft` ⇒ http 下**服务层抛 `not_connected`**，页面把创建者 / 名称输入框与「草稿」选项**禁用 + 给原因**（`UNSUPPORTED_FILTER_NOTE`） |
| 分页 | 必须分页；响应 `{items, total, limit, offset}`（`RegistryQuery{page, pageSize}` 换算为 `limit = pageSize`、`offset = (page-1)*pageSize`） |
| 权限 | 仅 `super_admin`；其他角色 `403`（界面 `forbidden` 态） |
| 错误码 | `401` 未认证 / `403` 非 super_admin / `422` `status`、`limit` 越界 / 他租户标识不泄露存在性 |

**为什么"不支持"要禁用而不是照样透传**：实测未知查询参数（`keyword` / `created_by`）**被后端静默忽略**，
即请求成功但返回的是**未筛选**的全量结果 —— 那比报错更危险（评审者会以为"筛了就是这些"）。
因此本批选择：**禁用 + 给原因**，并在服务层对这些参数抛 `not_connected`（防止别处误传）。

字段 ↔ 列（逐字段点名，`RegistryRow`）：

| 字段 | 来源 | 列 / 位置 |
| --- | --- | --- |
| `agent_key` | 后端 | 「员工标识」列（行键） |
| `name` | 后端 | 「名称」列（后端不支持按名称筛选，见上） |
| `description` | 后端 | 详情抽屉「工作范围」 |
| `role_key` | 后端 | 「所属岗位」列（自由字符串；模板缺失时显示「`<role_key>`（模板未接入）」） |
| `created_by` | 后端 | 「创建者」列（不透明账号标识，**不解析成姓名**） |
| `status` | 后端 | 「状态」列（`StatusTag` 受控枚举；http 下只会是 `active` / `disabled`） |
| `template` | **前端静态目录** | 「能力标签」列与详情能力包；命中项目级 6 个首批岗位才有值，否则 `null` ⇒ 「能力包未接入（后端未下发模板）」 |
| `usage.run_count` / `usage.success_rate` | **后端不提供** | 「使用统计」列 ⇒ http 下恒 `{null, null}` = 「未验证」+「暂无运行统计」，**不显示 `0` / `0%`** |
| `last_run_at` | **后端不提供** | 「最近使用」列 ⇒ http 下恒 `null` = 「未验证」+「暂无运行记录」 |
| `created_at` / `updated_at` | 后端 | 详情抽屉「创建时间」（为空显示「未提供」，不编造） |

## 2. 状态取值（受控枚举）

`active` / `disabled` 沿用后端既有枚举（库列 `CHECK (status IN ('active','disabled'))`）；
**`draft`（草稿）后端没有该枚举** —— 它只是界面的展示态：

- 样例数据里保留 `draft` 行，用于验证受控枚举与"草稿不可启停"；
- **http 下 `draft` 不可出现**：列表不返回、筛选被禁用、指标卡 `draft = null`（见 §3）；
- 界面不得因为"没看到草稿"而显示「草稿 0」（`0` 会被读成"确实没有草稿"，而事实是"后端没有这个概念"）。

## 3. 指标统计（**无聚合接口 ⇒ 从真实列表派生**）

`GET /api/v1/workforce/agents/stats` —— **后端不存在**（实测 `405 Method Not Allowed`，该路径被
`PATCH /workforce/agents/{agent_key}` 的路由匹配）。因此 `fetchRegistryStats()` 在 http 下：

1. 调 `GET /api/v1/workforce/agents?limit=200&offset=0`（**不带筛选**，全员口径）；
2. `total > items.length` ⇒ 抛 `failed`（**不把残缺派生当准数**）；
3. `total` / `active` / `disabled` 由真实行派生；
4. `draft = null`（后端无枚举 ⇒ 未接入）；`ran_last_7d = null`（无按员工的运行聚合 ⇒ 未验证）。

`RegistryStatsSummary` 字段：`total` / `active` / `disabled` / `draft`（`number | null`）/
`ran_last_7d`（`number | null`）；信封另带 `sample: boolean`。
界面：`draft === null` 时草稿卡显示「未验证」且总数卡标签改为「全部」（不再声称"含草稿"）。

> 说明（实测依据）：`GET /api/v1/metrics/summary` 存在，但它是**租户级**、**不按员工拆分**
> （实测键：`tenant_id / runtime_key / run_count / task_completion_rate / tool_success_rate /
> knowledge_hit_rate / latency_p95_ms / by_runtime`），且无运行时 `0` 会被一并填进比率字段（`0.0`）。
> ⇒ 不能据此渲染任何员工的成功率，本批**不采用**。

## 4. 详情（**未定义**）/ 启停（复用既有接口，**本批已接线**）

- 详情：既有 `GET /api/v1/workforce/agents/{agent_key}/config` 是**配置**口径且仅 `super_admin`；
  管理侧只读详情视图**未定义** ⇒ `fetchRegistryAgentDetail()` 在 http 下抛 `not_connected`；
  页面用列表已加载的行 + 复用员工侧 `CapabilityPack` 渲染（不新增字段）。
- 启停：`PATCH /api/v1/workforce/agents/{agent_key}`，请求体**恰为** `{"status":"active"|"disabled"}`；
  **传 `agent_key` 直接 `422`**（身份不可改）；`404` 不存在 / 跨租户；`409` 目标岗位不可用；审计 `workforce.agent.disabled`。
  界面必须走 `DangerConfirm`（输入确认词「停用」/「启用」）才发起调用；**未确认不得触发任何调用**。
- 写操作返回 `AgentWriteResult{agent_key, written, note}`（复用员工侧类型）：
  `written = true` **仅当** `PATCH` 返回 2xx（后端已确认写入）；`written = false` 只出现在开发期样例数据下。
  失败抛 `ServiceError`，界面按已 sanitize 的文案如实告知"本次没有写入任何数据"。

## 5. 状态保真（硬要求）

| 数据情形 | 界面（`usagePresence` / 各 presence 判定） |
| --- | --- |
| `run_count === null`（**http 下的常态**） | `unverified`：标签「未验证」+「暂无运行统计」，**不显示 0** |
| `run_count === 0` | `insufficient_sample`：标签「样本不足」+「暂无运行（成功率无从计算）」，**绝不显示 0%** |
| `run_count > 0` 且 `success_rate === null` | `not_configured`：标签「未配置」+「成功率未配置」，**不显示 0% / 100%** |
| `last_run_at === null`（**http 下的常态**） | `unverified` +「暂无运行记录」 |
| `draft === null`（**http 下的常态**） | `unverified`：草稿卡显示「未验证」，且总数卡标签改为「全部」 |
| `ran_last_7d === null` | `unverified`：「最近 7 天有运行」卡显示「未验证」 |

依据：`docs/contracts/role-templates.md` 验收第 5 条（未验证的数据不得以数字或成功态呈现）。

## 6. 通用口径

- 认证与越权：`401` 未认证；`403` 越权；`404` 不可见（不泄露存在性）；`422` 参数非法；`429` 限流；`5xx` 服务端。
- 前端取数：`services/agentRegistryService.ts` 是**唯一接线点**；HTTP 只走 `src/api/client.ts`；
  模式解析：`VITE_WORKBENCH_API_MODE`（`mock` | `http`）> 开发期默认 `mock` > **生产默认 `http`**。
  **筛选参数以服务端语义为准**：支持的（`status` / `role_key`）原样透传、页面不做前端过滤；
  不支持的（`created_by` / `keyword` / `draft`）**禁用 + 抛 `not_connected`**，绝不假装筛过。
- 样例标记：`sample` 为 `boolean`（`true` = 开发期样例，界面显示「示例数据（未接后端）」；`false` = 真实数据）。
- 失败分类：`forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态；请求层失败经 `serviceErrorFromApi` 转换（`403` ⇒ `forbidden`，其余 ⇒ `failed`）。
- 敏感信息：响应不含 PII；样例为虚构内容（无手机号 / 真实用户 ID / 租户 ID / 密钥，有自检用例）。

## 7. 真机取证记录（2026-09-19 · 第 6 轮接线批 2）

**拓扑**：`http://127.0.0.1:18112`（`uvicorn app.main:app`，**工作树代码**）+ 真库 `workbench_test`，
HTTP 客户端直调（超管 / 员工测试账号各一，`POST /api/v1/auth/sessions` 取令牌）。**未使用浏览器**。

**逐端点实测**（与 §1 / §3 / §4 逐条对齐）：

| 端点 / 场景 | 实测 |
| --- | --- |
| `GET /workforce/agents`（超管） | `200` `{"items":[],"total":0,"limit":50,"offset":0}`（本租户目录为空） |
| `GET /workforce/agents?limit=1&offset=0` | `200` `{...,"limit":1,"offset":0}`（分页参数原样生效） |
| `GET /workforce/agents?role_key=nosuch-role` | `200` + 空列表（未知岗位键不报错） |
| `GET /workforce/agents?keyword=zzz&created_by=zzz` | `200` + 与无参**完全相同** ⇒ **未知参数被忽略**（本页禁用这两个筛选的实测依据） |
| `GET /workforce/agents?status=draft` | `422` `{"detail":"状态只能是 active 或 disabled"}` |
| `GET /workforce/agents?limit=0` / `?limit=201` | `422`；`detail` 为**数组**（FastAPI 校验结构）⇒ 请求层 `safeDetail` 只接受字符串，界面回落固定文案 |
| `GET /workforce/agents`（匿名） | `401` `{"detail":"缺少登录身份信息"}` |
| `GET /workforce/agents`（员工令牌） | `403` `{"detail":"只有超级管理员可以管理岗位与数字员工目录"}` |
| `GET /workforce/agents/stats` | **`405`** `{"detail":"Method Not Allowed"}` ⇒ **无聚合统计接口**（§3 的实测依据） |
| `PATCH /workforce/agents/{不存在}`（`{}`） | `404` `{"detail":"no-such"}`（标识原样回显） |
| `PATCH /workforce/agents/{不存在}`（`{"agent_key":"x"}`） | `422`，`detail` 数组，`type = extra_forbidden` |
| `PATCH /workforce/agents/x`（员工令牌） | `403` |
| `GET /metrics/summary`（超管） | `200` `{"tenant_id":"…","runtime_key":null,"run_count":0,"task_completion_rate":0.0,"tool_success_rate":0.0,"knowledge_hit_rate":0.0,"latency_p95_ms":0,"by_runtime":[]}` ⇒ **租户级、不按员工拆分**，不采用 |

**落库核对**：探针**未产生任何写入**（`PATCH` 全部命中不存在的标识；本批未调用创建端点）；
数字员工目录在本批取证前后均为空（列表接口 `total = 0`）。

**未验证（不得读成已验）**：
① **条目级字段形状未在真机观测**（目录为空）：`DigitalEmployeeView` 的 8 个键只经模型定义核对；
② **启停成功路径未验证**：无对象可改 ⇒ `PATCH` 的 2xx 与 `written = true` 分支**只有单测覆盖**；
③ **界面渲染层未在真机走查**（未起浏览器）：无权限态 / 空态 / 指标「未验证」/ 筛选项禁用只有单测与构建产物 grep 覆盖；
④ 未测 `429`、令牌自然过期、并发；`limit` 上限 200 的截断只有单测；
⑤ 「草稿」永远是界面展示态：后端是否有意补该枚举**未确认**（本批按"未接入"处理）。