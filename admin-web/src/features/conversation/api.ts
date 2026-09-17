import { conversationErrorFromStatus } from './state'
import type {
  Conversation,
  ConversationDeletionResult,
  ConversationDetail,
  ConversationExportPage,
  ConversationList,
  ConversationMode,
  MessageCreateResponse,
  RunAcceptance,
} from './types'
import { EXPORT_MAX_PAGES, EXPORT_PAGE_SIZE } from './types'

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

// ---------------------------------------------------------------- P2c-1 实时流（P2b 契约消费）

/**
 * 打开 SSE 读端（`GET .../stream`）。**不用 `EventSource`**：认证与租户态走自定义请求头，
 * 且续播需要自定义 `Last-Event-ID`，只有 `fetch` + 读流能同时满足。
 *
 * 起点：服务端取 `max(Last-Event-ID, after_seq)`，缺省 0（从第一帧补发）；
 * 这里只在续播（`since > 0`）时发头，首连不带头（即 after_seq 缺省 = 0）。
 */
export async function openConversationStream(params: {
  conversationId: string
  runId?: string
  since: number
  signal: AbortSignal
}): Promise<Response> {
  const query = new URLSearchParams()
  if (params.runId) query.set('run_id', params.runId)
  const search = query.toString()
  const extra: HeadersInit = params.since > 0 ? { 'Last-Event-ID': String(params.since) } : {}
  return await fetch(
    `${apiBase}/conversations/${encodeURIComponent(params.conversationId)}/stream${search ? `?${search}` : ''}`,
    { headers: headers({ Accept: 'text/event-stream', ...extra }), signal: params.signal },
  )
}

export interface StreamSendResult {
  body: MessageCreateResponse
  /** 本次运行 id（响应头 `X-Stream-Run-Id`；无运行时为 null）——舞台据此加载概览与审批。 */
  runId: string | null
}

/**
 * 发送一条用户消息（**实时流路径**）：请求体 / 头 / 响应体与旧端点逐字一致，
 * 唯一新增是响应头 `X-Stream-Run-Id`（P2b 契约）。带幂等键 ⇒ 真实执行并写帧。
 */
export async function sendConversationMessageStream(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<StreamSendResult> {
  let response: Response
  try {
    response = await fetch(`${apiBase}/conversations/${encodeURIComponent(conversationId)}/messages:stream`, {
      method: 'POST',
      headers: headers({ 'Idempotency-Key': idempotencyKey }),
      body: JSON.stringify({ content }),
    })
  } catch {
    throw conversationErrorFromStatus(0)
  }
  if (!response.ok) throw conversationErrorFromStatus(response.status, await detailFrom(response))
  const body = await response.json() as MessageCreateResponse
  const runId = response.headers?.get?.('X-Stream-Run-Id') ?? body.run_id ?? null
  return { body, runId }
}

// ---------------------------------------------------------------- P2c-4（模式 / 导出 / 物理删除 / 结构判定）

/** 改每会话模式（仅本人；他人 / 跨租户 404、归档 409、非法取值 422）。 */
export function setConversationMode(conversationId: string, mode: ConversationMode): Promise<Conversation> {
  return request<Conversation>(`/conversations/${encodeURIComponent(conversationId)}/mode`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}

/** **物理删除**本人会话的内容行（同步、幂等）：删除后列表 / 详情 / 流 / 发消息一律 404。 */
export function deleteConversation(conversationId: string): Promise<ConversationDeletionResult> {
  return request<ConversationDeletionResult>(`/conversations/${encodeURIComponent(conversationId)}/delete`, {
    method: 'POST',
  })
}

/** 取一页导出数据（页单位 = 会话；服务端 500/页、条目上限 5 万）。 */
export function exportMyConversationsPage(offset: number): Promise<ConversationExportPage> {
  const query = new URLSearchParams({ limit: String(EXPORT_PAGE_SIZE), offset: String(offset) })
  return request<ConversationExportPage>(`/conversations/exports/mine?${query.toString()}`)
}

export interface ConversationExportBundle {
  pages: ConversationExportPage[]
  /** 客户端合并是否在服务端上限前停止（页数上限或服务端如实告知截断）。 */
  truncated: boolean
}

/**
 * 导出本人全部会话数据：**逐页拉取并合并**（客户端循环，上限 = 服务端上限口径 100 页 × 500）。
 * 到顶或服务端 `truncated` 即停止 —— 界面据 `truncated` **如实告知**未取全，不静默截断。
 */
export async function exportMyConversations(): Promise<ConversationExportBundle> {
  const pages: ConversationExportPage[] = []
  let offset = 0
  let fetched = 0
  let truncated = false
  for (let page = 0; page < EXPORT_MAX_PAGES; page += 1) {
    const data = await exportMyConversationsPage(offset)
    pages.push(data)
    fetched += Array.isArray(data.conversations) ? data.conversations.length : 0
    offset += EXPORT_PAGE_SIZE
    if (data.truncated) {
      truncated = true
      break
    }
    // 取全即停；空页也停（防止服务端异常导致死循环）。
    if (fetched >= (data.total_conversations ?? 0) || (data.conversations ?? []).length === 0) break
  }
  return { pages, truncated }
}

/** 运行结构判定（纯读；服务端不调模型、不改运行状态）。 */
export function getRunAcceptance(runId: string): Promise<RunAcceptance> {
  return request<RunAcceptance>(`/runs/${encodeURIComponent(runId)}/acceptance`)
}
