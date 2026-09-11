# 运行终态落盘与运行结果通知设计 · 口径（已确认）

> **状态**：**口径已确认**（§11 决策表四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1064 项测试通过，CI 已接入并实跑通过）

## 1. 目标与非目标

**目标**：让每一次运行都有**可信的终态记录**，并让等待结果的人在运行失败/取消时收到站内通知。

当前 `RunMetricsService.record_state` 全仓只有一处调用（`app/planner/service.py:150`），写的是**启动瞬间**的快照；运行的状态变化既不回写记录，也无法产生 `failed`。结果是 `GET /api/v1/metrics/summary` 的完成率/时延建立在失真的样本上，且上一批站内通知的 E5（运行失败）没有数据源。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 带 `requires_approval` 步骤的审批决议流程 | 需要「决议 → 恢复执行 → 终态」一整套新流程，规模独立；本轮只**登记缺口**（§9） |
| 改动指标聚合算法（`summary` 的公式） | 本轮只保证**样本可信**，不动口径 |
| 运行失败原因的自由文本落库 | 自由文本可能夹带客户原文/凭据；只存受控枚举，细节仍由 `/runs/{id}/events` 暴露 |
| Web Push / 邮件 / 短信 | 外部依赖，已登记为阻塞项 |

## 2. 事实核查（生成本设计时实际读码确认，非凭印象）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | `POST /api/v1/tasks/{task_id}/runs` 直接启动的运行**完全不写运行记录** | `app/main.py:939-949` |
| 2 | `pause_run` / `resume_run` / `cancel_run` 只改内存状态，**从不回写运行记录** | `app/runtime/mock.py:47-64` |
| 3 | `failed` 状态**从未产生**：Mock 仅在有审批步骤时停在 `running`，其余直接 `completed` | `app/runtime/mock.py:18-35` |
| 4 | `record_state` 每次都以 `now` 作 `started_at`，**回写会重置启动时间** | `app/runtime/run_metrics.py:30-55` |
| 5 | 运行记录**没有结束原因字段** | `migrations/013_run_records.sql` |

## 3. 数据模型（迁移 `020_run_finish_reason.sql`）

```sql
ALTER TABLE workbench_run_records ADD COLUMN IF NOT EXISTS finish_reason TEXT;
```

- 只加**一个可空文本列**，历史行保持 `NULL`（不影响既有查询与聚合）。
- 不建索引：现有查询按 `tenant_id/task_id/runtime_key` 过滤，不按原因过滤。
- 同步登记 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS`（否则 `test_staging_assets.py` 失败）。

## 4. 结束原因（受控枚举，不含自由文本）

`app/runtime/records.py` 新增：

| 枚举 | 字面量 | 触发状态 |
| --- | --- | --- |
| `FinishReason.RUN_COMPLETED` | `run_completed` | `completed` |
| `FinishReason.CANCELLED_BY_USER` | `cancelled_by_user` | `cancelled` |
| `FinishReason.STEP_FAILED` | `step_failed` | `failed` |

**一致性约束**：`finish_reason` 由运行状态**单向推导**（`status → finish_reason`），非终态一律为 `None`。这样状态与原因不可能互相漂移；将来新增原因（如 `timeout`）只需扩枚举与映射表，不改表结构。

## 5. Mock 运行时的确定性失败约定

约定：`plan.steps[].tool` 以 **`fail.`** 前缀开头即触发失败（仅 Mock 运行时行为，真实适配器不受影响；`fail.` 不与任何既有工具名冲突）。

失败步骤的行为：

1. 发 `step.started` 事件 → `tool_calls += 1`（**不计入** `successful_tools`）
2. 发 `tool.result` 事件，`status="error"`
3. 状态置 `failed`，发 `run.failed` 事件（payload 含 `step_id` / `tool` / `reason="tool_error"`）
4. **立即停止**，不再执行后续步骤，不再置 `completed`

判定顺序：`fail.` 前缀检查**先于** `requires_approval`，保证失败可确定性复现（不受步骤 kind 影响）。

## 6. 运行记录的单一写入口

把「运行状态 → 运行记录」的同步收敛到 `RuntimeService`（它已持有 `task_store` 与状态存储）：

| 动作 | 记录写入 |
| --- | --- |
| `RuntimeService.start(..., proposal_id=None)` | 启动后写一条（含终态：Mock 无审批步骤时即为 `completed`/`failed`） |
| `RuntimeService.pause(actor, run_id, reason)` | 委托适配器后回写（`paused`，`finished_at` 清空） |
| `RuntimeService.resume(actor, run_id)` | 委托适配器后回写（`running`，`finished_at` 清空） |
| `RuntimeService.cancel(actor, run_id, reason)` | 委托适配器后回写（`cancelled` + `cancelled_by_user` + `finished_at`） |

**回写保留语义**（修正事实 4）：`record_state` 改为**幂等合并**——已有记录时保留原 `started_at`；本次 `proposal_id` 为空时保留原值。缺一条，`PlannerService` 的后续写入就会把启动时间重置。

**连带影响（必须如实说明）**：`RuntimeService.start` 也被 `ContentService`（内容生成）调用，因此**内容生成产生的运行也会进入运行记录**。这是口径变完整的正面效果，但确实扩大了指标样本范围。

`PlannerService.start_run` 不再自行写记录，改为把 `proposal_id` 传给 `runtime_service.start(...)`，保持**只有一个写入者**。

## 7. 接口影响（须同步 `docs/api-contract.md`）

- `GET /api/v1/runs/{run_id}/metrics`：响应新增 `finish_reason`（`string | null`）。
- 路径、状态码、权限均不变；`GET /api/v1/metrics/summary` 不变。
- `POST /api/v1/tasks/{task_id}/runs`、`/runs/{run_id}/pause|resume|cancel` 的路径与响应不变（副作用变得完整）。

## 8. 运行结果通知（复用既有收件箱）

| # | 事件 | 触发点 | 接收人 | kind |
| --- | --- | --- | --- | --- |
| E5 | 运行**失败** | 启动/取消后记录为 `failed` | 任务创建人 `task.created_by` | `run.failed` |
| E8 | 运行**被取消** | 取消后记录为 `cancelled` | 任务创建人 `task.created_by` | `run.cancelled` |

- 文案（固定模板）：`run.failed` → 「你的任务运行失败，请查看运行详情」；`run.cancelled` → 「你的任务运行已取消」。
- `target_type="run"`、`target_id=run_id`，供客户端跳转。
- 接收人**必须反查**：`RunRecord` 无 `user_id`，只能经 `task_id → task.created_by`。任务不存在或不可见时**跳过通知并写审计** `run.notify_skipped`（detail 仅 `kind` 与 `reason="task_unavailable"`），不猜接收人。
- 挂钩位置：**API 路由层**（与既有 E1–E4、E6 的口径一致，`app/main.py`）；通知写入失败仍由 `InboxService` 降级为 `inbox.write_failed` 审计，不阻断业务。
- **取消也通知**：取消可能由他人（CEO/超管）发起，任务创建人需要知道自己的运行被停了。

## 9. 已知限制（实现后需如实登记）

1. **带审批步骤的运行永久停在 `running`**：无审批决议流程，本轮不修（已登记为缺口）。
2. 终态通知只在**API 路由层**挂钩：若将来出现非路由入口（如 Worker 触发的运行），需另接。
3. `finish_reason` 是**受控枚举**，不含具体失败步骤；定位细节仍需查 `/runs/{id}/events`。
4. 内容生成运行进入指标样本（见 §6 连带影响），未做来源区分字段。

## 10. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 指标服务 | `finish_reason` 三态映射；非终态为 `None`；**回写保留 `started_at` 与 `proposal_id`**；`finished_at` 在暂停/恢复后清空 |
| Mock 运行时 | `fail.` 工具触发 `failed` + 停止后续步骤 + `successful_tools` 不计；正常路径不受影响 |
| 运行时服务 | `start` / `pause` / `resume` / `cancel` 各自回写记录；`run_metrics=None` 时行为与旧版一致（不报错） |
| 仓储 | PostgreSQL 双实现覆盖 `finish_reason` 列的读写（假连接断言 SQL） |
| 接口 | 直启运行的 `GET /runs/{id}/metrics` 可见；取消后 `status=cancelled`、`finish_reason=cancelled_by_user`、`finished_at` 非空 |
| 通知 | 失败/取消各写一条 `run.failed` / `run.cancelled`；他人不可见；任务不可见时跳过并写 `run.notify_skipped` |
| 契约守护 | 契约覆盖（`test_api_contract_coverage.py`）、迁移清单一致（`test_staging_assets.py`）、审计动作计数同步 |

## 11. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 是否新增「结束原因」字段 | **新增**（迁移 020，受控枚举） |
| D2 | 失败路径与通知范围 | **新增 `fail.` 确定性失败路径 + 失败与取消都通知** |
| D3 | 带审批步骤的「永久 running」 | **不处理，登记缺口** |
| D4 | 直接启动的运行是否纳入记录 | **纳入** |

## 12. 落地清单

1. 迁移 `020_run_finish_reason.sql` + `.env.staging.example` 登记。
2. `app/runtime/records.py`：`FinishReason` 枚举 + `RunRecord.finish_reason` + 双仓储读写。
3. `app/runtime/run_metrics.py`：`record_state` 合并语义 + `finish_reason` 推导。
4. `app/runtime/mock.py`：`fail.` 失败路径。
5. `app/runtime/service.py`：注入 `run_metrics`，新增 `pause` / `resume` / `cancel`，`start` 支持 `proposal_id`。
6. `app/planner/service.py`：改传 `proposal_id`，移除自行写记录。
7. `app/inbox.py`：新增 `run.failed` / `run.cancelled` 两个 kind 与文案。
8. `app/audit/models.py`：新增 `run.notify_skipped`。
9. `app/bootstrap.py`：`build_runtime_service` 支持注入 `run_metrics`；`app/main.py` 装配顺序调整 + 路由改用 `runtime_service.pause/resume/cancel` + 终态通知钩子。
10. `docs/api-contract.md`（metrics 新增字段、收件箱 kind 由 7 个变 9 个）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步。
11. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
