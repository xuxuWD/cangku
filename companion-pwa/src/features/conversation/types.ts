// 手机伴侣端对话面板类型：与服务端 /api/v1/conversations 契约逐字对齐（字段名不得自造）。
// 契约：docs/api-contract.md「对话式 AI 员工平台（P1）」「实时流与过程事件（P2b）」。
// 说明（P2c-5 实施裁定）：本模块是网页管理台读端的**最小复制实现**（§2.12），
// 只保留 PWA 面板需要的子集：无 run 解析、无舞台、折叠条只渲染帧标签。

export type ConversationStatus = 'active' | 'archived'

export interface Conversation {
  conversation_id: string
  agent_key: string | null
  title: string
  status: string
  mode: string
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
  /** 后端显式标注的桩回复；界面必须原样呈现，不得伪装成真实模型输出。 */
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
  reply?: ConversationMessage
  run_id?: string | null
  status?: 'pending_approval'
  approval_id?: string
}

/** 一帧流帧（契约「实时流与过程事件（P2b）」冻结格式；`run_id` 为 P2c-2 只增字段）。 */
export interface StreamFrame {
  seq: number
  kind: string
  payload: Record<string, unknown>
  is_terminal: boolean
  run_id?: string
}

/** 读端连接态（四态：idle=未开启、connecting=建立中、streaming=接收中、closed/error=终态）。 */
export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'closed' | 'error'

// 分页口径与服务端一致：limit 1–200、offset ≥ 0，响应回报命中总数。
export const CONVERSATION_PAGE_SIZE = 20
export const MESSAGE_PAGE_SIZE = 50
export const MAX_MESSAGE_LENGTH = 8000

// 帧 `kind` 中文标签（复制自网页管理台：运行事件十种 + 消息两类 + 系统告知）；未知取值不猜测。
const RUN_EVENT_LABELS: Record<string, string> = {
  'plan.created': '计划已创建',
  'step.started': '步骤开始',
  'tool.call': '工具调用',
  'tool.result': '工具结果',
  'approval.requested': '请求审批',
  'approval.decided': '审批已决议',
  'checkpoint.saved': '保存检查点',
  'run.paused': '运行暂停',
  'run.failed': '运行失败',
  'run.completed': '运行完成',
}

export function frameKindLabel(kind: string): string {
  if (kind === 'message.user') return '用户消息已落定'
  if (kind === 'message.assistant') return '助手消息已落定'
  if (kind === 'stream.unavailable') return '流已停止（系统告知）'
  return RUN_EVENT_LABELS[kind] ?? '其他事件'
}

const ROLE_LABELS: Record<string, string> = {
  user: '我',
  assistant: '数字员工',
  tool: '工具',
  system: '系统',
}

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role
}

const STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  archived: '已归档',
}

export function conversationStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

// 标题为空是真实状态（会话可无标题），这里只做展示回落，不编造内容。
export function conversationTitle(title: string): string {
  return title.trim() || '未命名会话'
}

export function formatMessageTime(value: string | null): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}