# 基于指标的编排优化提案设计（子项目③）

## 目标

让工作台读取子项目②已产出的运行指标（`app/runtime/run_metrics.py`），在**样本充足**时自动生成一条「将默认运行时切换到表现更好运行时」的**待人工审核提案**。提案只做建议与留痕，**绝不自动修改任何配置**，采纳与执行必须由人按运行手册完成。

本设计只回答一个问题：**依据指标，是否值得把一个候选运行时提升为默认运行时？** 判定规则必须确定性、可复现、可审计。

## 非目标

- 不做运行指标采集与聚合（子项目②，已完成，本设计只消费）。
- 不做自动应用：审批通过只改变提案状态，不写任何运行时配置，不自动切换默认运行时。
- 不做模型质量、成本、安全等多维打分；本轮只用完成率、工具成功率与样本数。
- 不做按任务类型 / 项目 / 数据分级的细分运行时选择；本轮只比较「整租户默认运行时」这一维度。
- 不新增第二种提案类型（`kind` 目前只有 `runtime_default`）。
- 不提供提案的删除 / 编辑接口；提案一经生成即不可变，只能审批或驳回。
- 不复制第三方项目（含 EvoFlow）的代码或数据模型。

## 数据来源

- 指标服务：`RunMetricsService.summary(tenant_id, *, runtime_key=None)`（子项目②）。
- 使用的字段：顶层 `by_runtime` 数组中每个运行时的
  `runtime_key`、`run_count`、`task_completion_rate`、`tool_success_rate`、`knowledge_hit_rate`、`latency_p95_ms`。
- 生成提案时**以租户为界**：`self.metrics.summary(actor.tenant_id)`，不接受客户端传入租户或运行时范围。

## 提案生成规则

`OrchestrationProposalService.generate(actor, *, kind=runtime_default)` 按固定顺序判定，任一条件不满足即返回 `(None, 人类可读理由)`，不落库：

1. **类型校验**：仅支持 `runtime_default`；其他值抛 `ValueError`。
2. **样本门槛**：只保留 `run_count >= min_samples` 的运行时。合格运行时少于 2 个时返回
   `可用于比较的运行时不足（需至少 2 个且各自样本数不少于 N）`。
3. **选优规则**：在合格集合内按
   `(task_completion_rate 降序, tool_success_rate 降序, run_count 降序, runtime_key 升序)` 取第一。
   前三项为「越大越好」故取降序，`runtime_key` 升序作为**确定性**兜底，保证同样输入两次得到同一结果。
4. **默认已最优**：最优运行时等于 `default_runtime_key` 时返回
   `当前默认运行时已是表现最好的运行时，无需调整`。
5. **默认样本不足**：当前默认运行时不在合格集合内时返回 `当前默认运行时样本不足，暂不比较`。
   **不得**拿 0 当基线凭空比较。
6. **改善门槛**：`最优.task_completion_rate - 当前.task_completion_rate < improvement_threshold` 时返回
   `最优运行时的完成任务率提升未达到阈值，暂不建议切换`。
7. **幂等**：`store.find_pending(tenant_id, kind, 最优.runtime_key)` 命中时直接复用该待审提案，不重复创建。
   被驳回（或已审批）的提案不参与幂等查找，因此允许驳回后重新生成。
8. **创建提案**：写入 `current_value=default_runtime_key`、`proposed_value=最优.runtime_key`，
   `rationale` 用固定模板串出数字（完成率保留两位小数、样本数取整），
   `metrics_snapshot` 保存当前与最优两条运行时指标。

`rationale` 模板（示例）：

> 运行时 agentscope 的任务完成率 0.90（样本 10）高于当前默认 mock 的 0.60（样本 10），建议将默认运行时切换为 agentscope。

`metrics_snapshot` 结构：`{"current": {...}, "proposed": {...}}`，每条仅保留白名单键
`runtime_key / run_count / task_completion_rate / tool_success_rate / knowledge_hit_rate / latency_p95_ms`，
其他内部字段在写入前被裁剪（`_SNAPSHOT_KEYS`）。

## 状态机

```
pending_review ──approve──> approved
              └─reject───> rejected
```

- 只有 `pending_review` 允许审批或驳回，重复操作返回 `OrchestrationProposalStateConflict`。
- **审批通过不触发任何配置变更**：系统不写默认运行时配置、不重启运行时、不切换路由。
  采纳动作记录在 `rationale` 与运行手册中，由人工按运维流程执行。
- 不加数据库唯一约束：被驳回后允许重新生成同一建议。

## 权限

- 接口层：全部编排优化提案接口（生成、列表、详情、审批、驳回）**仅 `ceo` / `super_admin`** 可访问，其他角色返回 `403`「只有 CEO 或超级管理员可以管理编排优化提案」。
- 服务层：审批 / 驳回再次调用 `ensure_can_approve(actor)`（仅 `ceo` / `super_admin`），并校验
  `actor.user_id != proposal.created_by`，否则抛 `PolicyError("发起人不能审批自己提交的优化提案")`。
- 租户隔离：`get` / `list` 一律带 `tenant_id` 条件，跨租户统一表现为不存在（`404`）。

## 审计动作

在 `app/audit/models.py` 新增：

| 动作 | 值 | 明细键 |
| --- | --- | --- |
| `ORCHESTRATION_PROPOSED` | `orchestration.proposed` | `kind`、`current_value`、`proposed_value`、`run_count` |
| `ORCHESTRATION_APPROVED` | `orchestration.approved` | `kind`、`proposed_value` |
| `ORCHESTRATION_REJECTED` | `orchestration.rejected` | `reason` |

上述明细键均已在 `ALLOWED_DETAIL_KEYS` 白名单内，未声明键会抛 `AuditDetailNotAllowed`。
审计与日志均不含密钥、Token 或原始模型响应。

## 接口清单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/orchestration-proposals` | CEO / 超级管理员 | 依据指标生成提案，**始终 200**，无提案时 `proposal=null` 并由 `reason` 说明原因 |
| `GET` | `/api/v1/orchestration-proposals?limit=50` | CEO / 超级管理员 | 列出当前租户提案 |
| `GET` | `/api/v1/orchestration-proposals/{proposal_id}` | CEO / 超级管理员 | 查看详情；跨租户或不存在返回 `404`「优化提案不存在」 |
| `POST` | `/api/v1/orchestration-proposals/{proposal_id}/approval` | CEO / 超级管理员 | 审批；`NotFound→404`、`StateConflict→409`、`PolicyError→403` |
| `POST` | `/api/v1/orchestration-proposals/{proposal_id}/rejection` | CEO / 超级管理员 | 驳回并记录原因；另含空原因 `ValueError→422` |

请求体：

- 生成：`{ "kind": "runtime_default" }`（`extra="forbid"`，`kind` 可省略，默认 `runtime_default`）。
- 驳回：`{ "reason": "..." }`（去空后为空返回 `422`）。

响应：`{"proposal": <view>|null, "reason": "..."}`（生成）与 `{"items": [<view>...]}`（列表）。
`view` 字段：`proposal_id / kind / current_value / proposed_value / rationale / metrics_snapshot / status / created_by / created_at / reviewed_by / reviewed_at / rejection_reason`。

## 配置

| 配置项 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- |
| `WORKBENCH_ORCHESTRATION_DEFAULT_RUNTIME_KEY` | `mock` | 字符串 | 当前默认运行时 |
| `WORKBENCH_ORCHESTRATION_MIN_SAMPLES` | `5` | 1–1000 | 参与比较所需的最小样本数 |
| `WORKBENCH_ORCHESTRATION_IMPROVEMENT_THRESHOLD` | `0.1` | 0.0–1.0 | 完成任务率提升的最小阈值 |

## 持久化

`migrations/014_orchestration_proposals.sql` 新增表 `workbench_orchestration_proposals`，
含索引 `(tenant_id, status)` 与 `(tenant_id, created_at DESC)`，全部 `IF NOT EXISTS`，**不加唯一约束**。
内存实现 `InMemoryOrchestrationProposalStore` 与 PostgreSQL 实现
`PostgresOrchestrationProposalStore` 行为一致；审批使用条件更新
（`WHERE proposal_id = %s AND status = 'pending_review'`）保证并发安全。

## 已知限制与未做事项

- **只有一种 `kind`**：`runtime_default`。任务类型 / 项目 / 数据分级的细分策略未实现。
- **`knowledge_hits` 当前恒为 0**：运行指标采集里的知识命中尚未真正接线（子项目②的已知限制），
  因此本设计只把 `knowledge_hit_rate` 存入快照，**不**用它做选优依据。
- **提案采纳后需人工执行**：系统绝不自动修改默认运行时配置；审批只剩状态流转与审计留痕。
- **只用完成率触发**：改善门槛只看 `task_completion_rate`，工具成功率与延迟仅作为选优排序的次级依据，
  尚未进入阈值判断。
- **小样本被门槛挡住而非加权**：合格集合外的运行时（含当前默认）直接不参与比较，不做平滑或置信区间处理。
- **未做自动重生成**：不提供定时任务在指标变化后自动产出新提案；需人工再次调用生成接口。
- **并发生成**：服务层「先查待审、再写入」不是原子操作，极端并发下可能产生两条相同建议的待审提案；
  本轮不引入数据库唯一约束（会阻断驳回后重新生成），已知且接受。
