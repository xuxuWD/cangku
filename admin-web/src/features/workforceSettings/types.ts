// 岗位与数字员工目录前端类型：与服务端 /api/v1/workforce/{roles,agents,candidates} 契约一致。
export type DirectoryStatus = 'active' | 'disabled'

export interface JobRole {
  role_key: string
  name: string
  description: string
  status: DirectoryStatus
  created_by: string
  created_at: string | null
  updated_at: string | null
}

export interface DigitalEmployee {
  agent_key: string
  name: string
  description: string
  role_key: string
  status: DirectoryStatus
  created_by: string
  created_at: string | null
  updated_at: string | null
}

export interface DirectoryList<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface WorkforceCandidates {
  roles: string[]
  agents: string[]
}

// 数字员工配置：与服务端 GET/PATCH /api/v1/workforce/agents/{agent_key}/config 契约一致。
export interface AgentMemoryPolicy {
  short_term_enabled?: boolean
  short_term_turns?: number
}

export interface AgentConfig {
  agent_key: string
  system_prompt: string
  model_key: string
  temperature: number
  tool_allowlist: string[]
  memory_policy: Record<string, unknown>
  autonomy_level: string
  risk_threshold: string
  approval_timeout_minutes: number
  daily_budget_cents: number
  updated_at: string | null
}

export interface AgentConfigUpdate {
  system_prompt: string
  model_key: string
  temperature: number
  tool_allowlist: string[]
  memory_policy: AgentMemoryPolicy
  autonomy_level: string
  risk_threshold: string
  approval_timeout_minutes: number
  daily_budget_cents: number
}

export interface DirectoryErrorShape {
  status: number
  message: string
  retryable: boolean
}

export type DirectoryTab = 'roles' | 'agents'

export interface DirectoryState {
  tab: DirectoryTab
  roles: DirectoryList<JobRole>
  agents: DirectoryList<DigitalEmployee>
  candidates: WorkforceCandidates
  loading: boolean
  error: DirectoryErrorShape | null
  saving: boolean
  formError: DirectoryErrorShape | null
  toast: string | null
}

// 单页取满上限（200）：目录规模有限，翻页留给接口层；超出时会显式提示只显示前 200 项。
export const PAGE_LIMIT = 200

// 前端只做提示与拦截，后端才是权威（超长一律 422）。
export const MAX_SYSTEM_PROMPT_LENGTH = 8000
export const MIN_APPROVAL_TIMEOUT_MINUTES = 5
export const MAX_APPROVAL_TIMEOUT_MINUTES = 10080
export const MAX_SHORT_TERM_TURNS = 50

export const AUTONOMY_LEVELS = ['approval_for_all', 'approval_for_risky', 'full_auto'] as const

// 自治等级 = 决定「是否需要人批」，不决定「是否绕开权限判定」，界面上必须讲清楚。
export const AUTONOMY_LEVEL_LABELS: Record<string, string> = {
  approval_for_all: '每个工具都要批',
  approval_for_risky: '只批高风险',
  full_auto: '除极高风险外免批',
}

export const AUTONOMY_LEVEL_HINTS: Record<string, string> = {
  approval_for_all: '每个工具调用都需要人工审批通过后才执行。',
  approval_for_risky: '只有风险不低于风险阈值的动作需要人工审批，低风险动作直接执行。',
  full_auto: '免人工审批；但「极高（critical）」风险动作任何自治等级都必须审批，后端写死不可豁免。仍受权限判定与后端闸门约束，不能做操作者本人无权做的事。',
}

// `full_auto` 是特权而非默认：选中时必须显式提示「仅超管可设 + 写审计」，不得静默授予。
export const FULL_AUTO_NOTICE = 'full_auto 除「极高（critical）」风险外免人工审批；critical 任何自治等级都必须审批，不可豁免。仅超级管理员可设置，且该变更会写入审计；它只决定「是否需要人批」，不决定「是否绕开权限判定」。'

// `model_key` 为空是合法状态（后端语义 = 用默认模型），界面上要写明而不是留空。
export const EMPTY_MODEL_KEY_LABEL = '未指定（用默认模型）'

// 非超管读取配置会 403；给配置区一句专用文案，避免只显示目录权限文案或空白。
export const CONFIG_FORBIDDEN_MESSAGE = '仅超级管理员可查看与修改数字员工配置。'

export const RISK_THRESHOLD_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '极高（任何自治等级都必须审批）',
}

export const DIRECTORY_STATUS_LABELS: Record<DirectoryStatus, string> = {
  active: '启用',
  disabled: '停用',
}

// 取不到标签时回落显示原值，避免出现空白。
export function directoryStatusLabel(status: string): string {
  return DIRECTORY_STATUS_LABELS[status as DirectoryStatus] ?? status
}
