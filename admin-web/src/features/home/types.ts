// 首页前端类型：与 /api/v1/tasks、/api/v1/workforce/agents、/api/v1/conversations 契约一致。
// 会话类型直接复用 features/conversation 的契约类型，避免两处字段漂移。
import type { Conversation, ConversationErrorShape } from '../conversation/types'

export type HomeRiskLevel = 'low' | 'medium' | 'high'

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

export interface HomeCreatedTask {
  id: string
  title: string
  status: string
  risk_level: string
}

export type HomeErrorShape = ConversationErrorShape

export interface HomeState {
  employees: HomeEmployee[]
  employeesLoading: boolean
  employeesError: HomeErrorShape | null
  conversations: Conversation[]
  conversationsLoading: boolean
  conversationsError: HomeErrorShape | null
  submitting: boolean
  submitError: HomeErrorShape | null
  taskSubmitting: boolean
  taskError: HomeErrorShape | null
  toast: string | null
}

export const RISK_LABELS: Record<HomeRiskLevel, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

// 首页只展示最近几条会话，与后端的 limit 分页口径一致。
export const HOME_CONVERSATION_LIMIT = 4
