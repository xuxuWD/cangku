/**
 * 「数字员工注册中心」模块类型（第 5 轮，AD-01 管理后台视角）。
 *
 * 与员工侧（第 4 轮 `features/myAgents`）是**同一实体的两个视角**：
 *  - 共享字段用 `Pick<AgentItem, …>` 取，**从类型层面**保证字段名逐字一致（不另抄第二份定义）；
 *  - 管理侧**多**：创建者（`created_by` 本就在实体上，员工侧不展示）+ 使用统计（`usage`）；
 *  - 管理侧**不含** `ownership`（那是员工侧"我创建的 / 共享给我的"视角字段）。
 * 字段口径见 `docs/contracts/agent-registry-api.md`（与 `my-agents-api.md` 同源，命名必须一致）。
 */
import type { DataPresence, StatusTone } from '../../components'
import type { AgentItem, AgentStatus, RoleKey } from '../myAgents/types'

/**
 * 管理侧状态：在既有 `active` / `disabled` 之外，界面还需要"草稿"展示态。
 * **`draft` 是后端枚举未定义的值**（见契约 §2），后端补枚举前它只用于样例与界面演示。
 */
export type RegistryAgentStatus = AgentStatus | 'draft'

/** 状态 → 中文标签（受控枚举，界面不得随手写状态字符串）。 */
export const AGENT_STATUS_LABEL: Record<RegistryAgentStatus, string> = {
  active: '已启用',
  disabled: '已停用',
  draft: '草稿',
}

/** 状态 → 语义色（受控枚举，禁止传颜色值）。 */
export const AGENT_STATUS_TONE: Record<RegistryAgentStatus, StatusTone> = {
  active: 'success',
  disabled: 'neutral',
  draft: 'warning',
}

/** 与员工侧逐字一致的共享字段（`Pick` 保证同名同义，字段集合即两份契约的公共部分）。 */
export type RegistrySharedFields = Pick<
  AgentItem,
  | 'agent_key'
  | 'name'
  | 'description'
  | 'role_key'
  | 'created_by'
  | 'created_at'
  | 'updated_at'
  | 'last_run_at'
  | 'template'
>

/** 使用统计（管理侧新增）：非就绪时**不得**显示 `0` 或 `100%`。 */
export interface AgentUsageStats {
  /** 运行次数；`null` = 拿不到数据（**不得写成 0**）。 */
  run_count: number | null
  /** 成功率（0–1）；`null` = 无数据（**不得写成 0 / 100%**）。 */
  success_rate: number | null
}

/** 列表行 = 共享字段 + 管理侧状态 + 使用统计。 */
export type RegistryRow = RegistrySharedFields & {
  status: RegistryAgentStatus
  usage: AgentUsageStats
}

/** 指标统计（管理侧大盘；**不受筛选影响**）。 */
export interface RegistryStatsSummary {
  /** 全部：总数口径（后端无草稿枚举时 = `active + disabled`）。 */
  total: number
  active: number
  disabled: number
  /**
   * 草稿数；**`null` = 后端未定义草稿枚举 ⇒ 本批如实未接入**（不得显示 `0`：
   * `0` 会被读成"确实没有草稿"，而事实是"后端没有这个概念"）。见契约 §2。
   */
  draft: number | null
  /**
   * 最近 7 天有运行的员工数；`null` = 运行口径暂无数据（**不得显示 0**）。
   */
  ran_last_7d: number | null
}

/** 统计信封：`sample` 为样例硬标记（与列表信封同口径；真实数据必须为 `false`）。 */
export interface RegistryStatsPayload extends RegistryStatsSummary {
  sample: boolean
}

/** 筛选条件：**原样透传给服务端**，页面不得在前端过滤。 */
export interface RegistryFilters {
  role_key?: RoleKey
  status?: RegistryAgentStatus
  /** 创建者标识（模糊匹配）。 */
  created_by?: string
  /** 名称关键字（模糊匹配）。 */
  keyword?: string
}

/** 列表查询 = 筛选 + 分页（服务端分页语义：`items` 只含当前页）。 */
export interface RegistryQuery extends RegistryFilters {
  page: number
  pageSize: number
}

/** 列表信封：`items / total / limit / offset` 与后端列表接口同形，另带样例硬标记。 */
export interface RegistryListPayload {
  /** `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；`false` = 后端真实数据。 */
  sample: boolean
  items: RegistryRow[]
  total: number
  limit: number
  offset: number
}

/** 管理侧表格默认分页大小。 */
export const REGISTRY_PAGE_SIZE = 10

/** 空筛选（受控初始值）。 */
export const NO_FILTERS: RegistryFilters = {}

/**
 * 使用统计可用性（状态保真）：
 * - 拿不到运行次数 ⇒ `unverified`（未验证）；
 * - 运行 0 次 ⇒ `insufficient_sample`（**成功率无从计算**，绝不能渲染成 0%）；
 * - 有运行但成功率缺失 ⇒ `not_configured`（未配置）。
 */
export function usagePresence(usage: AgentUsageStats): DataPresence {
  if (usage.run_count === null) return 'unverified'
  if (usage.run_count === 0) return 'insufficient_sample'
  if (usage.success_rate === null) return 'not_configured'
  return 'ready'
}

/** 最近使用可用性：无运行记录 ⇒ `unverified`（不显示 0、不显示成功态）。 */
export function lastRunPresence(row: RegistrySharedFields): DataPresence {
  return row.last_run_at === null ? 'unverified' : 'ready'
}

/** 运行口径统计可用性（"最近 7 天有运行"这张卡）。 */
export function ranLast7dPresence(stats: RegistryStatsSummary): DataPresence {
  return stats.ran_last_7d === null ? 'unverified' : 'ready'
}

/**
 * 草稿口径可用性：后端 `status` 库列有 `CHECK (status IN ('active','disabled'))`，
 * **没有 `draft` 枚举** ⇒ http 模式下 `draft = null`，界面按「未验证」呈现（不得显示 `0`）。
 */
export function draftPresence(stats: RegistryStatsSummary): DataPresence {
  return stats.draft === null ? 'unverified' : 'ready'
}