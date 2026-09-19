# 「数字员工注册中心」界面接口契约（第 5 轮）

> 状态：**草案 v1 · 2026-09-19**（第 5 轮前端交付物，AD-01 **管理后台视角**）。
> 与 `docs/api-contract.md`（后端真源）：**只引用、不修改**；既有接口按原文口径标注，未定义的显式写「未定义」。
> **与 `docs/contracts/my-agents-api.md` 的关系**：同一实体的两个视角（员工侧「我的」/ 管理侧「全员」），
> **字段命名必须一致**；管理侧**多**创建者（`created_by`）与使用统计（`usage`），**不含** `ownership`（员工侧视角字段）。
> 字段名与 `src/features/agentRegistry/types.ts` **逐字一致**（逐字段点名见 §1 / §5）。

## 0. 权限口径（本页仅管理角色可见）

界面：员工访问 ⇒ `PermissionGuard` 渲染**无权限态（原因 + 申请入口）**，**不请求数据、也不渲染空表格**。
接口：既有 `/api/v1/workforce/*` 仅 `super_admin`（其他角色 `403`「只有超级管理员可以管理岗位与数字员工目录」）。

## 1. 列表（含筛选 / 分页）· 复用既有接口

| 项 | 内容 |
| --- | --- |
| 方法 / 路径 | `GET /api/v1/workforce/agents`（既有，仅 super_admin） |
| 查询参数 | `status`（可选 `active`/`disabled`）、`role_key`（可选，6 个岗位键）、`created_by`（可选，模糊）、`keyword`（可选，名称模糊）、`limit`（1–200，默认 50）、`offset`（≥0，默认 0） |
| 分页 | 必须分页；响应 `{items, total, limit, offset}`（前端 `RegistryQuery{page, pageSize}` 换算为 `limit` / `offset`） |
| 错误码 | `401` 未认证 / `403` 非 super_admin / `422` 参数非法（`status`、`limit` 越界）/ 他租户标识按 `404`（不泄露存在性） |

字段 ↔ 列（逐字段点名，`RegistryRow`）：

| 字段 | 列 / 位置 |
| --- | --- |
| `agent_key` | 「员工标识」列（行键）；格式 `^[a-z0-9][a-z0-9._-]{0,63}$` |
| `name` | 「名称」列（筛选 `keyword` 按它模糊匹配） |
| `description` | 不出现在列；详情抽屉「工作范围」 |
| `role_key` | 「所属岗位」列（与 `my-agents-api.md` 同名的岗位键） |
| `created_by` | 「创建者」列（**管理侧新增展示**；员工侧仅用于归属判定、不展示） |
| `status` | 「状态」列（`StatusTag` 受控枚举，取值见 §2） |
| `template` | 「能力标签」列（`template.skills` 数 · `template.knowledge_scopes` 数 · `template.autonomy_level`）与详情能力包 |
| `usage.run_count` / `usage.success_rate` | 「使用统计」列（**管理侧新增**，就绪判定见 §5） |
| `last_run_at` | 「最近使用」列（`null` ⇒ 未验证 + 暂无运行记录） |
| `created_at` / `updated_at` | 详情抽屉「创建时间」 |

## 2. 状态取值（受控枚举）

`active` / `disabled` 沿用后端既有枚举；**`draft`（草稿）后端枚举未定义** —— 它是本轮界面需要的展示态。
后端补枚举前：样例里的草稿行只用于验证受控枚举与"草稿不可启停"。指标区把草稿**单独成卡**并给准数（`draft` 字段），
因此 `total = active + disabled + draft` 在界面上**可直接相加验证**（界面不做减法猜数）。

## 3. 指标统计（**未定义**）

`GET /api/v1/workforce/agents/stats` —— **后端未定义**，本轮由样例承载，接线时新增（不改既有口径）。
响应 `{total, active, disabled, draft, ran_last_7d}`：`total` / `active` / `disabled` / `draft` 为全员口径（**不随筛选变化**）；
`total` **恒等于** `active + disabled + draft`（服务端给准数，界面不做减法）；`draft` 见 §2；
`ran_last_7d` 为 `null` 时表示运行口径暂无数据 ⇒ 界面按「未验证」呈现，**不得显示 0**。

## 4. 详情（**未定义**）/ 启停（复用既有接口）

- 详情：既有 `GET /api/v1/workforce/agents/{agent_key}/config` 是**配置**口径且仅 super_admin；管理侧只读详情视图**未定义**，
  本轮用列表已加载的行 + 复用员工侧 `CapabilityPack` 渲染（不新增字段）。
- 启停：`PATCH /api/v1/workforce/agents/{agent_key}`（既有，仅 super_admin），请求体 `{"status": "active" | "disabled"}`；
  **传 `agent_key` 直接 `422`**（身份不可改）；`404` 不存在 / 跨租户；`409` 目标岗位不可用；审计 `workforce.agent.disabled`。
  界面必须走 `DangerConfirm`（输入确认词「停用」/「启用」）才发起调用；**未确认不得触发任何调用**。
- 写操作返回 `AgentWriteResult{agent_key, written, note}`（复用员工侧类型），本轮 `written` **恒为 `false`**：
  未接后端就**不允许假装写入成功**，界面按 `note` 如实告知。

## 5. 状态保真（硬要求）

| 数据情形 | 界面（`usagePresence` 判定） |
| --- | --- |
| `run_count === null` | `unverified`：标签「未验证」+「暂无运行统计」，**不显示 0** |
| `run_count === 0` | `insufficient_sample`：标签「样本不足」+「暂无运行（成功率无从计算）」，**绝不显示 0%** |
| `run_count > 0` 且 `success_rate === null` | `not_configured`：标签「未配置」+「成功率未配置」，**不显示 0% / 100%** |
| `last_run_at === null` | `unverified` +「暂无运行记录」 |

依据：`docs/contracts/role-templates.md` 验收第 5 条（未验证的数据不得以数字或成功态呈现）。

## 6. 通用口径

- 认证与越权：`401` 未认证；`403` 越权；`404` 不可见（不泄露存在性）；`422` 参数非法；`429` 限流；`5xx` 服务端。
- 前端取数：`services/agentRegistryService.ts` 是**唯一接线点**；`mode='mock'`（默认）返回 `sample: true` 样例数据，
  界面必须显示「示例数据（未接后端）」；`mode='http'` **抛"尚未接入"错误**（不静默返回空数据）；
  **筛选参数原样透传给服务端**（页面不做前端过滤）；`forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态。
- 敏感信息：响应不含 PII；样例为虚构内容，不含手机号 / 真实用户 ID / 租户 ID / 密钥（有自检用例）。