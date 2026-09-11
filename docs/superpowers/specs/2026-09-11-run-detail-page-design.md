# 运行详情页（管理台）设计 · 口径（已确认）

> **状态**：**口径已确认**（§9 四项均已定），进入实现。
> **日期**：2026-09-11　**基线**：`main`（后端 1099 项测试通过，CI 实跑通过）
> **性质**：**纯前端**（admin-web）+ 一处前端契约漂移修复与守护测试；**不改后端、不加迁移、不改 api-contract**。

## 1. 目标与非目标

**目标**：让已经做完的运行时能力**在界面上可见可用**——指标、事件时间线、审批决议。目前 `GET /runs/{id}/events`、`/metrics`、`/approvals` 三个接口在两端**都没有任何页面**，审批决议只能靠 curl。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 运行列表页 | 后端**没有**租户级运行索引，没有列表接口；硬做只能造假数据 |
| 暂停 / 恢复 / 取消按钮 | 本轮口径定为「只读 + 审批决议」；控制类动作风险与确认流程需单独口径 |
| 伴侣端同步做运行详情 | 口径定为仅管理台（手机端定位是审批助手，不适合展示指标与事件流） |
| 展示事件 payload 的原始 JSON | 只按**已知字段白名单**渲染，避免把适配器带出的意外内容透到界面 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 三个运行接口齐备且已在 `api-contract`：`/events`（403 同租户非本人 / 404 跨租户）、`/metrics`（404）、`/approvals`（404） | `app/main.py:987-1130` |
| 2 | 通知页**只对 `target_type==='task'` 可点击**，`run.*` 提醒点了没反应 | `admin-web/src/features/inbox/InboxPage.tsx:64-69` |
| 3 | 管理台无登录，身份取自 `VITE_TENANT_ID`/`VITE_USER_ID`/`VITE_USER_ROLE`（默认 `super_admin`） | `admin-web/src/features/inbox/api.ts:5-7` |
| 4 | **前端 kind 枚举已漂移**：两端都缺 `run.cancelled`、`run.approval_rejected`（后端 10 个 vs 前端 8 个），仅靠 `?? '通知'` 兜底 | `admin-web/src/features/inbox/types.ts`、`companion-pwa/src/features/inbox/types.ts` |
| 5 | 运行内审批**不收集驳回原因**（后端只存布尔与受控枚举）→ 页面无法展示理由 | `docs/api-contract.md` 运行章节 |

## 3. 路由与入口

- 新增视图 `run`，URL 形如 `?view=run&run=<run_id>`（支持直达与刷新）。
- `AppView` 联合类型增加 `'run'`；`navigate(view, taskId?, runId?)` 第三参数承载 runId。
- **侧栏不加运行入口**（无列表页可去），因此不会出现无法到达的导航项。
- **通知页入口**：`target_type === 'run'` 的提醒点击后跳转运行详情；`canOpen` 判定同步扩展。

## 4. 页面结构（`admin-web/src/features/runDetail/`）

镜像既有 feature 目录约定（`api.ts` / `types.ts` / `state.ts` / `XxxPage.tsx` / 测试），页面外壳复用 `AppShell` + 既有 CSS 类（`page-head` / `history-panel` / `status-badge` / `empty-state` / `loading-state` / `notice-error`）。

**四个数据源并发加载**（`Promise.allSettled`），**分区独立呈现**：某区失败只在该区显示错误与「重新尝试」，不影响其他区。

| 区块 | 数据源 | 展示 |
| --- | --- | --- |
| 概览 | `GET /api/v1/tasks/{task_id}` + `GET /runs/{run_id}/metrics` | 任务标题、责任状态徽标、`status` + `finish_reason` 中文标签、步数完成度、工具调用、延迟、起止时间 |
| 审批 | `GET /runs/{run_id}/approvals` | 每条：步骤/工具、状态徽标；`pending` 时给出「通过 / 驳回」按钮 |
| 事件时间线 | `GET /runs/{run_id}/events` | 按 `sequence` 升序：事件中文标签 + 已知字段白名单（`step_id`/`tool`/`status`/`reason`/`approval_id`/`approved`/`step_count`/`knowledge_hit`） |

**终态文案**：`run_completed`→已完成、`cancelled_by_user`→用户取消、`step_failed`→步骤失败、`approval_rejected`→审批被驳回；非终态显示 `running`→运行中、`paused`→已暂停。

## 5. 错误与状态码映射

| 后端 | 页面表现 |
| --- | --- |
| `401` | 「当前账号没有查看该运行的权限。」 |
| `403` | 直接展示后端文案（如「发起人不能审批自己发起的运行」） |
| `404` | 「运行不存在，或你没有权限查看。」（不泄露存在性） |
| `409` | 「该审批已决议」→ 自动重新拉取审批与指标 |
| 网络/5xx | 可重试提示 + 「重新尝试」按钮 |

## 6. 决议按钮规则（口径 D3）

- 仅当审批项 `status === 'pending'` 时渲染按钮。
- 若能取到任务且 `task.created_by === VITE_USER_ID`（默认 `admin`）→ **隐藏按钮**并标注「发起人不能审批自己发起的运行」。
- 其他情况保留按钮，**由后端真实状态码驱动文案**，前端不猜角色。
- 决议成功后刷新审批、指标与事件三个区块，并给出「已通过 / 已驳回」提示。

## 7. 前端契约漂移修复 + 守护

1. 两端 `InboxKind` 补 `run.cancelled`、`run.approval_rejected`，并补中文标签（「运行被取消」「运行审批被驳回」）。
2. 新增 Python 守护测试 `tests/test_frontend_inbox_kinds.py`：解析两端 `features/inbox/types.ts` 的 kind 联合，与 `app.inbox.InboxKind` 的取值集合比对，**不一致即失败**——防止同类漂移再次发生（与 `test_api_contract_coverage.py`、`test_frontend_dependency_pins.py` 同一思路）。

## 8. 测试计划

| 层次 | 覆盖 |
| --- | --- |
| api | 路径与查询参数正确；决议请求体 `{"approved": boolean}`；401/403/404/409 与网络错误映射为中文提示 |
| 页面 | 加载并展示指标/审批/事件；**自审时隐藏按钮**；决议成功后刷新；**某区失败不影响其他区**；空审批与空事件态 |
| 路由 | `?view=run&run=xxx` 直达渲染详情页；通知页 `run.*` 提醒可点击跳转 |
| 漂移守护 | 上述 Python 守护测试 |
| 现状回归 | `npm run test`、`npm run build`（含 `tsc -b` 类型检查）全绿 |

## 9. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 入口 | **通知跳转 + URL 直达**，不做列表页 |
| D2 | 页面能力 | **只读 + 审批决议**，不做暂停/恢复/取消 |
| D3 | 按钮可见性 | **自审隐藏 + 后端文案驱动** |
| D4 | 前端范围 | **仅管理台（admin-web）** |

## 10. 已知限制（实现后需如实登记）

1. **没有列表页**：只能经通知跳转或直接粘 URL，运行详情无法从侧栏进入（后端无列表接口）。
2. **看不到驳回原因**：后端不收集自由文本，页面只能显示「审批被驳回」。
3. 事件 payload 只渲染白名单字段，未知字段不展示（这是刻意的收敛，不是遗漏）。

## 11. 落地清单

1. `admin-web/src/features/runDetail/`：`types.ts` / `api.ts` / `state.ts` / `RunDetailPage.tsx` + `api.test.ts` / `RunDetailPage.test.tsx`。
2. `admin-web/src/app/AppShell.tsx`：`AppView` 增加 `'run'`。
3. `admin-web/src/app/App.tsx`：`view=run` 路由与 `navigate` 的 runId 支持。
4. `admin-web/src/features/inbox/InboxPage.tsx`：`run` 类提醒可点击跳转（新增 `onOpenRun`）。
5. `admin-web/src/features/inbox/types.ts`、`companion-pwa/src/features/inbox/types.ts`：补两个 kind 与标签。
6. `admin-web/src/styles/global.css`：新增样式（沿用既有命名风格）。
7. `tests/test_frontend_inbox_kinds.py`：漂移守护。
8. 文档：`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步（新增「管理台运行详情页」项与限制）。
