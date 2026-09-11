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

export const DIRECTORY_STATUS_LABELS: Record<DirectoryStatus, string> = {
  active: '启用',
  disabled: '停用',
}

// 取不到标签时回落显示原值，避免出现空白。
export function directoryStatusLabel(status: string): string {
  return DIRECTORY_STATUS_LABELS[status as DirectoryStatus] ?? status
}
