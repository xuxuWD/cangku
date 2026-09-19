# 「权限配置」界面接口契约（第 6 轮）

> 状态：**v1 · 2026-09-19**（第 6 轮交付物；**契约先行**——本文件落盘后再写码）。实施方案见
> [`permissions-config-plan.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permissions-config-plan.md)。
> **唯一权威在别处**：权限口径 = [`permission-matrix.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/permission-matrix.md)；
> 知识分级 = [`knowledge-acl.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/knowledge-acl.md)。
> 本文件只声明**界面所需的最小接口集**；与 `docs/api-contract.md`（后端契约真源）的关系是**只引用、不修改**。
> 字段名与 `src/features/permissions/types.ts` **逐字一致**（改一处必须同时改另一处）。
> 所有形状均为 **2026-09-19 真机实测**（本机工作树 `uvicorn` + 真库 `workbench_test`，非生产）。

## 1. 接口清单（实测）

| 方法 | 路径 | 请求 | 响应 | 角色要求（实测） |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/workforce/roles` | `status`（可选 `active`/`disabled`）、`limit`（1–200，默认 50）、`offset`（≥0） | `{ items: JobRole[], total, limit, offset }` | **仅 `super_admin`**（非超管 `403`） |
| GET | `/api/v1/knowledge-access/roles/{role_key}` | 路径参数 | `{ binding_type: "role", binding_key, knowledge_base_ids: string[] }` | 仅 `super_admin`（`403`） |
| PUT | `/api/v1/knowledge-access/roles/{role_key}` | `{ knowledge_base_ids: string[] }`（`extra="forbid"`、**≤100 项**） | 同 GET（写入后的实际值） | 同上；**未纳管标识 ⇒ `409`** |
| GET | `/api/v1/knowledge-access/agents/{agent_key}` | 路径参数 | `{ binding_type: "agent", binding_key, knowledge_base_ids: string[] }` | 同上 |
| PUT | `/api/v1/knowledge-access/agents/{agent_key}` | 同上 | 同上 | 同上 |
| GET | `/api/v1/knowledge-access/audits` | `limit`（1–500，默认 100） | **数组**：`{ tenant_id, binding_type, binding_key, old_knowledge_base_ids, new_knowledge_base_ids, actor_id, occurred_at }` | 仅 `super_admin`（`403`） |

`JobRole` 逐键点名：`role_key`（标识，**不可改**）、`name`（中文名）、`description`、`status`（受控枚举 `active` / `disabled`）、
`created_by`、`created_at`、`updated_at`（后三者可为 `null`）。

## 2. 错误码与界面处置（**实测原文**）

| 场景 | 状态码 | 服务端原文 | 界面处置 |
| --- | --- | --- | --- |
| 非超管读写 | `403` | `{"detail":"只有超级管理员可以调整知识库范围"}` | 整页**无权限态**（列表不渲染编辑控件）；操作时二次失败 ⇒ 就地 Alert |
| 写入未纳管标识 | `409` | `{"detail":"该标识尚未纳入目录，请先在「数字员工设置」中纳管"}` | 抽屉内 Alert + **不关闭抽屉、不假装成功**（服务端**零写入**，实测） |
| 请求体含未知字段 / 非法值 | `422` | `detail` 是**数组**（`extra_forbidden` 等） | `safeDetail` 只接受**字符串** ⇒ 落回本地固定文案，**绝不渲染原始校验 JSON** |
| 未登录 / 令牌失效 | `401` | — | 由统一请求层清会话并回登录页（批 1 口径） |

**顺序语义（实测）**：写路径**先判权限、后判目录** —— 员工对未纳管标识 PUT 得到的是 `403` 而不是 `409`。

## 3. 页面契约（三块，一页承载）

| 块 | 数据来源 | 交互 | 空态口径 |
| --- | --- | --- | --- |
| **角色知识范围** | `workforce/roles` + 每行 `knowledge-access/roles/{key}` | 行内「编辑范围」⇒ 抽屉（候选 + 手动录入）⇒ PUT ⇒ 刷新该行 | 目录里没有角色 ⇒ 「目录里还没有岗位；请先在「数字员工设置」中纳管」+ 说明（**不显示"0 条绑定"冒充内容**） |
| **数字员工知识范围** | `workforce/agents`（批 2 契约）+ `knowledge-access/agents/{key}` | 同上 | 同上（文案换成数字员工） |
| **最近变更** | `knowledge-access/audits?limit=20` | **只读**；`old → new` 两列 | 「暂无变更记录」（审计为空是真实语义，**不标成加载失败**） |

**四态**：加载 / 空 / 错误（可重试）/ 无权限；**无权限**用整页 `PermissionGuard` 呈现，**不渲染任何编辑控件**。

## 4. 候选知识库标识的来源（方案 A，已裁决 2026-09-19）

- **候选 = 所有已绑定标识的并集**（来自三个块的现有绑定），外加**手动录入**；
- 前端校验**只有**：非空、去重、**≤100 项**（服务端 `max_length=100`）；**服务端仍是唯一权威**（前端不预设合法性）；
- 界面必须写明：「候选来自现有绑定；**新库标识需手动录入**（后端暂无枚举接口，已登记）」。

## 5. 未定义 / 未接入（本模块**不做**）

| 事项 | 原因 |
| --- | --- |
| 知识库**枚举**接口 | 后端无此端点（`knowledge_base_ids` 是 WeKnora 侧标识）⇒ 见 §4 |
| 角色 / 数字员工的**创建与启停** | 属目录面（「数字员工设置」）⇒ 本页只消费目录状态 |
| 文档级四级 ACL（`knowledge-acl.md`） | 字段**未落库**（属 Schema 线），本轮不碰 |
| 只读权限矩阵页签 | 矩阵唯一权威是 `permission-matrix.md`，界面另绘必然漂移 |

## 6. 未验证（不得读成已验）

- **检索侧效果**：`POST /api/v1/knowledge/search` 需 WeKnora 配置（未配 ⇒ `503`）⇒
  "绑定后检索只返回该范围"**本机验不了**；本轮只验**绑定读写与闸门**。
- `workforce/roles` 与 `workforce/agents` 的**目录侧写入**（创建/启停）属批 2 与目录模块的验证范围，本模块不重复验。
- 本机拓扑（Windows + 单进程 uvicorn + 本机测试库）**非 staging / 生产**。
- **界面渲染层未在真机走查**（本轮按要求只做 API 层取证，浏览器走查由用户统一做）：
  三块布局 / 四态 / 抽屉交互 / 409 就地呈现只有单测与构建产物 grep 覆盖。
- **逐行取绑定的性能未压测**：目录无批量绑定接口 ⇒ 请求数 = `1 + 目录行数`（N+1）；
  本机目录只有 1 行，**未在"几十~上百行"下测过耗时与并发**（真实环境需再看，见 §8 取数口径）。
- **`PUT` 未纳入请求层受控枚举**：本模块在 service 内做了一次显式收窄（未改 `api/**`，见 §8）。
  若后续把 `PUT` 加入 `RequestOptions.method`，应把该收窄去掉（已在交付报告单列）。
- 未测 `429`、令牌自然过期、并发写同一标识（后端的幂等/并发语义未在本轮取证范围）。

## 7. 变更留痕

- 2026-09-19：v1 建立（第 6 轮方案确认后、写码前落盘）；形状来自真机实测。
- 2026-09-19：**实施后回写** —— 新增 §8「实施落地口径」与 §9「真机取证记录（2026-09-19 · 第 6 轮实施）」；
  §6 补齐未验证清单。**接口清单（§1）与错误码原文（§2）零变更**（实施未发现形状偏差）。

## 8. 实施落地口径（写码后回写）

| 项 | 落地口径 |
| --- | --- |
| 请求层 | 全部走 `src/api/client.ts`；写路径用 `PUT`（见上 §6 的收窄说明，未改 `api/**`） |
| 取数 | 目录 `limit=200&offset=0` 一次取满；**逐行** `GET` 该行绑定（后端无批量接口）⇒ 请求数 = `1 + 行数`；`total > items.length` 直接抛错（不展示残缺数据） |
| 行状态 | 未知 `status` 抛错（**不误标**成"已启用 / 已停用"）；绑定形状不符（缺 `knowledge_base_ids`）也抛错（**不默认成"未绑定"**） |
| 失败分类 | 读：`403 → forbidden`，其余 `failed`；写：`403 → forbidden`、`409 → conflict`、`422 → invalid`、其余 `failed` |
| 候选 | `collectCandidates` = 两块现有绑定 ∪ 变更记录 `old/new`，去重排序；界面允许手输；固定文案 `CANDIDATE_NOTE` |
| 前端校验 | 空项拒绝 / 去重 / **≤100**；**留空合法**（= 解除该对象全部绑定）——合法性一律以服务端为准 |
| 写成功 | 用**服务端回读值**提示（数量取 `binding.knowledge_base_ids.length`）+ `invalidateQueries` 刷新该块与变更记录 |
| 写失败 | 就地 Alert（服务端原文 + 「本次没有写入任何数据」），**不关闭抽屉、不假装成功** |
| 样例模式 | `written = false` 且 `binding = null`（**不伪造回读值**）；不触发刷新（没有可刷新的服务端变化） |
| 无权限 | 整页 `PermissionGuard`（能力 `permission.manage`）⇒ 不请求数据、不渲染任何编辑控件 |

## 9. 真机取证记录（2026-09-19 · 第 6 轮实施）

**拓扑**：`http://127.0.0.1:18112`（`uvicorn app.main:app`，**工作树代码**）+ 真库 `workbench_test`
（本机 Docker `wb-test-postgres-1:55433`）。HTTP 客户端直调（`POST /api/v1/auth/sessions` 取令牌，
超管账号与员工账号各一，**均为 136 号段**；令牌只存在于命令行内存，未落任何文件/日志）。**未使用浏览器**。

| 场景 | 实测 |
| --- | --- |
| ① 员工令牌 `PUT /knowledge-access/roles/evidence-ops` | **`403`** `{"detail":"只有超级管理员可以调整知识库范围"}` |
| ② 超管 `PUT` 未纳管 `key`（`evidence-ops`，目录中不存在） | **`409`** `{"detail":"该标识尚未纳入目录，请先在「数字员工设置」中纳管"}` ⇒ 查库 `workbench_knowledge_access_bindings` 中 `binding_key='evidence-ops'` **前后均为 0 行**（零写入） |
| ②′ 请求体多字段（`{"knowledge_base_ids":[...],"extra":1}`） | **`422`**，`detail` 是**数组**（`type = extra_forbidden`）⇒ 请求层 `safeDetail` 拒绝非字符串 ⇒ 界面回落**本地固定文案**（不渲染校验 JSON） |
| ③ 经目录纳管：`POST /api/v1/workforce/roles`（`role_key=evidence-ops`） | `201`（`status=active`） |
| ③′ 超管 `PUT` 绑定 `["kb-evidence-1","kb-evidence-2"]` | `200` `{"binding_type":"role","binding_key":"evidence-ops","knowledge_base_ids":["kb-evidence-1","kb-evidence-2"]}` |
| ③″ `GET` 回读 | `200`，与写入值**逐字一致** |
| ③‴ 查库核对 | `workbench_knowledge_access_bindings` 实际落库两行：`role|evidence-ops|kb-evidence-1`、`role|evidence-ops|kb-evidence-2` |
| ④ `GET /knowledge-access/audits?limit=20` | `200` 数组，含该条变更：`binding_type=role`、`binding_key=evidence-ops`、`old=[]`、`new=[kb-evidence-1,kb-evidence-2]`、`actor_id=acct-0ac0…`（不透明账号标识）、`occurred_at=2026-09-19T10:25:43Z` |
| ⑤ 清理 | `PUT {"knowledge_base_ids":[]}` ⇒ `200`（回读为空）；`PATCH /workforce/roles/evidence-ops {"status":"disabled"}` ⇒ `200`；查库：绑定 **0 行**、岗位行 `evidence-ops|disabled` |

**残留行清单（供裁决；后端无删除接口，本轮未物理删除）**：

| 表 | 残留 | 说明 |
| --- | --- | --- |
| `workbench_job_roles` | **1 行**（`role_key=evidence-ops`，`status=disabled`） | 取证③为"先纳管"所建；已停用（写入闸门对停用标识同样返回 `409`），绑定已清空 |
| `workbench_knowledge_access_audits` | **2 行**（`binding_key=evidence-ops`：绑定 + 解绑各一条） | **按要求不删**（审计只追加） |

> 本轮取证**未触碰**其它任何测试数据；未产生手机号/令牌/租户标识落盘。

### 9.1 浏览器真机走查（2026-09-19 · 由收口人执行，非子代理）

**拓扑**：生产构建产物（`VITE_API_BASE_URL` 指向本机工作树 API、`VITE_WORKBENCH_API_MODE=http`）经真浏览器操作；
账号为本轮取证账号（超管 / 员工，*136 号段*）。

| 检查 | 实测（页面原文） |
| --- | --- |
| 员工侧导航 | 仅 4 项（我的工作台 / 我的数字员工 / 知识库 / 团队协作），**无「权限配置」**；「我的工作台」的快捷入口区仍显示**禁用的**「权限配置」并给原因（批次 1 口径，非缺陷） |
| 页面骨架 | 标题「权限配置」；三块块标题 = 角色知识范围 / 数字员工知识范围 / 最近变更；说明条「已接入真实数据」+「…候选标识来自现有绑定，新库标识需手动录入（平台暂无可选清单）。」 |
| 角色块 | 列 = 岗位标识 / 名称 / 状态 / 知识范围 / 操作；1 行：`evidence-ops`、`证据运营（本轮取证）`、`已停用`、`尚未绑定任何知识库`、`编辑范围` |
| 员工块空态 | 「目录里还没有数字员工；请先在「数字员工设置」中纳管数字员工，再回到本页配置知识范围。」（**解释了为什么空**，非"0 条"） |
| 变更块 | 列 = 对象 / 变更前 / 变更后 / 操作者 / 时间；2 行（绑定 `[] → kb-evidence-1 kb-evidence-2`、解绑反向），与 §9 的 API 取证一致 |
| 编辑抽屉 | 标题「编辑知识范围：证据运营（本轮取证）」；候选**恰为** `kb-evidence-1` / `kb-evidence-2`（**无编造候选**）；可直接输入新标识；说明「候选来自现有绑定；新库标识需手动录入（平台暂无可选清单，已登记待补）。」；「留空表示解除该对象的全部绑定。」 |
| **写失败（409）** | 红色错误条：标题「未能保存：该标识尚未纳入目录，请先在「数字员工设置」中纳管」+ 描述「本次没有写入任何数据；…后重试。」；**抽屉保持打开、已填值保留**；全文**无**「已保存 / 成功」字样；后端确为 `PUT … → 409`（2 次尝试各一次），且**变更块行数/内容未变**（无乐观更新残留） |
| 取消路径 | 点「取消」先弹确认「放弃未保存的改动？」⇒ 放弃后数据与变更块**逐字未变** |
| Console | 无 JS 异常、无 unhandled rejection（409 被业务层正常捕获）；仅 3 条 `net::ERR_ABORTED`（页面重载 + 登出 204，**已定性为环境上报**，见 my-workbench-api.md §7） |

**未验证 / 待人工复核**（不得读成已验）：
1. **自动化点击下拉候选未被选中**（3 次尝试失败，hover 被拦；键盘输入 `kb-evidence-1` + 回车可正常选中）——**归因未定**：
   既可能是自动化环境（视口仅 552×489 + 内层滚动），也可能是真实交互问题 ⇒ **登记为待人工复核**，不判定为确证缺陷（组件选择逻辑有单测覆盖）。
2. 未逐字读取 `PUT` 请求体与 `409` 响应体（工具不提供 body；状态码取自 performance 资源条目）。
3. 未测「已停用角色」对其它取值（空值 / 其它标识）是否返回不同码值（本轮只测了 `kb-evidence-1`）。
4. 抽屉关闭后弹层容器内仍留有隐藏的确认框节点（无可见错误，记录备查）。