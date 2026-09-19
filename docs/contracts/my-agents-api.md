# 「我的数字员工」界面接口契约（第 4 轮）

> 状态：**草案 v1 · 2026-09-19**（第 4 轮前端交付物，DE-01 / DE-02 / DE-03 的**员工侧**部分）。
> 与 `docs/api-contract.md`（后端真源）的关系：**只引用、不修改**；已存在的接口按原文口径标注，
> 员工侧尚未有的接口在本文件**显式标为「未定义」**。字段名与 `src/features/myAgents/types.ts` **逐字一致**。

## 0. 现状口径（先读）

既有 `/api/v1/workforce/roles`、`/api/v1/workforce/agents`（含 `PATCH .../{agent_key}`）是**管理目录**口径：
**仅 `super_admin`**，其他角色（含 `employee`）一律 `403`「只有超级管理员可以管理岗位与数字员工目录」。
本轮是**员工侧**「我的数字员工」，因此 5 个能力在员工侧口径下**均未定义**，本轮由样例数据承载（页面有统一标识）。
**岗位模板数据来源于 `docs/contracts/role-templates.md`（唯一权威）；本轮以样例承载，后端模板实体待 S2 之后落地。**

## 1. 列我的数字员工（`GET /api/v1/workforce/agents` 复用；**员工侧未定义**）

| 项 | 内容 |
| --- | --- |
| 方法 / 路径 | `GET /api/v1/workforce/agents`（既有，**仅 super_admin**）；员工侧「我创建的 ∪ 共享给我的」**未定义** |
| 请求参数 | `status`（可选 `active`/`disabled`）、`role_key`（可选）、`limit`（1–200，默认 50）、`offset`（≥0） |
| 分页 | 必须分页，响应含 `total` / `limit` / `offset` |
| 错误码 | `401` 未认证；`403` 非 super_admin（既有口径）；他租户标识按 `404` 处理（不泄露存在性） |

字段 ↔ 卡片（`AgentItem`）：

| 字段 | 卡片位置 |
| --- | --- |
| `agent_key` | 行键与详情抽屉「标识」 |
| `name` | 卡片标题 + 头像首字母（`Avatar`，不引用图片文件） |
| `description` | 详情抽屉「工作范围」 |
| `role_key` | 卡片「所属岗位」；能力包的解析键 |
| `status` | 卡片状态标签（`active` → 已启用 / `disabled` → 已停用） |
| `created_by` | **不直接展示**，仅用于判定归属 |
| `created_at` / `updated_at` | 详情抽屉「创建时间」 |
| `last_run_at` | 卡片「最近使用」；**为 `null` 时必须显示「暂无运行记录 / 未验证」**（见 §7） |
| `ownership` | 卡片归属标签与分区（`mine` 我创建的 / `shared` 共享给我的）——**前端归一化**：`created_by` 与当前身份比较的结果 |
| `template` | 卡片能力标签（Skill 数 / 知识范围数 / 自治档）与详情能力包——**服务端按 `role_key` 解析后随视图下发** |

## 2. 岗位模板列表（**未定义**）

**未定义接口**：后端无模板实体（`role-templates.md` §3：`workbench_job_roles` / `workbench_digital_employees` 均无模板列，
需待 `adr.md` 签字后落库），**待 S2 之后落地**。本轮样例逐字照抄 `role-templates.md` §2 的 6 个模板，
其中 `budget_cents` 在 §2 表格中**未给出**，样例值由前端示例设定（**非契约值**）。

`RoleTemplate` 字段，**逐个点名**（对齐 `role-templates.md` §1）：`role_key`（`sales`/`hr`/`rd`/`finance`/`ops`/`admin`）、
`name`（岗位中文名）、`mission`、`skills[]`、`tools[]`、`knowledge_scopes[]`、
`memory_policy{ scope, write_categories[] }`、`autonomy_level`（`approval_for_all`/`approval_for_risky`/`full_auto`）、
`budget_cents`（**整数分**）。`org_ref` 为预留位、本期不填，故不建模。

## 3. 创建（从岗位模板创建，DE-01）

`POST /api/v1/workforce/agents`（既有，**仅 super_admin**）；员工侧**未定义**。
既有请求体：`{"agent_key","name","role_key","description"}`；`409` 标识重复 / 所属岗位不可用；`422` 参数非法。
**员工侧差异（未定义）**：`agent_key` 应由服务端生成，能力包**由模板继承**（服务端读模板 → 生成 Skill 绑定 /
知识绑定 / 记忆策略 / 自治档），客户端**只提交** `CreateAgentInput{ name, role_key, description }`
（表单「工作范围」→ 字段 `description`）。能力**只授予、不放大**：模板能力必须 ⊆ 使用者权限。

## 4. 详情（**员工侧未定义**）

既有 `GET /api/v1/workforce/agents/{agent_key}/config`（**仅 super_admin**，`404` 不存在/跨租户）。
员工侧只读详情**未定义**；本轮列表视图已含全部展示字段，详情抽屉直接用列表已加载的 `AgentItem`。

## 5. 停用（`PATCH /api/v1/workforce/agents/{agent_key}` 复用；**员工侧未定义**）

既有：请求体允许 `name` / `description` / `role_key` / `status`；**传 `agent_key` 直接 `422`**（身份不可改）；
`status` 只有 `active` / `disabled`，**停用不删除**（不撤销既有绑定、不影响历史任务与运行）；变更写审计 `workforce.agent.disabled`。
界面：必须走 `DangerConfirm`（输入确认词「停用」）才发起调用。员工侧停用「我创建的」**未定义**。

## 6. 更新（配置，"查看详情"之外的写入路径）

同 §5 的 `PATCH`；员工侧**未定义**。入参 `UpdateAgentInput{ agent_key, name, description }`：只改名称与工作范围，
**能力包不可改**（改能力属"换岗 / 升级模板"，另立动作）。

## 7. 状态保真与写操作口径（硬要求）

- `last_run_at === null` ⇒ 界面必须显示「暂无运行记录 / 未验证」（`DataPresence=unverified`），
  **不得显示 `0`、不得显示"成功"**（`role-templates.md` 验收第 5 条）。
- 写操作返回 `AgentWriteResult{ agent_key, written, note }`，本轮 `written` **恒为 `false`**：
  未接后端就**不允许假装写入成功**，界面按 `note` 如实告知（"本轮为示例数据（未接后端），操作未写入后端"）。

## 8. 通用口径

- 认证与越权：未认证 `401`；越权 `403`；跨租户 / 不可见 `404`（不泄露存在性）；`422` 参数非法；`429` 限流；`5xx` 服务端。
- 前端取数：`services/myAgentsService.ts` 是**唯一接线点**。`mode='mock'`（默认）返回样例信封
  （`sample: true` + `items[]`；信封类型定义在共享模块 `src/utils/serviceKit.ts`），界面必须显示「示例数据（未接后端）」；
  `mode='http'` **抛"尚未接入"错误**（不静默返回空数组）；`forbidden` 与其它失败分别映射为界面 `forbidden` / `error` 态。
- 敏感信息：响应不含 PII；样例数据为虚构内容，不含手机号 / 用户 ID / 租户 ID / 密钥（有自检用例）。