// 首页前端类型：与 /api/v1/tasks、/api/v1/workforce/agents、/api/v1/content-tasks 契约一致。
export type HomeRiskLevel = 'low' | 'medium' | 'high'
export type HomeDraftStatus = 'generating' | 'reviewing' | 'confirmed' | 'failed'

export interface HomeEmployee {
  agent_key: string
  name: string
  description: string
  role_key: string
  status: string
  created_by: string
  created_at: string | null
  updated_at: string | null
}

export interface HomeEmployeeList {
  items: HomeEmployee[]
  total: number
  limit: number
  offset: number
}

export interface HomeDraft {
  task_id: string
  tenant_id?: string
  created_by: string
  topic: string
  status: HomeDraftStatus
  run_id: string
  created_at: string
  updated_at: string
}

export interface HomeDraftList {
  items: HomeDraft[]
  page: number
  page_size: number
  total: number
  has_next: boolean
}

export interface HomeCreatedTask {
  id: string
  title: string
  status: string
  risk_level: string
}

export interface HomeErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface HomeState {
  employees: HomeEmployee[]
  employeesLoading: boolean
  employeesError: HomeErrorShape | null
  drafts: HomeDraft[]
  draftsLoading: boolean
  draftsError: HomeErrorShape | null
  submitting: boolean
  submitError: HomeErrorShape | null
  toast: string | null
}

export const RISK_LABELS: Record<HomeRiskLevel, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

export const DRAFT_STATUS_LABELS: Record<HomeDraftStatus, string> = {
  generating: '生成中',
  reviewing: '待自检',
  confirmed: '已确认',
  failed: '失败',
}

// 取不到标签时回落显示原值，避免出现空白。
export function draftStatusLabel(status: string): string {
  return DRAFT_STATUS_LABELS[status as HomeDraftStatus] ?? status
}

export const HOME_DRAFT_LIMIT = 4

export function formatDraftTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
