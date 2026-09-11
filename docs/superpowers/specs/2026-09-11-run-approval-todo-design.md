# 审批人租户级待办入口设计 · 口径（已确认）

> **状态**：**口径已确认**（§9 四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1100 项测试通过，CI 实跑通过）

## 1. 目标与非目标

**目标**：关闭就绪清单 E 节最后一条 ❌——让审批人**主动发现**待决议的运行审批，而不是必须已经知道 `run_id`。做法是把运行审批并入既有的「待我审批」聚合，并在伴侣端提供第 4 类卡片与决议动作。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 持久化运行时状态或新增审批表 | 运行时状态**本来就在内存**（§2 事实 1）；只持久化审批表会造成「列表里有、决议却 404」的幽灵待办，除非连整个运行时状态一起持久化（另一个项目量级） |
| 给审批人发站内通知 | 一条审批 × N 个审批人会产生 N 条通知，且需新增「按租户列审批角色」查询、名册变动无法回填；既有三类审批都靠聚合轮询发现，本类保持一致 |
| 管理台新增「待我审批」页 | 既有三类审批只在伴侣端；管理台已有运行详情页可决议，保持对称 |
| 列出已决议的审批 | 聚合只服务「现在要做什么」，历史看运行详情页 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 运行时状态在**所有模式（含 postgres）**都是进程内 `RuntimeStateStore`，**未持久化**；重启后按旧 `run_id` 决议会「运行不存在」。**该事实此前无任何文档记录** | `app/bootstrap.py:540-553`、`app/runtime/state.py` |
| 2 | `RuntimeStateStore` 只有 `dict[run_id] → state`，**没有租户级遍历**，也没有创建时间 | `app/runtime/state.py:23-51` |
| 3 | 聚合服务只支持三类 kind，`counts` 键固定三个 + total | `app/approvals.py:10-19` |
| 4 | 账户仓储没有「按租户列审批角色」的查询（只有 `list_requests` 与 `has_approved_admin`） | `app/accounts/repository.py:115-120` |
| 5 | **缺陷**：Mock 的 `decide_approval` 不校验运行是否已终态——先驳回（`failed`）后批准另一个仍 `pending` 的审批，会把运行**复活为 `completed`**，违反上一轮规格「终态即终态」 | `app/runtime/mock.py`、spec `2026-09-11-run-approval-decision-design.md` §9 限制 4 |

## 3. 索引与数据（无迁移）

- `RuntimeState` 增加 `created_at: datetime = field(default_factory=lambda: datetime.now(UTC))`（供聚合排序）。
- `RuntimeStateStore` 增加 `list_for_tenant(tenant_id) -> list[RuntimeState]`（同一把锁内过滤）。
- **不加表、不加迁移**：与运行时状态同生共死；重启后待办列表自然为空，**不会出现幽灵待办**。

## 4. 服务层口径

`RuntimeService.list_pending_approvals(actor, *, limit)` 返回本租户的待决议审批描述符：

```python
@dataclass(frozen=True)
class PendingRunApproval:
    run_id: str
    approval_id: str
    step_id: str | None      # 对应计划步骤时非空
    tool: str | None
    task_id: str
    requested_by: str        # 运行发起人（= state.context.user_id）
    created_at: datetime
```

**过滤规则（两条都要）**：

1. 只列**非终态运行**（`running` / `paused`）的审批——终态运行的待办不可决议，列出即误导。
2. 只列 `status == "pending"` 的审批。
3. 结果按 `created_at` 倒序，最多 `limit` 条。

## 5. 缺陷修复：终态不可复活

`decide_approval` 在运行已处于终态（`completed` / `failed` / `cancelled`）时必须**拒绝**，不得改状态：

- 新增异常 `RunNotDecidable(ValueError)`；接口层映射为 **`409`「运行已结束，无法决议」**。
- Mock 在决议前先校验状态；服务层不额外拦截（由适配器保证），但接口层按 409 返回。
- 补测试：先驳回一条审批（运行 → `failed`），再批准另一条仍 `pending` 的审批 → 必须 409 且运行状态**保持 `failed`**。

## 6. 聚合契约（须同步 `docs/api-contract.md`）

`GET /api/v1/approvals/pending` 新增第 4 类：

| 字段 | 取值 |
| --- | --- |
| `kind` | 新增 **`run_approval`**（与 `task_approval` / `plan_proposal` / `account_registration` 并列） |
| `target_id` | `run_id` |
| `title` | 任务标题（能取到时）；取不到时回落为「运行审批」 |
| `requested_by` | 运行发起人 `user_id` |
| `created_at` | 运行时状态的创建时间 |
| `detail` | `{"run_id", "approval_id", "step_id"\|null, "tool"\|null}` —— 客户端据此调用决议接口 |

- `counts` 新增 `run_approval` 键（恒存在，无待办为 0）。
- **可见性**：与任务/计划提案同一口径，仅 `ceo`/`super_admin` 可见；其他角色返回空列表与全 0 计数。
- **剔除自审**：`requested_by == 当前用户` 的条目被剔除（与计划提案同一逻辑，避免展示点不动的待办）。
- 决议仍走既有 `POST /api/v1/runs/{run_id}/approvals/{approval_id}/approval`（路径与语义不变）。

## 7. 伴侣端范围

- `PendingApprovalKind` 增加 `'run_approval'`；`counts` 增加 `run_approval`；`KIND_LABELS` 增加「运行审批」。
- `approveItem` / `rejectItem` **必须先判断 `run_approval`**（现有实现的兜底分支是账号注册，若不前置会把 run 审批误发到注册接口），请求体 `{"approved": true|false}`，路径由 `detail.run_id` + `detail.approval_id` 拼出。
- `run_approval` **可驳回**（`rejectable` 判定沿用「非 task_approval 即可驳回」）。
- 401 仍触发会话过期处理；决议失败展示服务端提示。

## 8. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| 索引 | `list_for_tenant` 只返回本租户；空租户返回空 |
| 服务层 | 只列非终态运行 + `pending` 审批；终态运行与已决议审批不出现；`limit` 生效；按 `created_at` 倒序 |
| 终态守卫 | 终态运行决议抛 `RunNotDecidable`；接口层 409；运行状态**不被改写**（缺陷回归测试） |
| 聚合 | 第 4 类 kind 出现在 `items`；`counts.run_approval` 正确；employee 角色看不到；**发起人自审条目被剔除**；`detail` 含 `run_id`/`approval_id` |
| 接口 | `/api/v1/approvals/pending` 的 `counts` 四个键恒存在 |
| 伴侣端 | 第 4 类卡片渲染；通过/驳回请求打到 `/runs/{runId}/approvals/{approvalId}/approval`（**不落到注册接口**）；401 仍触发会话过期 |
| 契约守护 | `counts` 键与 kind 文档同步；`test_api_contract_coverage.py` 保持通过 |

## 9. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 待决议审批的存储 | **仅内存租户索引**（无迁移；与运行时状态同生共死，无幽灵待办） |
| D2 | 是否通知审批人 | **不发**，靠聚合轮询（与既有三类一致） |
| D3 | 聚合口径 | **角色可见 + 剔除发起人自审** |
| D4 | 前端范围 | **仅伴侣端第 4 类**（管理台仍走运行详情页） |

## 10. 已知限制（实现后需如实登记）

1. **待办列表不跨重启**：运行时状态未持久化（既有限制，本轮首次写入文档）；重启后运行审批待办为空，且旧 `run_id` 无法决议。
2. **多进程不可用**：`RuntimeStateStore` 是进程内状态，多 worker 部署下不同进程看不到彼此的待办（既有限制，同上）。
3. 一条审批对**所有审批角色可见**，没有「指派给某个审批人」的概念。
4. 管理台没有「待我审批」聚合页（既有限制）。

## 11. 落地清单

1. `app/runtime/state.py`：`RuntimeState.created_at`、`RuntimeStateStore.list_for_tenant`。
2. `app/runtime/contracts.py`：`RunNotDecidable`。
3. `app/runtime/mock.py`：决议前校验终态。
4. `app/runtime/service.py`：`PendingRunApproval` + `list_pending_approvals`。
5. `app/approvals.py`：第 4 类 kind、counts 键、可见性与自审剔除。
6. `app/main.py`：`ApprovalsService` 注入运行时审批来源；决议接口映射 409。
7. `companion-pwa/src/features/approvals/`：types / api / page / tests。
8. `docs/api-contract.md`（聚合 4 类与 counts）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步。
9. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
