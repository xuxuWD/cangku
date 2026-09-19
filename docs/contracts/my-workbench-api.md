# 「我的工作台」界面接口契约（第 3 轮 · 第 6 轮接线批 1 回写）

> 状态：**v2 · 2026-09-19**（第 3 轮草案 + 第 6 轮「接线批 1」差异回写：待办已接真接口）。
> **范围**：只声明本轮 UI 所需的**最小接口集**。
> 与 `docs/api-contract.md`（后端契约真源）的关系：**只引用、不修改**；已存在的接口按其原文口径复用，
> 未定义的接口在本文件**显式标为「未定义」**。字段名与 `src/features/myWorkbench/types.ts` **逐字一致**。
>
> **第 6 轮差异清单（本文件即回写结果）**：① 待办合并口径 = **未读站内通知 + 全部待审批**（见 §1）；
> ② 新增「标记已读」端点；③ `TodoItem` 新增 `inbox_id`；④ `SamplePayload.sample` 由字面量 `true` 改为 `boolean`
> （真实数据必须为 `false`）；⑤ 服务层模式解析规则改为「显式变量 > 开发期 mock > 生产 http」（见 §5）；
> ⑥ 审批 `kind` 增加 `account_registration`，并新增未知取值的兜底 `other`；⑦ 快捷入口能力来源改为服务端角色映射（见 §4）；
> ⑧ 「最近使用」「日程」本批**仍未接线**（§2 / §3 结论不变）。

## 1. 待办（TodoPanel）· 复用既有接口（**本批已接线**）

| 方法 | 路径 | 请求参数 | 分页 | 需要的角色 |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/approvals/pending` | `limit`（1–200，默认 50） | 仅 `limit` 截断 | 登录即可；非审批角色 `200` + 空列表 |
| GET | `/api/v1/inbox` | `unread_only=true`、`limit`（1–200，默认 50） | 仅 `limit` 截断 | 登录（只返回本人通知） |
| POST | `/api/v1/inbox/{inbox_id}/read` | 路径参数 `inbox_id` | — | 登录（只允许本人通知；他人 / 跨租户 `404`） |

**合并口径（第 6 轮定稿）**：待办 = `/inbox?unread_only=true`（未读通知）∪ `/approvals/pending`（待审批），
按 `created_at` 倒序合并后取前 `limit`（前端 `TODO_LIMIT = 50`）。两个请求用 `Promise.all` 并发，
**任一失败即整体失败**（少一半待办比"加载失败"更危险）；成功时 `sample = false`。

响应：`/approvals/pending` → `{ items[]: { kind, target_id, title, requested_by, created_at, detail }, counts{} }`；
`/inbox` → `{ items[]: { inbox_id, kind, title, target_type, target_id, target_conversation_id, target_approval_id, created_at, read_at }, unread_count }`；
`/inbox/{id}/read` → 单条 `InboxItemView`（重复标记幂等）。
错误码：`401` 未认证；`404` 通知不存在 / 不可见；`422` `limit` 越界；审批聚合对非审批角色**不报 403**（返回空列表）。

字段 ↔ 卡片（`TodoItem`）：

| 契约字段 | 卡片位置 |
| --- | --- |
| `kind` | 类型标签（`StatusTag`；受控映射 `TODO_KIND_LABEL` / `TODO_KIND_TONE`） |
| `title` | 标题列 |
| `created_at` | 时间列（展示层格式化为 `YYYY-MM-DD HH:mm`） |
| `target_type` / `target_id` | "查看"跳转占位（本轮不接路由，只回调；同时是行键的一部分） |
| `inbox_id` | 「标记已读」按钮的可用性：**非空才可标记**；审批类为 `null` ⇒ 按钮禁用并给出原因（不静默隐藏） |

前端归一化字段：`source`（`approval` | `notification`）—— 合并两个来源时判别用；`kind` 的取值为
后端 `/approvals/pending` 的 `kind` **原样**（含 `account_registration`）+ `/inbox` 归一化出的 `notification_result`
+ 未知取值的兜底 `other`（后端将来新增类型时如实显示"其他"，**不误标**成已知类型）。

## 2. 最近使用（RecentPanel）· 会话复用既有接口；**运行列表未定义**（本批仍未接线）

| 方法 | 路径 | 请求参数 | 分页 | 需要的角色 |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/conversations` | `status`（可选）、`limit`（1–200，默认 50）、`offset`（≥0，默认 0） | `limit` + `offset` + `total` | 登录；范围 = 本人 ∪ 成员 |
| GET | `/api/v1/runs` | — | — | **未定义：后端没有运行列表接口**（只有 `/runs/{run_id}/…` 单运行接口） |

**本批结论**：`mode = 'http'` 时本块**如实抛 `not_connected`**（文案 `RECENT_NOTE`），
**不返回空数组**、也不显示"暂无最近使用记录"（空数组会被读成"真的没有内容"）。接线见后续批次。

字段 ↔ 卡片（`RecentItem`）：`title` → 行标题；`updated_at` → "最近更新"；`kind` → 类型标签（会话 / 运行）。
归一化：`target_id` ← `conversation_id`（会话，既有字段）/ `run_id`（运行）；`updated_at` ← `updated_at`（会话，既有字段）/
`finished_at`（运行，**其列表接口未定义，样例数据无对应接口可依**）。

## 3. 日程（SchedulePanel）· **无后端实体（未定义接口）**

**明确结论：后端没有日程 / 日历实体，接口未定义。** 本轮 UI **固定渲染「尚未接入」**，
**不展示任何日期 / 会议 / 时间条目**，也**不声明任何日程字段**（避免"先编字段再补后端"）。
归属可追溯：`docs/contracts/adr.md` §「明确后置」—— 员工首页四件事（WH-01~04：待办/日程/最近/便捷）⇒ 后续批次。

`ScheduleAvailability` 的字段只有两个，**逐个点名**：`backend_entity`（字面量 `'absent'`，类型层面锁死，塞不进任何日程条目）、
`note`（界面固定文案，含「尚未接入」字样，含"后端暂无日程实体"结论）。**没有** `items` / `start_at` / `end_at` 等字段。

## 4. 快捷入口（QuickActions）· **无后端实体（前端静态目录）**

入口目录为前端静态定义（`src/features/myWorkbench/services/myWorkbenchService.ts` 的 `QUICK_ACTIONS`），
后端无此实体、无接口。可用性由 `src/app/session.tsx` 的 `ROLE_CAPABILITIES`（**服务端角色 → 能力**的映射）判定：
`capability = null` 对所有已登录角色可用；管理类入口需要 `agent.manage` / `permission.manage`。
第 6 轮起角色取值来自登录响应（`employee / department_lead / ceo / super_admin / customer_admin`），
映射关系为 `super_admin` 全量、`ceo` = `audit.view` + `data.export`、`department_lead` = `data.export`、
`employee` / `customer_admin` 无管理能力。**这只是界面呈现**（决定入口显不显示、给不给"无权限"说明），
真正的安全边界在服务端；接线后应由服务端下发可用入口（本轮**不假设**其字段）。

`QuickActionItem` 的字段，**逐个点名**：`key`（受控枚举 `QuickActionKey`）、`label`（按钮文案）、
`capability`（`Capability | null`）、`kind`（`'common' | 'admin'`）。**没有** `url` / `route` 字段（本轮不接路由）。

## 5. 通用口径（第 6 轮接线批 1 更新）

- **认证**：登录 `POST /api/v1/auth/sessions`（请求体 `{ phone, password, totp_code? }`，后端 `extra="forbid"`；
  响应 `{ access_token, token_type, expires_in, tenant_id, user_id, role, scope }`，**无展示名**）；登出 `POST /api/v1/auth/logout`（204）。
  令牌只放在 `sessionStorage`（键 `workbench.token`），**只进 `Authorization: Bearer` 头**，不进 URL / localStorage / 日志。
- **越权与可见性**：全部接口需登录（未认证 `401`）；越权 `403`；跨租户 / 不可见一律 `404`（不泄露存在性）。
- **错误码汇总**：`401` 未认证 / `403` 越权 / `404` 不可见 / `409` 冲突 / `422` 参数非法 / `429` 限流 / `503` 服务未就绪 / `5xx` 服务端。
  文案优先取服务端 `detail`，但**只接受"短且干净"的字符串**（堆栈 / SQL / 数据库驱动原文 / 内部路径一律丢弃，回落本地固定文案）。
- **前端取数**：`services/myWorkbenchService.ts` 是**唯一接线点**（页面与组件都不认识 URL）；HTTP 只走 `src/api/client.ts`。
  模式解析：`VITE_WORKBENCH_API_MODE`（`mock` | `http`）> 开发期默认 `mock` > **生产默认 `http`**（生产不允许回落到样例数据）。
- **样例标记**：`SamplePayload<T>.sample` 为 `boolean`；`true` = 开发期样例（界面必须显示「示例数据（未接后端）」），
  `false` = 后端真实数据；**禁止**把真实数据标成 sample，反之亦然。
- **前端状态**：`forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态（`panelStateOfError`）；
  `401` 由请求层统一清会话并回到登录页，**不做静默重试**。
- **敏感信息**：样例数据为虚构内容，不含手机号 / 用户 ID / 租户 ID / 密钥（有自检用例）。

## 6. 真机取证记录（2026-09-19 · 第 6 轮接线批 1）

**拓扑（据实登记）**：本机 `uvicorn app.main:app`（**跑的是工作树代码**，不是镜像）连**真库**
`wb-test-postgres-1:55433/workbench_test`（`WORKBENCH_STORAGE_BACKEND=postgres`）+ Redis 隔离 db5；
`WORKBENCH_REQUIRE_ADMIN_TOTP=false` 属**取证拓扑配置**（免动态验证码），**不是生产口径**。
前端侧用**生产构建产物**（`VITE_API_BASE_URL` 指向该 API、`VITE_WORKBENCH_API_MODE=http`）经真浏览器走查。

**实测（与上文契约逐条对齐）**：

| 项 | 实测结果 |
| --- | --- |
| `POST /auth/sessions` | `200`；键恰为 `access_token / token_type / expires_in / tenant_id / user_id / role / scope`（**无展示名**）；`expires_in = 900` |
| `POST /auth/logout` | `204`；**同一令牌随后 `401`**（服务端撤销真生效，不依赖前端清本地）。⚠️ 自动化浏览器会把该 **204 响应**标成 `net::ERR_ABORTED` 并打一条 console error —— **对照实验定性为环境上报行为，非应用缺陷**：同一 URL 用**不带 signal 的裸 `fetch`** 同样被标，而同样条件下返回 `401` 时**不标**；服务端访问日志两次均记 `204 No Content`（详见本文件末节） |
| `GET /approvals/pending` | `200` `{items, counts}`；`counts` 实测键 = `task_approval / plan_proposal / run_approval / account_registration / `**`total`**（多一个 `total`；前端**不读** `counts`，无影响） |
| 待审批条目 | `{kind, target_id, title, requested_by, created_at, detail}`；`requested_by` 实测 `null`；`account_registration` 的 `title` = **掩码手机号**（`139****0002`），`detail` = `{position}` |
| `GET /inbox?unread_only=true` | `200` `{items, unread_count}`；条目 9 键与 §1 一致；`target_type` / `target_id` / `target_conversation_id` / `target_approval_id` 实测**均可为 `null`** |
| `unread_count` | **本人未读总数（与筛选无关）**：标记已读后同请求 `items = []` 且 `unread_count = 0`；不带筛选时同一条 `read_at` 非空 |
| `POST /inbox/{id}/read` | `200` 返回**完整 `InboxItemView`**（`read_at` 由 `null` → 时间戳）；他人 / 不存在的 id ⇒ `404` |
| 未认证 / 伪造令牌 | 均 `401`，文案 `{"detail":"缺少登录身份信息"}`（短且干净 ⇒ 请求层会采用它） |
| 越权 | 员工令牌访问 `GET /auth/registrations` ⇒ `403` |
| 中文编码 | 库内 `title` 的 UTF-8 字节与 `app/inbox.py` 固定模板**逐字节一致**（无乱码；契约不依赖前端转码） |
| `GET /collaboration-dynamics` | `200` **裸数组**（非信封）——本批**未接线**，登记给「团队协作」批次 |

**落库核对（不只看返回码）**：`workbench_accounts` 两条（`super_admin` / `employee`，租户 `wiring-evidence`，均 `approved`）；
`workbench_inbox_items` 两条（一条 `read_at` 非空）；审计面：注册 / 审批 / 登录在 `workbench_audit_log` 有行，
**站内通知的写入与已读不写审计**（`app/inbox.py::notify` 仅在**写失败**时记 `inbox.write.failed`）——属**既有口径**，非本批引入。

**未验证（不得读成已验）**：① 未覆盖任务 / 计划 / 运行三类审批的**产生链路**（只造了账号注册一类）；
② `429`（登录限流）与令牌自然过期（900s 到期）的**真机**表现未测；③ 拓扑是本机 Windows + 单进程 uvicorn + 本机测试库，
**非 staging / 生产**；④ 未测并发与大数据量（`limit` 上限 200 的截断行为只有单测覆盖）。

## 7. 走查发现的缺陷与处置（2026-09-19 · 批 1 收口）

**缺陷（已修）：登出失败时的"如实告知"实际不可见。** 原实现把「服务端会话撤销失败」的 Alert 渲染在**已登录分支**里，
而该警告产生的同一刻 `signOut()` 已把壳层切到登录页 ⇒ 这条告知**永远看不到**（等于没告知，与"不能假装服务端也退干净了"冲突）。
**修法**：`LoginPage` 新增可选属性 `externalNotice`，壳层在未认证分支传 `logoutWarning`；已登录分支里那条不可达的旧 Alert 删除。
**真机验证（生产构建产物 + 真浏览器）**：① 篡改令牌后点「退出登录」⇒ 请求 `401` ⇒ 登录页出现 **warning** Alere（原文
`已退出本地登录，但服务端会话撤销失败：该登录凭证可能仍然有效，请关闭浏览器标签页。`），且 `sessionStorage` 令牌为 `null`；
② 对照组（正常登出 `204`）⇒ **不出现**该提示（不是无脑常显）。
用例锁定：`src/app/AppShell.test.tsx` 两条（成功无警告 / 失败必显示）；**反假已做**：把壳层改回不传 `externalNotice`
⇒ 失败分支用例 1 failed，还原后全绿。

**现象（已定性为环境，非应用缺陷）：204 响应被自动化浏览器标 `net::ERR_ABORTED`。** 同一自动化浏览器内三组对照：
裸 `fetch`（**不带 signal**）→ 返回 204 仍被标 + console error；裸 `fetch` + `signal`（10s 定时器未触发）→ 同样被标；
条件相同但返回 `401` → **不标**。⇒ 与 `src/api/client.ts` 的 `AbortController` 无关，触发条件锁定为「**204 空响应体**」；
新出现 console error 的调用栈指向自动化浏览器注入的 Electron 桥（`sandbox_bundle`），**不是应用 bundle**。
**未验证**：普通 Chrome / 真实用户侧是否同样如此（本次观测全在该自动化浏览器内）；其具体机制未做抓包级定位。