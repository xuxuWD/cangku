# 运行内审批决议闭环设计 · 口径（已确认）

> **状态**：**口径已确认**（§11 决策表四项均已定），进入实现（先写失败测试，再写实现）。
> **日期**：2026-09-11　**基线**：`main`（后端 1083 项测试通过，CI 实跑通过）

## 1. 目标与非目标

**目标**：把「高风险步骤需要人工审批」这条链路补成闭环——登记审批后可以被**决议**，决议结果驱动运行落到**终态**，并让提交人知道结果。

上一轮已把运行终态落盘做扎实，但 `requires_approval` 步骤的运行**永久停在 `running`**（`app/runtime/mock.py:38-46`）：审批只登记不决议，`resume_run` 也不会执行剩余步骤。本设计补齐这一段，关闭该已登记缺口。

**非目标（明确不做）**：

| 不做 | 原因 |
| --- | --- |
| 把运行审批并入「待我审批」聚合接口 | 状态存储**没有租户级运行索引**，只能按 `run_id` 取；聚合需要先新建索引，规模独立（见 §9 限制 1） |
| 给审批人发站内通知 | 账户仓储**没有「按租户列 CEO/超管」的查询**，收件箱接收人必须是具体 `user_id`，无法广播（见 §9 限制 1） |
| 收集驳回原因（自由文本） | 与上一轮「运行终态不落自由文本」一致；需要的说明走线下，将来若确需再单独评审脱敏口径 |
| 真实外部运行时的决议联调 | 无真实环境；外部适配器只做命令映射与契约测试 |

## 2. 事实核查（实际读码确认）

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | `start_run` 遇到 `requires_approval` 步骤只写 `state.approvals[step_id]="pending"`，最终状态停在 `running` | `app/runtime/mock.py:18-35` |
| 2 | `resume_run` 只把状态改成 `running`，**不执行**剩余步骤（既有测试已冻结该行为） | `app/runtime/mock.py:53-58`、`tests/test_mock_runtime.py:12-24` |
| 3 | 适配器协议有 `request_approval`，**没有**决议方法 | `app/runtime/contracts.py:119-130` |
| 4 | 接口只有 `POST /runs/{run_id}/approvals`（登记），无决议与查询入口 | `app/main.py:1063-1070` |
| 5 | `finish_reason` 目前按 `status` 映射，`failed` 只会得到 `step_failed` | `app/runtime/run_metrics.py:11-17` |

## 3. 状态机与数据（无需迁移）

复用 `RuntimeState.approvals: dict[str, str]`，明确取值语义：

| 键 | 来源 | 值 |
| --- | --- | --- |
| 计划步骤的 `step_id` | 启动时 `requires_approval` 的步骤 | `pending` → `approved` / `rejected` |
| 运行时生成的 `approval_id` | `POST /runs/{id}/approvals` 登记 | 同上 |

**运行终态规则**：

- 存在任何 `pending` 审批 → 运行保持 `running`（不变）
- 全部审批已决议且**无驳回** → 继续执行被批准的步骤，随后 `completed`
- 任一审批被驳回 → **立即** `failed`，剩余步骤不再执行

**无新增表、无迁移**：`finish_reason` 已是 `TEXT` 列。

## 4. 结束原因推导规则（修正）

`failed` 需要区分「机器失败」与「人工驳回」，因此推导从「仅看 status」改为「看 status + 审批状态」，仍是**单向、确定性**的：

| 运行状态 | 附加条件 | `finish_reason` |
| --- | --- | --- |
| `completed` | — | `run_completed` |
| `cancelled` | — | `cancelled_by_user` |
| `failed` | 存在 `rejected` 审批 | **`approval_rejected`**（新增） |
| `failed` | 其余 | `step_failed` |
| `running` / `paused` | — | `null` |

## 5. 事件

新增 `RuntimeEventType.APPROVAL_DECIDED = "approval.decided"`，payload 仅含 `approval_id` 与 `approved`（布尔），**不含任何自由文本**。外部适配器事件映射同步该类型；未知外部类型仍统一映射为 `run.failed`。

## 6. 接口契约（新增 2 个，须同步 `docs/api-contract.md`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/runs/{run_id}/approvals` | 返回该运行的审批项：`{"items":[{"approval_id","step_id","tool","status"}]}`；`status ∈ pending/approved/rejected`；`step_id`/`tool` 仅在审批项对应计划步骤时非空 |
| `POST` | `/api/v1/runs/{run_id}/approvals/{approval_id}/approval` | 请求体 `{"approved": true|false}`（`extra="forbid"`）；成功返回 `{"run_id","approval_id","status","run_status"}` |

**权限矩阵**（越权与不存在的语义要分清）：

| 场景 | 结果 |
| --- | --- |
| 未登录 | `401` |
| 跨租户运行 / 运行不存在 | `404`「运行不存在」（不泄露存在性） |
| 角色不是 `ceo`/`super_admin` | `403`「只有 CEO 或超级管理员可以决议运行审批」 |
| 决议人是该运行的发起人 | `403`「发起人不能审批自己发起的运行」（与计划提案口径一致） |
| `approval_id` 不在该运行内 | `404`「审批不存在」 |
| 该审批已决议过 | `409`「审批已决议」 |

## 7. Mock 运行时的决议语义

`decide_approval(run_id, approval_id, approved)`：

- **通过**：该项置 `approved`；若该项对应计划步骤，则执行该步骤（记 `completed_steps`、`tool_calls +1`、`successful_tools +1`，发 `tool.result`）；随后若已无 `pending`，置 `completed` 并发布 `run.completed`
- **驳回**：该项置 `rejected`，置 `failed`，发布 `run.failed`（payload 含 `approval_id` 与 `reason="approval_rejected"`），不再执行任何剩余步骤
- 每次决议后都 `save_checkpoint`，保证 `GET /runs/{id}/events` 与检查点一致

外部适配器（`ExternalAdapter`）把决议映射为一次命令调用（`action="approval_decision"`），**未联调**，与既有外部命令同一验收状态。

## 8. 写入者与通知（复用上一轮的链路）

- **运行记录**：`RuntimeService.decide_approval(actor, run_id, approval_id, approved)` 委托适配器后走既有 `_sync_run_record` 回写（保留 `started_at`/`proposal_id`）。
- **通知**：驳回后由既有 `_notify_run_terminal` 处理，按 `finish_reason` 分流——
  - `approval_rejected` → 新增 kind **`run.approval_rejected`**（文案「你的任务运行被审批驳回」）
  - 其余 `failed` → 既有 `run.failed`
  - `completed` / `cancelled` 行为不变（完成不打扰）
- **审计**：新增动作 **`run.approval_decided`**，`target_type="run"`、`target_id=run_id`，detail 仅 `{"status": "approved"|"rejected"}`（白名单内键，无自由文本）。

## 9. 已知限制（实现后需如实登记）

1. **审批人没有主动发现入口**：无租户级运行索引、无按角色查询审批人，故待决议的运行审批既进不了「待我审批」聚合、也无法广播通知；审批人必须已知 `run_id`（例如由提交人转达或从事件流观察）。
2. **外部运行时的决议未联调**：只做命令映射与契约测试，不代表真实平台可决议。
3. **驳回不记录原因**：运行记录只存受控枚举 `approval_rejected`，不收集自由文本；`approval.decided` 事件也只有布尔值。
4. 驳回后**剩余步骤不可恢复执行**（终态即终态）；若将来要「改判」，需要新的状态机设计。

## 10. 测试计划（先写测试，后写实现）

| 层次 | 覆盖 |
| --- | --- |
| Mock 运行时 | 通过 → 步骤执行、无 pending 后 `completed`；驳回 → `failed` 且不再执行；未知审批项与重复决议的报错 |
| 结束原因 | `failed` 细分：有驳回审批 → `approval_rejected`；无 → `step_failed`；仍保持非终态为空 |
| 服务层 | `decide_approval` 回写记录（保留 `started_at`、`proposal_id`）；`run_metrics=None` 时不报错 |
| 接口 | 列表与决议的状态码矩阵（401/403/403 自审/404 跨租户/404 未知审批/409 重复决议）；决议后 `GET /runs/{id}/metrics` 的状态与 `finish_reason` |
| 通知与审计 | 驳回写 `run.approval_rejected` 通知 + `run.approval_decided` 审计；通过不产生通知 |
| 契约守护 | 新路由必须出现在 `docs/api-contract.md`（`test_api_contract_coverage.py` 守护） |

## 11. 决策记录（已确认）

| # | 决策 | 结论 |
| --- | --- | --- |
| D1 | 决议权限 | **仅 CEO/超级管理员，且发起人不能自审** |
| D2 | 驳回后的终态 | **`failed` + 新增 `finish_reason=approval_rejected`** |
| D3 | 决议结果通知 | **驳回发专用通知 `run.approval_rejected`**；通过不通知 |
| D4 | 审批人发现途径 | **只做运行级接口**，把「无租户级聚合/无法按角色广播」登记为缺口 |

## 12. 落地清单

1. `app/runtime/contracts.py`：`RuntimeEventType.APPROVAL_DECIDED`；协议增加 `decide_approval`。
2. `app/runtime/mock.py`：`decide_approval` 决议语义。
3. `app/runtime/adapters/common.py`：外部决议命令映射 + 事件映射新增 `approval.decided`。
4. `app/runtime/records.py`：`FinishReason.APPROVAL_REJECTED`。
5. `app/runtime/run_metrics.py`：`failed` 细分推导。
6. `app/runtime/service.py`：`decide_approval` + 权限校验（新异常区分 403/404）+ 回写记录。
7. `app/inbox.py`：新增 kind `run.approval_rejected` 与 `run_approval_rejected(...)`。
8. `app/audit/models.py`：新增 `run.approval_decided`。
9. `app/main.py`：两个新接口 + `_notify_run_terminal` 按 `finish_reason` 分流。
10. `docs/api-contract.md`（两个新接口、kind 9→10、`finish_reason` 取值表）、`docs/delivery-gates.md`、`docs/delivery-readiness-checklist.md` 同步。
11. 全量回归（`pytest` + `compileall` + 两端 vitest/build + desktop `node --test`），CI 实跑确认。
