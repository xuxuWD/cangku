# 计划生成与审核闸门设计（子项目①）

## 目标

让员工用自然语言描述目标，由工作台生成一份**可审核的 Agent 计划**，审核通过后复用既有 Runtime 执行。计划的步骤与风险等级由**服务端**依据工具白名单推导，模型不得自证风险。生成后端可切换：开发环境使用确定性 Mock，生产环境使用真实模型。

本设计是「自然语言 → 工作流」三步走的第一阶段。反馈与指标采集（子项目②）、基于指标的编排优化提案（子项目③）不在本轮范围，各自另立 spec。本轮完成后即可独立交付「描述目标 → 得到可审核计划 → 复用既有运行层执行」的闭环价值。

## 当前问题

工作台已具备本能力的绝大部分地基，唯独缺少「从目标到计划」的生成环节：

- 已有计划表示 `AgentPlan` / `PlanStep`，且 `AgentPlan.from_steps` 已能按 `kind` 推导 `requires_approval`。
- 已有运行执行协议 `AgentRuntimeAdapter`（启动、事件流、暂停、恢复、取消、审批、检查点、重放、用量、健康）。
- 已有模型网关 `ModelGateway`，按能力与数据分级路由模型，敏感数据不会路由到无资格的模型。
- 已有受控成长提案模式 `GrowthProposalStore`（`pending_review → approved → active`）。
- 已有策略中心、运行审批、审计与 Outbox。

缺口是：任务步骤目前只能由调用方手工构造，员工无法用自然语言表达目标；而计划中的 `kind` 由调用方传入，若交给模型自由填写，模型即可把高风险步骤标成只读以绕过审批。

## 决策记录

| 议题 | 结论 |
| --- | --- |
| 生成后端 | 可切换：开发用确定性 Mock，生产用 OpenAI 兼容真实模型 |
| 风险判定 | 服务端按工具白名单与工具到 kind 的映射推导；模型提供的 `kind`、`requires_approval` 一律忽略 |
| 未知工具 | 拒绝整个计划，不静默丢弃单步 |
| 审核闸门 | 提案层面一律人工审核；运行层面按服务端推导的 `requires_approval`，只读步骤自动通过、写入与外部副作用步骤需审批 |
| 审批权限 | 审批与驳回仅限 CEO 或超级管理员，与既有任务审批保持一致；发起人不能自审自己的提案 |
| 计划归属 | 挂在既有 Task 上，不新建第二套工作流事实源 |
| 执行方式 | 审核通过后仍需显式触发；执行只能经既有 RuntimeService |
| 自动执行 | 本轮不做 |
| 反馈驱动的自动优化 | 本轮不做，属子项目③ |
| 可视化编排编辑器 | 本轮不做 |

## 方案

新增 `app/planner/` 领域包，与既有控制平面解耦但复用其能力：

- `ToolCatalog` 是唯一的安全边界：服务端持有工具白名单与工具到 kind 的映射。生成器只能从白名单选择工具，`kind` 与 `requires_approval` 由服务端推导。
- `PlanGenerator` 是协议，有两种实现：`MockPlanGenerator`（确定性、可重复、只使用白名单工具）与 `ModelPlanGenerator`（OpenAI 兼容，要求模型输出结构化步骤）。
- `PlannerService` 负责生成提案、审批、驳回与执行编排，只依赖最小仓储接口与既有 RuntimeService。
- `PlanProposalStore` 提供内存与 PostgreSQL 两种实现，沿用 `bootstrap.py` 的装配方式。
- 执行阶段直接调用既有 `RuntimeService.start`，它已会从任务快照重建租户、用户、岗位、项目、预算、知识与文件范围和策略版本，客户端无法覆盖。

不采用「让模型输出完整计划定义」的做法，因为那等于把权限与风险判定交给不可信输入；也不采用「生成后自动执行」，因为生成的计划必须先过审核闸门。

## 组件与接口

### 工具白名单

`app/planner/models.py` 定义：

- `Tool`：`name`、`kind`、`description`、`requires_approval`。
- `ToolCatalog`：持有 `Tool` 集合，提供 `resolve(name) -> Tool`；名称不在白名单时抛出 `UnknownTool`。
- 服务端维护的 kind 取值与既有 `AgentPlan.from_steps` 的副作用集合保持一致：`read` 自动通过；`write`、`external_send`、`publish`、`delete`、`permission` 需要审批。

初始白名单必须**只登记部署中已真实接通的工具**，并且新增工具属于受控变更。开发环境的 Mock Runtime 不真正执行工具，因此白名单在开发环境主要用于验证边界与审批推导，不代表该工具已具备生产能力。

### 计划提案

`PlanProposal` 字段：`proposal_id`、`task_id`、`tenant_id`、`goal`、`steps`（服务端推导后的步骤）、`status`（`pending_review` / `approved` / `rejected`）、`generator_key`、`generator_model`、`created_by`、`created_at`、`reviewed_by`、`reviewed_at`、`rejection_reason`、`idempotency_key`。

状态机只允许 `pending_review → approved` 与 `pending_review → rejected`，重复审批返回冲突。

### 生成器

- `PlanGenerator` 协议：`generate(goal, *, max_steps, catalog) -> list[GeneratedStep]`，其中 `GeneratedStep` 只含 `step_id`、`tool`、`args`。
- `MockPlanGenerator`：从白名单的只读工具中按固定顺序取用，产出确定、可重复的步骤，仅使用白名单工具。
- `ModelPlanGenerator`：通过 OpenAI 兼容接口请求结构化步骤；解析失败、缺少必需字段、工具不在白名单时，**一律抛出明确错误，不静默降级为 Mock**。模型无权选择或声明模型；数据分级闸门本轮未接入，见下文「实现偏差记录」。
- 生成后的步骤统一经 `_normalize_steps` 处理：校验工具白名单、由服务端写入 `kind` 与 `requires_approval`、校验 `args` 为 JSON 对象且键名不命中敏感键集合。

### 服务

`app/planner/service.py` 的 `PlannerService`：

- `propose(actor, task_id, goal, idempotency_key)`：校验任务归属与租户；按同一任务、同一幂等键返回既有提案；调用生成器；归一化步骤；写入 `pending_review` 提案。**本轮不写审计记录**，见下文「实现偏差记录」。
- `get(actor, proposal_id)`：跨租户或不存在的提案统一表现为不存在。
- `approve(actor, proposal_id)`：只允许 `pending_review`；写入审批人与时间。
- `reject(actor, proposal_id, reason)`：只允许 `pending_review`；记录原因。
- `start_run(actor, proposal_id, runtime_key, mode)`：仅 `approved` 可执行，否则返回冲突；调用既有 `RuntimeService.start`，传入服务端归一化后的步骤。

### 接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/tasks/{task_id}/plan-proposals` | 任务发起人、CEO、超级管理员 | 提交目标生成提案，需幂等键 |
| `GET` | `/api/v1/plan-proposals/{proposal_id}` | 任务发起人、CEO、超级管理员 | 查看提案与服务端推导后的步骤 |
| `POST` | `/api/v1/plan-proposals/{proposal_id}/approval` | CEO 或超级管理员 | 审批通过，发起人不能自审 |
| `POST` | `/api/v1/plan-proposals/{proposal_id}/rejection` | CEO 或超级管理员 | 驳回并记录原因 |
| `POST` | `/api/v1/plan-proposals/{proposal_id}/runs` | 任务发起人、CEO、超级管理员 | 仅 `approved` 可执行，复用既有 Runtime |

响应只包含提案号、任务号、目标、步骤（含服务端推导的 kind 与是否需审批）、状态、生成器标识与时间；不包含模型密钥、原始模型响应或内部提示词。

权限口径以任务仓储的可见性为准：能读取该任务的身份（任务发起人、部门负责人、CEO、超级管理员）即可提交目标与查看自己的提案；提案只有**发起人本人**或 CEO/超级管理员可查看与执行；审批与驳回仅限 CEO 或超级管理员，且发起人不能自审。

## 配置

- `WORKBENCH_PLANNER_BACKEND`：`mock`（默认）或 `openai_compatible`。
- `WORKBENCH_PLANNER_MODEL_BASE_URL`、`WORKBENCH_PLANNER_MODEL_NAME`、`WORKBENCH_PLANNER_MODEL_API_KEY`、`WORKBENCH_PLANNER_MODEL_TIMEOUT_SECONDS`：连接信息与内容工作台分开配置，避免耦合。
- `WORKBENCH_PLANNER_MAX_STEPS`：默认 `10`，允许范围 `1`–`50`，越界时应用拒绝启动。
- 选择 `openai_compatible` 但缺少地址、模型名或密钥时，启动即失败，不静默回退到 Mock。

模型选择与连接配置是两件事：连接信息来自上面的 planner 专属配置（单模型直连，形态与内容工作台的 OpenAI 兼容后端一致）。**本轮不接入 `ModelGateway` 的数据分级闸门**，原因见下文「实现偏差记录」。

## 错误与一致性

- 未知工具：拒绝整个计划，返回 `422` 并指出违规工具名，不生成部分计划。
- 模型输出无法解析时返回 `422`，任务与提案状态不进入可用态；超出步数上限时生成阶段按上限截断，且 `normalize_steps` 仍对直接调用方执行「超过上限即拒绝」的强校验（双重防线）。
- 未审批即执行：返回 `409`。
- 跨租户或不存在提案：统一返回 `404`，不泄露存在性。
- 重复审批：返回 `409`，不重复写入审计。
- 相同幂等键重复提交：返回既有提案，不重复调用生成器。
- 提案、审计与日志中不得出现模型密钥、原始模型响应、口令或会话凭证。

## 测试验收

先新增或更新行为测试，再修改生产代码：

- 白名单：未知工具导致整份计划被拒；模型在响应里自报 `kind="read"` 时，服务端仍推导为高风险并要求审批；只读工具自动通过。
- 生成器：Mock 结果确定可重复且只使用白名单工具；模型生成器遇到非法 JSON、缺字段、超步数、越界工具时抛出明确错误，且**不降级为 Mock**。
- 归一化：`args` 非对象被拒；`args` 命中敏感键（token / api_key / password / cookie 等）被拒；步骤数超限被拒。
- 状态机：`pending_review` 可审批与驳回；重复审批冲突；已驳回不可审批；未批准不可执行。
- 权限：发起人或普通员工不能审批与驳回自己的提案，返回 `403`；CEO 或超级管理员可以审批。
- 幂等：同任务同幂等键返回同一提案，生成器只被调用一次。
- 执行：仅 `approved` 可启动；执行复用既有 RuntimeService，跨租户返回 `404`；客户端无法覆盖租户、预算与策略版本。
- 配置：`WORKBENCH_PLANNER_MAX_STEPS` 越界时启动失败；选择真实模型但缺少配置时启动失败。
- 脱敏：接口响应、提案记录与错误信息中不含模型密钥与原始模型响应。
- 回归：既有测试全部通过，开发环境请求头流程与其他接口契约不变。

真实模型效果、工具真实执行能力、并发压测与 staging 验收不在本设计范围内，不据此宣称已上线。

## 交付物与文档同步

按仓库「每次提交必须满足」的约定，本设计同时交付以下变更：

- 新增 `migrations/009_plan_proposals.sql` 保存计划提案。
- 同步 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS` 清单与 `docs/private-deployment-runbook.md` 的迁移范围，避免 staging 预检因新增迁移而漂移。
- 更新 `docs/api-contract.md`，补入 5 个接口的路径、请求字段、状态码与脱敏约定。
- 更新 `.env.example`，补入 planner 相关配置项。
- 更新 `docs/delivery-gates.md`：只勾选本轮真实完成的部分，**不**勾选子项目②与③对应的能力。

## 实现偏差记录

以下三项是设计初稿提出、但实施阶段未落地或作了调整的要求。此处如实登记，不视为已完成：

- **未写审计记录**：初稿要求 `propose` 与审批写入审计。实施时未实现——项目层面「关键操作结构化日志/审计」本身就是已登记的遗留项（见账号功能设计文档的「与项目宪法的差距」G2），本轮不单独为计划模块另造一套审计机制，避免出现两套并行审计。**在执行该遗留专项时，计划模块的生成、审批与执行必须一并纳入。**
- **未接入 `ModelGateway` 数据分级闸门**：初稿要求调用模型前校验数据分级。实施时未实现——当前规划输入（自然语言目标）没有可用的数据分级来源，`ModelGateway` 需要「能力 + 数据等级」两个输入才能路由，缺少后者时接入只会变成形式化检查。**在引入规划输入的数据分级之前，不应宣称该闸门已生效。**
- **超步数改为截断**：初稿要求超上限即报错。实施改为生成阶段按上限截断，同时保留 `normalize_steps` 对直接调用方的强校验。两条防线并存，但对外不再返回「步骤数超限」这一错误码。

另有两处按实施简化，已在正文对齐：`MockPlanGenerator` 取白名单中的只读工具生成确定性步骤（不解析目标关键词）；接口权限以任务仓储的可见性为准（含部门负责人），提案可见性为发起人或 CEO/超级管理员。

## 非目标

- 不做反馈驱动的自动优化与提案生成（子项目③）。
- 不做运行指标采集与聚合（子项目②）。
- 不做自动化执行：审核通过后执行必须由人显式触发。
- 不做可视化编排编辑器或 DAG 图形界面。
- 不新建独立的「工作流」领域对象，计划始终挂在既有 Task 上。
- 不允许模型决定工具白名单、步骤风险等级、审批结果、预算或任务最终状态。
- 不复制第三方项目（包括 EvoFlow）的代码或数据模型。

## 已知限制

- 工具白名单初版只登记开发环境可验证的最小集合；真实工具执行能力取决于部署中接通的 Runtime 适配器，白名单存在不代表该工具已具备生产能力。
- 生成质量取决于模型能力，本设计只保证**边界安全**（白名单、风险推导、审核闸门），不保证计划一定正确或最优。计划正确性由人工审核兜底。
- 低风险步骤自动通过意味着只读步骤无需逐条确认；这些步骤仍受既有知识范围、文件范围与预算约束，且运行层不对其放宽策略。
- 与子项目③的衔接点（如何用运行指标生成改进提案）在本轮只保留 `generator_key` 与运行号等最小关联字段，具体方案在③中设计。
