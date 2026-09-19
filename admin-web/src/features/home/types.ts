// 首页前端类型：与 /api/v1/tasks、/api/v1/workforce/agents、/api/v1/conversations 契约一致。
// 会话类型直接复用 features/conversation 的契约类型，避免两处字段漂移。
import type { Conversation, ConversationErrorShape } from '../conversation/types'
import type { InboxItem } from '../inbox/types'

// 风险刻度与后端 `RiskLevel` 一致（迁移 025 起为四档）；前端只做提示，判定一律以后端为准。
export type HomeRiskLevel = 'low' | 'medium' | 'high' | 'critical'

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
  /** 会话**命中总数**（服务端口径；首页不按左栏筛选走，如实取全量）。 */
  conversationsTotal: number
  conversationsLoading: boolean
  conversationsError: HomeErrorShape | null
  /** 未读通知（首页「等你处理」区块；与通知页同源端点）。 */
  inbox: InboxItem[]
  inboxUnread: number
  inboxLoading: boolean
  inboxError: HomeErrorShape | null
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
  critical: '极高（仅负责人可发起）',
}

// 首页只展示最近几条会话，与后端的 limit 分页口径一致。
export const HOME_CONVERSATION_LIMIT = 4

// 首页「等你处理」只展示最近几条未读通知；总数以服务端 `unread_count` 为准。
export const HOME_INBOX_LIMIT = 4

/** 「试试这样问」示例：只是**输入建议**，点一下填进输入框，用户可改后再发。 */
export const HOME_EXAMPLE_PROMPTS: string[] = [
  '把本周客户反馈整理成一页要点',
  '起草一份明天开会的议程',
  '把这段话改得更礼貌一些',
]
