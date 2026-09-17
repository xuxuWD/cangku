import { loadSession } from '../../app/session'
import type { ConversationDetail, ConversationList, MessageCreateResponse } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

const DEFAULT_ERROR_MESSAGE = '对话服务暂时不可用，请检查网络后重试。'

/** 对话接口错误：带服务端状态码与「可否重试」判定；文案不暴露堆栈 / 路径 / SQL。 */
export class ConversationApiError extends Error {
  readonly status: number
  readonly retryable: boolean

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ConversationApiError'
    this.status = status
    this.retryable = status === 0 || status >= 500
  }
}

/** 认证请求遇到 401 时抛出：上层据此清理会话并要求重新登录。 */
export class ConversationSessionExpiredError extends ConversationApiError {
  constructor(message = '登录已过期，请重新登录。') {
    super(message, 401)
    this.name = 'ConversationSessionExpiredError'
  }
}

// 按 HTTP 状态码映射为固定中文提示；仅当服务端 `detail` 是**字符串**时才透出（后端自己写的中文原因）。
export function conversationErrorFromStatus(status: number, detail?: string | null): ConversationApiError {
  if (status === 401) return new ConversationSessionExpiredError()
  if (status === 403) return new ConversationApiError(detail || '当前岗位不能使用对话入口。', status)
  if (status === 404) return new ConversationApiError(detail || '会话不存在，或不属于当前账号。', status)
  if (status === 409) return new ConversationApiError(detail || '会话已归档，不能再发送新消息。', status)
  if (status === 422) return new ConversationApiError(detail || '消息不符合要求（不能为空 / 超长，或工具调用格式不合法）。', status)
  if (status === 0 || status >= 500) return new ConversationApiError(DEFAULT_ERROR_MESSAGE, status)
  return new ConversationApiError(detail || `请求未被接受（${status}）。`, status)
}

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  const session = loadSession()
  const headers: Record<string, string> = { Accept: 'application/json', 'Content-Type': 'application/json', ...(extra as Record<string, string>) }
  if (session) headers.Authorization = `Bearer ${session.accessToken}`
  return headers
}

async function detailFrom(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return typeof body.detail === 'string' && body.detail.trim() ? body.detail.trim() : null
  } catch {
    return null
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: authHeaders(options.headers ?? {}) })
  } catch {
    throw conversationErrorFromStatus(0)
  }
  if (!response.ok) throw conversationErrorFromStatus(response.status, await detailFrom(response))
  return (await response.json().catch(() => ({}))) as T
}

export function listConversations(params: { limit: number; offset: number }): Promise<ConversationList> {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  return request<ConversationList>(`/conversations?${query.toString()}`)
}

export function getConversation(conversationId: string, params: { limit: number; offset: number }): Promise<ConversationDetail> {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}?${query.toString()}`)
}

/** 纯文本路径：**不带幂等键**（桩回复，不触发真实执行、不写帧）。 */
export function sendMessage(conversationId: string, content: string): Promise<MessageCreateResponse> {
  return request<MessageCreateResponse>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export interface ConversationStreamSendResult {
  body: MessageCreateResponse
  /** 本次运行 id（响应头 `X-Stream-Run-Id`；无运行时为 null ⇒ 界面如实告知「没有过程流」）。 */
  runId: string | null
}

/** 结构化调用路径：带新幂等键走 `messages:stream`（真实执行 + 幂等）。 */
export async function sendMessageStream(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<ConversationStreamSendResult> {
  let response: Response
  try {
    response = await fetch(`${apiBase}/conversations/${encodeURIComponent(conversationId)}/messages:stream`, {
      method: 'POST',
      headers: authHeaders({ 'Idempotency-Key': idempotencyKey }),
      body: JSON.stringify({ content }),
    })
  } catch {
    throw conversationErrorFromStatus(0)
  }
  if (!response.ok) throw conversationErrorFromStatus(response.status, await detailFrom(response))
  const body = (await response.json().catch(() => ({}))) as MessageCreateResponse
  const runId = response.headers?.get?.('X-Stream-Run-Id') ?? body.run_id ?? null
  return { body, runId }
}

/**
 * 打开 SSE 读端（`GET .../stream`）。**不用 `EventSource`**：认证走自定义请求头，
 * 且续播需要自定义 `Last-Event-ID`，只有 `fetch` + 读流能同时满足。
 *
 * 起点：服务端取 `max(Last-Event-ID, after_seq)`，缺省 0（从第一帧补发）；
 * 这里只在续播（`since > 0`）时发头，首连不带头（即 after_seq 缺省 = 0）。
 * 简化（§2.12 裁定）：不按 `run_id` 钉死，始终尾随该会话**最新 run**（服务端自动发现）。
 */
export async function openConversationStream(params: {
  conversationId: string
  since: number
  signal: AbortSignal
}): Promise<Response> {
  const extra: HeadersInit = params.since > 0 ? { 'Last-Event-ID': String(params.since) } : {}
  return await fetch(`${apiBase}/conversations/${encodeURIComponent(params.conversationId)}/stream`, {
    headers: authHeaders({ Accept: 'text/event-stream', ...extra }),
    signal: params.signal,
  })
}