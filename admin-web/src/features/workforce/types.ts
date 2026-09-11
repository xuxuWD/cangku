// 岗位与数字员工清单前端类型：与服务端 GET /api/v1/workforce/roster 契约保持一致。
export interface WorkforceRosterItem {
  key: string
  role_knowledge_base_ids: string[]
  agent_knowledge_base_ids: string[]
  task_count: number
}

export interface WorkforceRosterResponse {
  items: WorkforceRosterItem[]
  total: number
}

export interface WorkforceErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface WorkforceState {
  items: WorkforceRosterItem[]
  total: number
  loading: boolean
  error: WorkforceErrorShape | null
}

// 知识范围为空时统一显示「未绑定」，避免出现空白单元格。
export function scopeLabel(ids: string[]): string {
  return ids.length > 0 ? ids.join('、') : '未绑定'
}
