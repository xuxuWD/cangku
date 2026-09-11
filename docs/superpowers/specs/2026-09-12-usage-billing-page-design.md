# 用量与费用页设计 · 口径（已确认）

> **状态**：**口径已确认**（§3 三项决策已定），实现为**只读页面**，复用现有接口，**不改后端、无迁移**。
> **日期**：2026-09-12　**基线**：`main`（`8bc7e59`，后端 `pytest` exit=0，CI run `34631052968` 四个 job 全绿）
> **关联**：本文件同时修正 `docs/delivery-gates.md` 与 `docs/delivery-readiness-checklist.md` 里「模型与费用**无数据源**」这一**不准确**表述（见 §2）。

## 1. 目标与非目标

**目标**：把管理台侧栏的占位项做成真实的**只读「用量与费用」页**——展示本租户的**累计用量**与**累计费用**（数据来自既有 append-only 用量账本）。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| **模型清单 / 模型目录**（本期的另一半） | 模型侧**没有实体表、没有接口**：`ProviderModel` 是装配时由配置现造（`app/bootstrap.py:499-507`）。要落地必须定「配置即真源还是建表并改 `ModelGateway` 取数」，属**地基层面**变更（会同时动规划与内容两条取数链路），**需专项评审 + 单独立项** |
| 按时间 / 模型 / 任务的花费维度 | 账本只有 `units` 与 `cost_cents` 两列（`migrations/006`），**没有 `model_key` / `task_id` / 时间桶查询**；加维度＝加列或新表，且历史数据**无法回填** |
| 预算、告警、套餐额度与超额 | 属商业化 G0 的 `plan_versions` / `usage_ledger` 另一条线（见 `docs/delivery-readiness-checklist.md`），本期只做展示 |
| 冲正（reverse）入口 | 冲正是**写**操作，涉及金额纠错与审计，必须有独立口径；本期只读展示 |

## 2. 事实核查（实际读码 + 本机实测）

| # | 事实 | 依据 |
| --- | --- | --- |
| 1 | **费用侧有真实数据源**：`workbench_usage_ledger` 为**追加式**账本，含 `units`、`cost_cents`、`idempotency_key`、`reversal_of`、`reason`、`actor_id`、`occurred_at`；`(tenant_id, idempotency_key)` 唯一保证幂等，冲正写入一条负值记录 | `migrations/006_commercial_g0.sql:35-45`、`app/commercial/usage.py` |
| 2 | 现有聚合**只有两个租户级累计**：`total(units)` 与 `total_cost_cents` | `app/commercial/usage.py:59-65`、`:97-109` |
| 3 | 接口 `GET /api/v1/commercial/usage` → `{tenant_id, units, cost_cents}`；**不改一行即可复用** | `app/main.py:339-342`、`:691-704` |
| 4 | 权限：`super_admin`，或**本租户已登记的 `customer_admin`**；其他角色 `403`「只有客户管理员或超级管理员可以管理租户商业化设置」 | `app/main.py:410-415` |
| 5 | **本租户未在商业化模块登记时返回 `404`「租户不存在」**（先查租户再取用量） | `app/main.py:695-699` |
| 6 | **本机实测（memory/development）**：`usage` → `404 {'detail': '租户不存在'}`；`tenant` → `404`；`ceo` → `403` | 2026-09-12 进程内 TestClient 实测 |
| 7 | 模型侧：`ProviderModel` 只声明一个能力 `PLAN_GENERATION_CAPABILITY`，`sensitive_data` 取自 `planner_model_sensitive_data`；两套独立配置 `content_model_*` / `planner_model_*` | `app/bootstrap.py:487-507`、`app/settings.py:58-160` |
| 8 | 侧栏「模型与费用」**没有 view**（占位项，点击无反应）；无页面、无接口调用 | `admin-web/src/app/AppShell.tsx` |

**修正**：早前把「模型与费用」笼统记为「无数据源」是**不准确**的——**费用侧有账本与只读接口**（缺的是页面与维度），**模型侧才确实无实体、无接口**。§7 落地清单包含对两处文档措辞的更正。

## 3. 决策记录（已确认）

| # | 决策点 | 结论 |
| --- | --- | --- |
| D1 | 本期范围 | **只做费用页**；模型侧留到下一期（需专项评审） |
| D2 | 展示维度 | **只用现有租户累计**（`units` + `cost_cents`），零新查询、零结构变更 |
| D3 | 可见权限 | **沿用现有口径**（`super_admin` 或本租户已登记的 `customer_admin`），不新增权限面 |
| D4 | 侧栏命名（实现时补充确认） | 占位项「模型与费用」**改名为「用量与费用」**，与实际页面一致；模型侧落地时再新增独立入口（宪法：做不到的功能不上界面） |

## 4. 页面与口径细节

- 路由：`?view=billing`，`AppView` 新增 `'billing'`。
- 内容：**累计用量**（整数原值）与**累计费用**（金额）。
- **金额口径**：`cost_cents` 是**整数分**；展示时用**整数运算**换算为元（`¥{floor(abs/100)}.{abs%100 补两位}`），**不使用浮点除法**（宪法：金额不用浮点）；**支持负数**（冲正后累计可能为负，前面加 `-`）。
- **不解释 `units` 的业务含义**：账本里没有单位语义，页面只如实展示原值，不猜测是 token / 次数 / 条数。
- 状态：加载 / 正常（含 `0` 的空态提示）/ `403` 无权限 / `404` 本租户未登记（**单列**，不与错误态混同）/ 网络与 5xx（可重试）。
- 只读：不接受任何写动作，页面明确写出「本页只读」与数据来源（追加式账本，含冲正）。
- 页脚如实说明：**模型清单尚未实现**（模型来自配置注入，属下一期立项）。

## 5. 测试计划（先写测试）

| 层次 | 覆盖 |
| --- | --- |
| api | 请求路径正确；`403` → 固定权限文案；`404` → 固定「未登记」文案；`5xx`/网络 → 可重试文案；**不透出服务端原始 detail（避免 404/403 文案被后端改词影响）** |
| 金额格式化 | `0` → `¥0.00`；`123456` → `¥1234.56`；`5` → `¥0.05`；**负数**（冲正）→ `-¥1.00`；大数不产生浮点误差（如 `999999999999`） |
| 页面 | 正常渲染 units/费用；`units=0 且 cost_cents=0` 显示空态提示；`403` 显示无权限文案且**不出现「重新尝试」**；`404` 显示「本租户尚未登记」；错误 + 重试后成功；只读声明与模型未实现的说明存在 |
| 路由 | 侧栏「用量与费用」跳转 `?view=billing` |

## 6. 已知限制（如实登记）

1. **只有租户级累计**：没有时间趋势、没有按模型/任务的分摊，页面不提供任何走势或占比。
2. **`units` 语义未定义**：只展示原值，不标注单位。
3. **`404` 是常见态而非异常**：开发/未初始化环境里商业化仓储为空，接口即返回 `404`；页面据此显示「本租户尚未登记」，**这不是故障**。
4. **模型侧未做**：本页不展示任何模型信息，页脚已如实说明。
5. 冲正入口未做（写操作，需独立口径）。

## 7. 落地清单

1. `admin-web/src/features/billing/`：`types.ts` / `api.ts` / `state.ts` / `UsageBillingPage.tsx` + 测试。
2. `admin-web/src/app/AppShell.tsx`：`AppView` 增加 `'billing'`，侧栏项改名「用量与费用」并接上 `view: 'billing'`。
3. `admin-web/src/app/App.tsx`：`?view=billing` 路由。
4. `admin-web/src/styles/global.css`：追加样式。
5. 文档同步：`docs/api-contract.md`（补 `GET /api/v1/commercial/usage` 的 404 语义与页面引用）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md`（**更正「无数据源」措辞**，登记模型侧为下一期）。
6. 全量回归（`pytest` + `compileall` + 两端 vitest/build + 桌面 `node --test`），CI 实跑确认。
