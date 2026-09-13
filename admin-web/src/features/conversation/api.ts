import { conversationErrorFromStatus } from './state'
import type {
  Conversation,
  ConversationDetail,
  ConversationList,
  MessageCreateResponse,
} from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

// 只取服务端自己写的中文 detail（字符串）；数组形式的参数校验错误一律丢弃。
async function detailFrom(response: Response): Promise<string | null> {
  try {
    const body = await response.json() as { detail?: unknown }
    return typeof body.detail === 'string' && body.detail.trim() ? body.detail.trim() : null
  } catch {
    return null
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw conversationErrorFromStatus(0)
  }
  if (!response.ok) throw conversationErrorFromStatus(response.status, await detailFrom(response))
  return await response.json() as T
}

export function listConversations(params: { status?: string; limit: number; offset: number }): Promise<ConversationList> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  query.set('limit', String(params.limit))
  query.set('offset', String(params.offset))
  return request<ConversationList>(`/conversations?${query.toString()}`)
}

export function getConversation(conversationId: string, params: { limit: number; offset: number }): Promise<ConversationDetail> {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}?${query.toString()}`)
}

// `agent_key` 缺省表示用默认员工；不给未知字段（后端 extra=forbid）。
export function createConversation(payload: { agent_key?: string; title?: string } = {}): Promise<Conversation> {
  return request<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ agent_key: payload.agent_key, title: payload.title ?? '' }),
  })
}

// 响应直接带回 reply（含 stub 标注），不需要轮询。
// `Idempotency-Key`（§3.2 第四条）：带键 ⇒ 触发真实执行 + 幂等（201 已执行 / 202 待批）；
// 不带键 ⇒ 后端沿用既有 `stub=true` 桩回复。键由调用方生成（同一键重放返回既有结果）。
export function sendConversationMessage(conversationId: string, content: string, idempotencyKey?: string): Promise<MessageCreateResponse> {
  const extra: HeadersInit = idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}
  return request<MessageCreateResponse>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST',
    headers: extra,
    body: JSON.stringify({ content }),
  })
}

export function archiveConversation(conversationId: string): Promise<Conversation> {
  return request<Conversation>(`/conversations/${encodeURIComponent(conversationId)}/archive`, { method: 'POST' })
}
