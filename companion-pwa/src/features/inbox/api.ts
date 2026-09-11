import { loadSession } from '../../app/session'
import type { InboxList } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

export class InboxApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'InboxApiError'
    this.status = status
  }
}

// 认证请求遇到 401 时抛出：上层据此清理会话并要求重新登录。
export class InboxSessionExpiredError extends InboxApiError {
  constructor(message = '登录已过期，请重新登录。') {
    super(message, 401)
    this.name = 'InboxSessionExpiredError'
  }
}

function authHeaders(): Record<string, string> {
  const session = loadSession()
  const headers: Record<string, string> = { Accept: 'application/json', 'Content-Type': 'application/json' }
  if (session) headers.Authorization = `Bearer ${session.accessToken}`
  return headers
}

async function friendlyMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail?: unknown }).detail
      if (typeof detail === 'string' && detail.length > 0) return detail
    }
  } catch {
    // 响应体不是 JSON 时退回通用文案。
  }
  return `服务暂时无法完成请求（${response.status}）。`
}

export async function listInbox(unreadOnly = false, limit = 50): Promise<InboxList> {
  const params = new URLSearchParams({ unread_only: String(unreadOnly), limit: String(limit) })
  const response = await fetch(`${apiBase}/inbox?${params.toString()}`, { headers: authHeaders() })
  if (response.status === 401) throw new InboxSessionExpiredError()
  if (!response.ok) throw new InboxApiError(await friendlyMessage(response), response.status)
  return (await response.json()) as InboxList
}
