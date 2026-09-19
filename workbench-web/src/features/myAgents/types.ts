/**
 * 「我的数字员工」模块类型（第 4 轮）。
 *
 * 命名口径：
 *  - **数字员工字段**逐字沿用后端契约既有字段名（`docs/api-contract.md` §岗位与数字员工目录：
 *    `agent_key` / `name` / `description` / `role_key` / `status` / `created_by` / `created_at` / `updated_at`）；
 *  - **岗位模板 / 能力包字段**逐字对齐 `docs/contracts/role-templates.md` §1
 *    （`role_key` / `mission` / `skills` / `tools` / `knowledge_scopes` / `memory_policy` /
 *    `autonomy_level` / `budget_cents`；`org_ref` 为预留位，本期不填故不建模）。
 *
 * 与本模块契约 `docs/contracts/my-agents-api.md` **逐字一致**（改一处必须同时改另一处）。
 */
import type { DataPresence } from '../../components'

/** 岗位键：逐字对齐 `role-templates.md` §2 的首批 6 个模板。 */
export type RoleKey = 'sales' | 'hr' | 'rd' | 'finance' | 'ops' | 'admin'

/** 自治档：逐字对齐 `role-templates.md` §1 的既有枚举（迁移 023）。 */
export type AutonomyLevel = 'approval_for_all' | 'approval_for_risky' | 'full_auto'

/** 记忆策略（`role-templates.md` §1 的 `memory_policy`：scope 上限 + 允许写入的类别）。 */
export interface MemoryPolicy {
  /** scope 上限。 */
  scope: 'user' | 'role' | 'project' | 'organization'
  /** 允许写入的类别（受控键名，不含正文）。 */
  write_categories: string[]
}

/** 岗位模板（能力包）：选岗位即自动继承。 */
export interface RoleTemplate {
  role_key: RoleKey
  /** 岗位中文名（`role-templates.md` §2 表格"岗位"列）。 */
  name: string
  /** 一句话使命。 */
  mission: string
  /** 默认绑定的 Skill（`skill_key@版本`）。 */
  skills: string[]
  /** 默认工具 / MCP 面（白名单）。 */
  tools: string[]
  /** 知识库范围（库级）。 */
  knowledge_scopes: string[]
  memory_policy: MemoryPolicy
  autonomy_level: AutonomyLevel
  /** 单任务预算上限（**整数分**，非浮点）。 */
  budget_cents: number
}

/** 数字员工状态：沿用后端目录 `status` 枚举（`active` / `disabled`，停用不删除）。 */
export type AgentStatus = 'active' | 'disabled'

/** 归属：我创建的 / 他人创建后共享给我。 */
export type AgentOwnership = 'mine' | 'shared'

export interface AgentItem {
  /** 数字员工标识（后端字段同名）。 */
  agent_key: string
  name: string
  description: string
  /** 所属岗位（后端字段同名）。 */
  role_key: RoleKey
  status: AgentStatus
  /** 创建者标识（后端字段同名；**不在界面展示原始 ID**，只用于判定归属）。 */
  created_by: string
  created_at: string
  updated_at: string
  /**
   * 最近一次运行时间（ISO 8601）。
   * **无运行记录必须为 `null`** —— 不得填 `0`、不得造时间（状态保真，见本模块契约 §7）。
   */
  last_run_at: string | null
  /** 归属（前端归一化：服务端下发的 `created_by` 与当前身份比较的结果）。 */
  ownership: AgentOwnership
  /** 能力包：服务端按 `role_key` 解析后随视图下发（本轮样例直接内联）。 */
  template: RoleTemplate
}

/** 创建入参（表单「工作范围」→ 请求字段 `description`，沿用后端既有字段名）。 */
export interface CreateAgentInput {
  name: string
  role_key: RoleKey
  description: string
}

/** 更新入参（沿用后端既有字段：名称与描述可改，`agent_key` 不可改）。 */
export interface UpdateAgentInput {
  agent_key: string
  name: string
  description: string
}

/**
 * 写操作的受理结果。
 * `written` 恒为 `false`：本轮未接后端，**不允许假装写入成功**（界面据此给出如实提示）。
 */
export interface AgentWriteResult {
  agent_key: string
  written: false
  /** 如实说明本轮发生了什么、没发生什么。 */
  note: string
}

/**
 * 运行记录可用性（状态保真）：有运行时间才 `ready`，否则一律 `unverified`。
 * 绝不用 `0` 表示"没有运行记录"，也绝不显示"成功"。
 */
export function runsPresence(agent: AgentItem): DataPresence {
  return agent.last_run_at === null ? 'unverified' : 'ready'
}