// 对话前端类型：与服务端 /api/v1/conversations 契约逐字对齐（字段名不得自造）。
// 契约：docs/api-contract.md「对话式 AI 员工平台（P1）」；后端模型见 app/main.py。

export type ConversationStatus = 'active' | 'archived'
export type ConversationRole = 'user' | 'assistant' | 'tool' | 'system'

export interface Conversation {
  conversation_id: string
  agent_key: string | null
  title: string
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface ConversationList {
  items: Conversation[]
  total: number
  limit: number
  offset: number
}

export interface ConversationMessage {
  message_id: string
  conversation_id: string
  role: string
  content: string
  // P1 的助手消息都是确定性桩；后端显式标注，界面必须原样呈现，不得伪装成真实模型输出。
  stub: boolean
  tool_name: string | null
  tool_call_id: string | null
  created_at: string | null
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[]
  messages_total: number
  messages_limit: number
  messages_offset: number
}

export interface MessageCreateResponse {
  message_id: string
  conversation_id: string
  stub: boolean
  // 202 待批响应（stub=false）不含 reply；重取会话详情即可看到落库消息。
  reply?: ConversationMessage
  // §3.7 Y2 / 契约变更点 1：201 响应新增可选 run_id；202 另含 status 与 approval_id。
  run_id?: string | null
  status?: 'pending_approval'
  approval_id?: string
}

export interface ConversationErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface ConversationState {
  conversations: Conversation[]
  conversationsTotal: number
  conversationsLoading: boolean
  conversationsError: ConversationErrorShape | null
  statusFilter: ConversationStatus | 'all'
  listOffset: number
  detail: ConversationDetail | null
  detailLoading: boolean
  detailError: ConversationErrorShape | null
  createError: ConversationErrorShape | null
  sending: boolean
  sendError: ConversationErrorShape | null
  archiving: boolean
  toast: string | null
}

// 分页口径与服务端一致：limit 1–200、offset ≥ 0，响应回报命中总数。
export const CONVERSATION_PAGE_SIZE = 20
export const MESSAGE_PAGE_SIZE = 50
export const MAX_MESSAGE_LENGTH = 8000

// 页面级显式声明：默认后端（mock）不接真实模型、不执行任何工具，助手回复是 stub 桩回复。
// P2a 段二起，带 `Idempotency-Key` 的**结构化工具调用**消息可能触发真实执行（受九步闸门约束）。
export const STUB_NOTICE =
  '默认阶段未接入真实模型：普通消息的助手回复均为后端标注 stub 的确定性桩回复，仅用于打通会话、权限与审计链路，请勿当作真实模型输出；带幂等键的结构化工具调用消息会按九步闸门执行或转为待审批。'

export const CONVERSATION_STATUS_LABELS: Record<ConversationStatus, string> = {
  active: '进行中',
  archived: '已归档',
}

// 取不到标签时回落显示原值，避免出现空白。
export function conversationStatusLabel(status: string): string {
  return CONVERSATION_STATUS_LABELS[status as ConversationStatus] ?? status
}

export const ROLE_LABELS: Record<ConversationRole, string> = {
  user: '我',
  assistant: '数字员工',
  tool: '工具',
  system: '系统',
}

export function roleLabel(role: string): string {
  return ROLE_LABELS[role as ConversationRole] ?? role
}

// 标题为空是真实状态（会话可无标题），这里只做展示回落，不编造内容。
export function conversationTitle(title: string): string {
  return title.trim() || '未命名会话'
}

export function formatMessageTime(value: string | null): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
