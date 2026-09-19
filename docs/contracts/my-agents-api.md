# 「我的数字员工」界面接口契约（第 4 轮 · 第 6 轮接线批 2 回写）

> 状态：**v2 · 2026-09-19**（第 4 轮草案 + 第 6 轮「接线批 2」差异回写：列表 / 配置 / 停用已接真接口）。
> 与 `docs/api-contract.md`（后端真源）的关系：**只引用、不修改**；已存在的接口按原文口径标注，
> 未定义 / 未接入的在本文件**显式标注**。字段名与 `src/features/myAgents/types.ts` **逐字一致**。
>
> **范围**：只声明本模块 UI 所需的**最小接口集**。
>
> **第 6 轮差异清单（本文件即回写结果）**：
> ① 列表 / 配置 / 停用**已接线**，空数组不再是"未接入"（见 §1 / §5 / §6）；
> ② `template`（能力包）**后端不下发** ⇒ 类型改为 `RoleTemplate | null`，由前端项目级目录按 `role_key` 解析，未知岗位键为 `null`；
> ③ `ownership` 新增 `'unknown'`（**归属无法判定**：后端不下发当前用户标识、也没有「共享」实体）；
> ④ `role_key` 由受控枚举 `RoleKey` 放宽为 `string`（后端是自由字符串，员工表外键指向 `workbench_job_roles`）；
> ⑤ `last_run_at` 在 http 下**恒为 `null`**（后端目录视图不含运行时间）⇒ 界面一律「未验证」；
> ⑥ `AgentWriteResult.written` 由字面量 `false` 改为 `boolean`（真写入为 `true`）；
> ⑦ `SamplePayload.sample` 由字面量 `true` 改为 `boolean`（真实数据必须为 `false`）；
> ⑧ **创建**本批**未接入**（后端有 `POST`，但口径不符，见 §3）；「岗位模板列表」「员工侧详情」仍未接入（§2 / §4）。

## 0. 接线结论总览（先读）

| 能力 | 端点 | 本批结论 |
| --- | --- | --- |
| 列表 | `GET /api/v1/workforce/agents` | **已接线**（后端为**管理目录**口径，仅 `super_admin`） |
| 配置（改名 / 工作范围） | `PATCH /api/v1/workforce/agents/{agent_key}` | **已接线**（`{name, description}`） |
| 停用 | `PATCH /api/v1/workforce/agents/{agent_key}` | **已接线**（`{status:"disabled"}`） |
| 启用 | 同上 | 未接线（本页无启用动作；注册中心页有） |
| 岗位模板列表 | — | **未接入**（后端无模板实体）· http 如实抛 `not_connected` |
| 员工侧只读详情 | — | **未接入**（后端无员工侧详情接口；页面用列表已加载的行） |
| 创建（从岗位模板） | — | **未接入**（见 §3，后端 `POST` 口径不符）· 入口保留但**禁用 + 给原因** |

**为什么"我的"仍要调管理目录接口**：后端**没有**员工侧「我创建的 ∪ 共享给我的」口径，`GET /api/v1/workforce/agents`
是唯一存在的数字员工列表接口，且**仅 `super_admin`**（其他角色一律 `403`）。本批如实接入该接口，
并让非管理角色走**无权限态**（不是空列表、不是加载失败），原因文案明说"该目录接口只对超级管理员开放"。

## 1. 列表（`GET /api/v1/workforce/agents`）· **本批已接线**

| 项 | 内容 |
| --- | --- |
| 方法 / 路径 | `GET /api/v1/workforce/agents` |
| 请求参数 | `status`（可选 `active`/`disabled`）、`role_key`（可选，自由字符串）、`limit`（1–200，默认 50）、`offset`（≥0） |
| 前端请求 | `limit=200&offset=0`（`AGENT_PAGE_LIMIT = 200`），**不分页**：`total > items.length` 时抛 `failed`，**不展示残缺列表** |
| 分页 | 响应含 `total` / `limit` / `offset` |
| 权限 | **仅 `super_admin`**；其他角色 `403`（界面进 `forbidden` 态） |
| 错误码 | `401` 未认证；`403` 非 super_admin；`422` `status` / `limit` 非法 |

**响应键名（逐个点名）**：信封 `items` / `total` / `limit` / `offset`；
条目 = 后端 `DigitalEmployeeView`（`app/main.py:1399`）的 **8 个键**：
`agent_key` / `name` / `description` / `role_key` / `status` / `created_by` / `created_at` / `updated_at`。
**没有** `template` / `last_run_at` / `ownership` / `usage`。

字段 ↔ 界面（`AgentItem`）：

| 字段 | 来源 | 卡片 / 详情位置 |
| --- | --- | --- |
| `agent_key` | 后端 | 行键与详情「标识」 |
| `name` | 后端 | 卡片标题 + 头像首字母 |
| `description` | 后端 | 详情「工作范围」 |
| `role_key` | 后端 | 卡片「所属岗位」；能力包解析键（**自由字符串**，不保证是首批 6 个岗位） |
| `status` | 后端 | 卡片状态标签（`active` → 已启用 / `disabled` → 已停用）；**未知取值抛 `failed`**，不误标 |
| `created_by` | 后端 | 不直接展示（本批也**无法**用于归属判定，见下） |
| `created_at` / `updated_at` | 后端 | 详情「创建时间」（为空时不编造，显示「未提供」） |
| `last_run_at` | **恒 `null`** | 卡片/详情「最近使用」⇒ 必须显示「暂无运行记录 / 未验证」 |
| `ownership` | **恒 `'unknown'`** | 卡片归属标签「归属未判定」+ 独立分区（见下） |
| `template` | **前端静态目录** | 卡片能力标签与详情能力包；岗位键不在目录里 ⇒ `null` ⇒ 「模板未接入」 |

**归属（`ownership`）为什么恒为 `unknown`**：后端只下发 `created_by`（不透明账号标识，如 `acct-xxxxxxxx`），
而前端会话**只存令牌与角色**（`src/app/session.tsx` 的 `persistSession(token, role)`，批 1 已交付、本批不改），
拿不到当前 `user_id`；后端也没有任何「共享」实体。⇒ 一律 `unknown`，**绝不编造成"我创建的"**；
界面单独成区并说明原因，配置 / 停用按"他人创建"同口径处理（需要 `agent.manage`）。

**能力包（`template`）来源声明**：后端**没有模板实体**（§2），列表也不下发 `template`。
本批由前端**项目级唯一目录**（`docs/contracts/role-templates.md` → `ROLE_TEMPLATES`，生产构建同样存在、非样例数据）
按 `role_key` 解析：命中 6 个首批岗位之一才有值，否则 `null`。
界面**必须**说明"能力包按项目级目录解析、后端未下发"，且不得暗示它等于服务端实际生效的配置
（实际生效的 `autonomy_level` / `tool_allowlist` 在 `GET .../config`，本批未接入）。

## 2. 岗位模板列表（**未定义**）

**未定义接口**：后端无模板实体（`role-templates.md` §3：`workbench_job_roles` / `workbench_digital_employees`
均无模板列，需待 `adr.md` 签字后落库）。
`fetchRoleTemplates()` 在 `mode='http'` 时**如实抛 `not_connected`**（文案 `ROLE_TEMPLATE_NOTE`），
**不返回空数组**、也不返回前端静态目录冒充服务端数据。

`RoleTemplate` 字段，**逐个点名**（对齐 `role-templates.md` §1）：`role_key` / `name` / `mission` /
`skills[]` / `tools[]` / `knowledge_scopes[]` / `memory_policy{ scope, write_categories[] }` /
`autonomy_level` / `budget_cents`（**整数分**）。`org_ref` 为预留位，本期不建模。

## 3. 创建（**未接入**）

**实测：`POST /api/v1/workforce/agents` 存在**（`app/main.py:1541`），但**三条口径都不符**：

1. 请求体要求**客户端自带** `agent_key`（`{"agent_key","name","role_key","description"}`；缺字段 `422`）——
   与"标识由服务端生成"相反（前端生成标识属越界，不做）；
2. **仅 `super_admin`** 可调用（员工侧一律 `403`）；
3. 后端无模板实体 ⇒ 没有"从岗位模板继承能力包"的服务端口径。

因此员工侧「从岗位模板创建」本批**未接入**：`createAgent()` 在 `mode='http'` 时抛 `not_connected`
（文案 `CREATE_AGENT_NOTE`），页面**保留入口但禁用并给出原因**（`title`）——
**不生成假 `agent_key`、不假装创建成功、不写死一条假记录**。
实测错误：缺字段 `422`；`role_key` 无对应启用岗位 `409`（`{"detail":"岗位不存在或不属于本租户"}`）。

## 4. 员工侧只读详情（**未接入**）

既有 `GET /api/v1/workforce/agents/{agent_key}/config`（**仅 super_admin**，`404` 不存在 / 跨租户）
是**配置**口径（`system_prompt` / `model_key` / `temperature` / `tool_allowlist` / `memory_policy` /
`autonomy_level` / `risk_threshold` / `approval_timeout_minutes` / `daily_budget_cents`），不是本页展示模型。
员工侧只读详情**未定义** ⇒ `fetchAgentDetail()` 在 http 下抛 `not_connected`；
详情抽屉直接用列表已加载的 `AgentItem`（**不发额外请求**）。

## 5. 停用（`PATCH /api/v1/workforce/agents/{agent_key}`）· **本批已接线**

| 项 | 内容 |
| --- | --- |
| 方法 / 路径 | `PATCH /api/v1/workforce/agents/{agent_key}` |
| 请求体 | `{"status":"disabled"}`（本页只发这一个键） |
| 响应 | 单条 `DigitalEmployeeView`（8 个键，同上） |
| 权限 | **仅 `super_admin`**；其他角色 `403` |
| 错误码 | `401` / `403` / `404` 不存在或跨租户 / `409` 目标岗位不可用 / `422` 非法状态 |
| 审计 | `workforce.agent.disabled`（后端既有） |

界面：必须走 `DangerConfirm`（输入确认词「停用」）才发起调用；**未确认不得触发任何调用**。

## 6. 更新（配置）· **本批已接线**

同 §5 的 `PATCH`，请求体**恰为** `{"name","description"}`：

- **只改名称与工作范围**（`agent_key` 是身份，传了直接 `422` extra_forbidden；本页不改 `role_key`）；
- 能力包不可改（改能力属"换岗 / 升级模板"，另立动作）；
- 成功返回单条 `DigitalEmployeeView`，界面按 `AgentWriteResult{ agent_key, written: true, note }` 如实告知。

## 7. 状态保真与写操作口径（硬要求）

- `last_run_at === null` ⇒ 界面必须显示「暂无运行记录 / 未验证」（`DataPresence = unverified`），
  **不得显示 `0`、不得显示"成功"**。http 模式下后端不下发运行时间 ⇒ **恒为 `null`**。
- 写操作返回 `AgentWriteResult{ agent_key, written, note }`：
  `written = true` **仅当** `PATCH` 返回 2xx（后端已确认写入）；`note` 如实说"已写入后端"。
  `written = false` 只出现在开发期样例数据下（`MOCK_WRITE_NOTE`，文案含「未接后端」）。
  失败必须抛 `ServiceError`（`forbidden` / `failed`），界面按已 sanitize 的文案如实告知"本次没有写入任何数据"。

## 8. 通用口径

- 认证与越权：未认证 `401`；越权 `403`；跨租户 / 不可见 `404`（不泄露存在性）；`422` 参数非法；`429` 限流；`5xx` 服务端。
- 前端取数：`services/myAgentsService.ts` 是**唯一接线点**（页面与组件都不认识 URL）；HTTP 只走 `src/api/client.ts`。
  模式解析：`VITE_WORKBENCH_API_MODE`（`mock` | `http`）> 开发期默认 `mock` > **生产默认 `http`**。
- 样例标记：`SamplePayload<T>.sample` 为 `boolean`：`true` = 开发期样例（界面显示「示例数据（未接后端）」），
  `false` = 后端真实数据；**禁止**互相冒充。样例数据整块包在 `import.meta.env.DEV` 分支里，生产构建为 0 命中。
- 失败分类：`forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态（`panelStateOfError`）。
  请求层失败 → 适配层失败用共享原语 `serviceErrorFromApi`：`403` ⇒ `forbidden`，其余 ⇒ `failed`。
- 敏感信息：响应不含 PII；样例为虚构内容（无手机号 / 真实用户 ID / 租户 ID / 密钥，有自检用例）。
  `created_by` 是不透明账号标识，界面仅按原样展示（不解析成姓名、不猜测身份）。

## 9. 真机取证记录（2026-09-19 · 第 6 轮接线批 2）

**拓扑（据实登记）**：`http://127.0.0.1:18112` 上运行的 `uvicorn app.main:app`（**跑的是本仓库工作树代码**），
连**真库** `workbench_test`（本机 `wb-test-postgres-1` 映射端口）；账号为测试数据（超管 / 员工各一），
取证方式为 **HTTP 客户端逐端点直调**（`POST /api/v1/auth/sessions` 取 `access_token` 后带
`Authorization: Bearer`）。**未使用浏览器**（故界面渲染层未在真机走查，见下方「未验证」）。
本租户 `wiring-evidence` 的数字员工目录与岗位目录**均为空**（见下），因此**条目级字段形状未被真机观测到**。

**逐端点实测**：

| 端点 / 场景 | 实测 |
| --- | --- |
| `POST /auth/sessions`（超管 / 员工） | `200`；键 `access_token / token_type / expires_in / tenant_id / user_id / role / scope`；`expires_in = 900` |
| `GET /workforce/agents`（超管，无参） | `200` `{"items":[],"total":0,"limit":50,"offset":0}`（本租户目录为空） |
| `GET /workforce/agents?status=active&limit=1&offset=0` | `200` `{"items":[],"total":0,"limit":1,"offset":0}`（`limit` / `offset` 原样回显） |
| `GET /workforce/agents?role_key=nosuch-role` | `200` + 空列表（**未知 `role_key` 不报错**） |
| `GET /workforce/agents?keyword=zzz&created_by=zzz` | `200` + 与无参**完全相同**的结果 ⇒ **未知查询参数被忽略**（非 422、非筛选） |
| `GET /workforce/agents?status=draft` | `422` `{"detail":"状态只能是 active 或 disabled"}`（**字符串** ⇒ 请求层会采用该文案） |
| `GET /workforce/agents?limit=0` / `?limit=201` | `422`；`detail` 是**数组**（FastAPI 校验结构）⇒ 请求层 `safeDetail` 只接受字符串，界面回落本地固定文案「请求参数不合法，已拒绝。」 |
| `GET /workforce/agents`（匿名） | `401` `{"detail":"缺少登录身份信息"}` |
| `GET /workforce/agents`（员工令牌） | `403` `{"detail":"只有超级管理员可以管理岗位与数字员工目录"}` |
| `GET /workforce/roles` / `/roster` / `/candidates`（超管） | 分别 `200`：`{items:[],total,limit,offset}` / `{items:[],total}` / `{roles:[],agents:[]}`（**均空**） |
| 同上（员工令牌） | 均 `403`（同一条 detail） |
| `GET /workforce/agents/stats` | **`405` `{"detail":"Method Not Allowed"}`** ⇒ **无聚合统计接口**（该路径被 `PATCH .../{agent_key}` 的路由匹配） |
| `POST /workforce/agents`（`{}`） | `422`（**端点存在**；缺必填字段） |
| `POST /workforce/agents`（合法形状，`role_key=ops`） | `409` `{"detail":"岗位不存在或不属于本租户"}`（岗位目录为空 ⇒ **未写入任何数据**） |
| `POST /workforce/agents`（员工令牌） | `422`（先于鉴权落到请求体校验） |
| `PATCH /workforce/agents/{不存在}`（`{}`） | `404` `{"detail":"no-such"}`（**把标识原样回显**；短且干净 ⇒ 请求层会采用它作为文案） |
| `PATCH /workforce/agents/{不存在}`（`{"agent_key":"x"}`） | `422`，`detail` 为数组，`type = extra_forbidden`（**身份不可改**） |
| `PATCH /workforce/agents/{不存在}`（`{"status":"bogus"}`） | `422` |
| `PATCH /workforce/agents/x`（员工令牌） | `403` |
| `GET /workforce/agents/{不存在}/config` | `404` |

**落库核对**：上述探针**没有产生任何写入**（创建被 `409` 拦截在岗位校验；`PATCH` 全部命中不存在的标识）；
`workbench_digital_employees` 记录数在本批取证前后均为 **0**（由列表接口 `total = 0` 佐证）。

**未验证（不得读成已验）**：
① **条目级字段形状未在真机观测**：本租户目录为空（`total = 0`），`DigitalEmployeeView` 的 8 个键只经模型定义核对，**未经真实响应体核对**；
② **写入成功路径未验证**：无对象可改（目录为空），且不新建数据以免污染测试库 ⇒ `PATCH` 的 2xx 响应形状与 `written = true` 分支**只有单测覆盖**；
③ **界面渲染层未在真机走查**（本批未起浏览器）：生产构建产物与真实后端的联调表现（403 无权限态、空态、指标卡"未验证"）只有单测与构建产物 grep 覆盖；
④ 未测 `429` 限流、令牌自然过期（900s）、并发与大数据量（`limit` 上限 200 的截断只有单测）；
⑤ 未覆盖员工侧「我创建的 ∪ 共享给我的」语义 —— **后端本就没有该口径**，本批按管理目录接入并让非超管走无权限态。