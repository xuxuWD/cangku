# 「我的工作台」界面接口契约（第 3 轮）

> 状态：**草案 v1 · 2026-09-19**（第 3 轮前端交付物）。**范围**：只声明本轮 UI 所需的**最小接口集**。
> 与 `docs/api-contract.md`（后端契约真源）的关系：**只引用、不修改**；已存在的接口按其原文口径复用，
> 未定义的接口在本文件**显式标为「未定义」**。字段名与 `src/features/myWorkbench/types.ts` **逐字一致**。

## 1. 待办（TodoPanel）· 复用既有接口

| 方法 | 路径 | 请求参数 | 分页 | 需要的角色 |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/approvals/pending` | `limit`（1–200，默认 50） | 仅 `limit` 截断 | 登录即可；非审批角色 `200` + 空列表 |
| GET | `/api/v1/inbox` | `unread_only`（默认 false）、`limit`（1–200，默认 50） | 仅 `limit` 截断 | 登录（只返回本人通知） |

响应：`/approvals/pending` → `{ items[]: { kind, target_id, title, requested_by, created_at, detail }, counts{} }`；
`/inbox` → `{ items[]: { inbox_id, kind, title, target_type, target_id, target_conversation_id, target_approval_id, created_at, read_at }, unread_count }`。
错误码：`401` 未认证；`422` `limit` 越界；审批聚合对非审批角色**不报 403**（返回空列表）。

字段 ↔ 卡片（`TodoItem`）：

| 契约字段 | 卡片位置 |
| --- | --- |
| `kind` | 类型标签（`StatusTag`；受控映射 `TODO_KIND_LABEL` / `TODO_KIND_TONE`） |
| `title` | 标题列 |
| `created_at` | 时间列（展示层格式化为 `YYYY-MM-DD HH:mm`） |
| `target_type` / `target_id` | "查看"跳转占位（本轮不接路由，只回调；同时是行键的一部分） |

前端归一化字段：`source`（`approval` | `notification`）—— 合并两个来源时判别用；`kind` 的 `notification_result` 是
`/inbox` 结果类通知在界面的归一化取值（后端原值为 `task.approved` / `run.failed` 等十取值）。

## 2. 最近使用（RecentPanel）· 会话复用既有接口；**运行列表未定义**

| 方法 | 路径 | 请求参数 | 分页 | 需要的角色 |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/conversations` | `status`（可选）、`limit`（1–200，默认 50）、`offset`（≥0，默认 0） | `limit` + `offset` + `total` | 登录；范围 = 本人 ∪ 成员 |
| GET | `/api/v1/runs` | — | — | **未定义：后端没有运行列表接口**（只有 `/runs/{run_id}/…` 单运行接口） |

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
后端无此实体、无接口。可用性由 `src/app/session.tsx` 的**本地能力桩**判定：`capability = null` 对所有角色可用，
管理类入口需要 `agent.manage` / `permission.manage`。接线后应由服务端下发可用入口（本轮**不假设**其字段）。

`QuickActionItem` 的字段，**逐个点名**：`key`（受控枚举 `QuickActionKey`）、`label`（按钮文案）、
`capability`（`Capability | null`）、`kind`（`'common' | 'admin'`）。**没有** `url` / `route` 字段（本轮不接路由）。

## 5. 通用口径

- 认证与越权：全部接口需登录（未认证 `401`）；越权 `403`；跨租户 / 不可见一律 `404`（不泄露存在性）。
- 错误码汇总：`401` 未认证 / `403` 越权 / `404` 不可见 / `422` 参数非法 / `429` 限流 / `5xx` 服务端。
- 前端取数：`services/myWorkbenchService.ts` 是**唯一接线点**。`mode = 'mock'`（默认）返回带 `sample: true` 的样例数据，
  界面必须显示「示例数据（未接后端）」；`mode = 'http'` **抛"尚未接入"错误**（不静默返回空数组）；
  `forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态（`panelStateOfError`）。
- 敏感信息：样例数据为虚构内容，不含手机号 / 用户 ID / 租户 ID / 密钥（有自检用例）。