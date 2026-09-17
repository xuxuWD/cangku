// 对话前端类型：与服务端 /api/v1/conversations 契约逐字对齐（字段名不得自造）。
// 契约：docs/api-contract.md「对话式 AI 员工平台（P1）」；后端模型见 app/main.py。
import { RUN_EVENT_LABELS } from '../runDetail/types'

export type ConversationStatus = 'active' | 'archived'
export type ConversationRole = 'user' | 'assistant' | 'tool' | 'system'
/** 每会话模式（P2c-4 §2.9，与后端受控枚举逐字一致：`ask` / `plan` / `goal` / `craft`）。 */
export type ConversationMode = 'ask' | 'plan' | 'goal' | 'craft'

export interface Conversation {
  conversation_id: string
  agent_key: string | null
  title: string
  status: string
  /** P2c-4 只增字段：默认 `craft`（＝改造前行为）。 */
  mode: ConversationMode
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
  /** P2c-6 只增字段：发言账号 id；助手 / 工具 / 系统恒 `null`，存量行 `null` ⇒ 展示回退「发起人」。 */
  sender_id?: string | null
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
  /** 结构化调用未产生运行时的如实告知（后端未装配真实执行 ⇒ 回落桩路径）；下次发送时清空。 */
  streamNotice: string | null
  archiving: boolean
  toast: string | null
  // P2c-6 会话协作：参与者名单（发言人回溯与分享区块共用同一份数据；不猜、不本地造名单）。
  participants: ConversationMember[]
  /** 参与者**命中总数**（服务端口径；`> participants.length` ⇒ 本页之外还有成员，界面如实告知）。 */
  participantsTotal: number
  participantsLoading: boolean
  participantsError: ConversationErrorShape | null
  sharing: boolean
  shareError: ConversationErrorShape | null
}

// 分页口径与服务端一致：limit 1–200、offset ≥ 0，响应回报命中总数。
export const CONVERSATION_PAGE_SIZE = 20
export const MESSAGE_PAGE_SIZE = 50
export const MAX_MESSAGE_LENGTH = 8000

// ---------------------------------------------------------------- P2c-1 实时流（消费 P2b 契约）

/**
 * 一帧流帧（契约「实时流与过程事件（P2b）」冻结格式：`id`/`event`/`data` 三字段，
 * `data` 为 `{seq, kind, payload, is_terminal}`）。
 */
export interface StreamFrame {
  seq: number
  kind: string
  payload: Record<string, unknown>
  is_terminal: boolean
  /** 帧所属运行号（P2c-2 契约「只增」）：历史会话与多客户端据此解析「当前 run」。 */
  run_id?: string
}

/** 读端连接态（四态：idle=未开启、connecting=建立中、streaming=接收中、closed/error=终态）。 */
export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'closed' | 'error'

/** 帧 `kind` 的中文标签：消息两类与系统告知单独命名，过程事件复用运行详情页的十种枚举标签。 */
export function frameKindLabel(kind: string): string {
  if (kind === 'message.user') return '用户消息已落定'
  if (kind === 'message.assistant') return '助手消息已落定'
  if (kind === 'stream.unavailable') return '流已停止（系统告知）'
  return RUN_EVENT_LABELS[kind] ?? '其他事件'
}

// 页面级显式声明：默认后端（mock）不接真实模型、不执行任何工具，助手回复是 stub 桩回复。
// P2a 段二起，带 `Idempotency-Key` 的**结构化工具调用**消息可能触发真实执行（受九步闸门约束）。
export const STUB_NOTICE =
  '默认阶段未接入真实模型：普通消息的助手回复均为后端标注 stub 的确定性桩回复，仅用于打通会话、权限与审计链路，请勿当作真实模型输出；带幂等键的结构化工具调用消息会按九步闸门执行或转为待审批。'

export const CONVERSATION_STATUS_LABELS: Record<ConversationStatus, string> = {
  active: '进行中',
  archived: '已归档',
}

// 模式中文标签与提示（文案只描述服务端已定义的行为，不承诺额外能力）。
export const CONVERSATION_MODE_LABELS: Record<ConversationMode, string> = {
  ask: '只问答',
  plan: '先计划后执行',
  goal: '目标驱动',
  craft: '完整执行',
}

export const CONVERSATION_MODE_HINTS: Record<ConversationMode, string> = {
  ask: '只问答：服务端会拒绝一切真实执行（纯文本问答仍可用）。',
  plan: '先计划后执行：真实调用一律先落待审批（等价「一律审批」）。',
  goal: '目标驱动：执行照常，按数字员工的自治等级判定是否需要审批。',
  craft: '完整执行（默认）：与改造前行为一致，按自治等级判定是否需要审批。',
}

export function conversationModeLabel(mode: string): string {
  return CONVERSATION_MODE_LABELS[mode as ConversationMode] ?? mode
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

// ---------------------------------------------------------------- P2c-4（模式 / 导出 / 物理删除 / 结构判定）

/**
 * 运行**结构判定**（P2c-4 §2.5）：三条件全满足 ⇒ `met`。判定由**服务端**给出，
 * 前端只渲染结论与三个 `checks`，不自行复算规则。
 */
export interface RunAcceptance {
  run_id: string
  verdict: 'met' | 'unmet'
  checks: { steps_complete: boolean; no_pending_approvals: boolean; finish_reason_ok: boolean }
  steps: { completed: number; total: number }
  pending_approvals: number
  finish_reason: string | null
  status: string
}

export interface ExportConversation extends Conversation {
  messages: Array<Omit<ConversationMessage, 'conversation_id'>>
  messages_total: number
}

export interface ConversationExportPage {
  exported_at: string
  limit: number
  offset: number
  conversations: ExportConversation[]
  total_conversations: number
  total_messages: number
  truncated: boolean
  limit_reason: string | null
}

export interface ConversationDeletionResult {
  conversation_id: string
  deleted: boolean
  message_count: number
  frame_count: number
  stream_state_count: number
  idempotency_count: number
}

// 与服务端一致：每页 500 会话；客户端最多合并 100 页（= 服务端 5 万条上限口径）。
export const EXPORT_PAGE_SIZE = 500
export const EXPORT_MAX_PAGES = 100

// ---------------------------------------------------------------- P2c-6 会话协作（分享与多端协同）

/** 成员授权档（与后端受控枚举逐字一致：`read` / `write`）。 */
export type MemberPermission = 'read' | 'write'

/**
 * 参与者条目（`GET .../members` 的 `items[]`）：发起人列首位（`permission="owner"` / `is_owner`）。
 * `display_name` / `role` 由服务端按账号解析（账号缺失 ⇒ 回退 `member_id` / `null`，不编造）。
 */
export interface ConversationMember {
  member_id: string
  display_name: string
  role: string | null
  permission: MemberPermission | 'owner'
  is_owner: boolean
  added_by: string | null
  created_at: string | null
}

export interface ConversationMemberList {
  items: ConversationMember[]
  /** 命中总数（不静默截断：`total > items.length` ⇒ 还有下一页）。 */
  total: number
  /** 分页（2026-09-18 收尾裁决 B，响应**只增**）：服务端实际生效的页大小与偏移。 */
  limit: number
  offset: number
}

export interface ConversationMemberGrant {
  conversation_id: string
  member_id: string
  permission: MemberPermission
}

export const MEMBER_PERMISSION_LABELS: Record<string, string> = {
  owner: '发起人',
  read: '仅查看',
  write: '可发言',
}

export function memberPermissionLabel(permission: string): string {
  return MEMBER_PERMISSION_LABELS[permission] ?? permission
}

/** 当前登录账号 id（与 `api.ts` 的请求头同源：`VITE_USER_ID`，缺省 `admin`）。 */
export const CURRENT_USER_ID = import.meta.env.VITE_USER_ID || 'admin'

/**
 * 消息气泡的发言者标签：**按 `sender_id` 回溯**，查不到就如实回落，绝不冒充当前用户。
 *
 *  * 非 `user` 消息（助手 / 工具 / 系统）仍按角色显示；
 *  * `sender_id == 我` ⇒「我」；命中参与者名单 ⇒ 其 `display_name`；
 *  * `sender_id` 为空（**存量行 `NULL`**）⇒「发起人」（零破坏的回退口径）；
 *  * 有 `sender_id` 但不在本页名单内（如已被撤销）⇒「会话成员」（不编造姓名）。
 */
export function speakerLabel(message: ConversationMessage, participants: ConversationMember[]): string {
  if (message.role !== 'user') return roleLabel(message.role)
  const sender = message.sender_id ?? null
  if (!sender) return '发起人'
  if (sender === CURRENT_USER_ID) return '我'
  const hit = participants.find((item) => item.member_id === sender)
  const name = hit?.display_name?.trim()
  if (name) return name
  return '会话成员'
}

/** 当前用户是否为该会话发起人（用于决定是否展示分享管理控件；成员只读）。 */
export function isConversationOwner(participants: ConversationMember[]): boolean {
  return participants.some((item) => item.is_owner && item.member_id === CURRENT_USER_ID)
}
