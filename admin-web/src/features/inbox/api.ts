import type { ApiErrorShape, InboxItem, InboxList } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
    if (!response.ok) {
      const unauthorized = response.status === 401 || response.status === 403
      throw { status: response.status, message: unauthorized ? '当前账号没有查看通知的权限。' : `服务暂时无法完成请求（${response.status}）。`, retryable: !unauthorized && response.status >= 500, unauthorized } satisfies ApiErrorShape
    }
    return await response.json() as T
  } catch (error) {
    if (typeof error === 'object' && error !== null && 'status' in error) throw error
    throw { status: 0, message: '通知服务暂时不可用，请检查网络后重新尝试。', retryable: true, unauthorized: false } satisfies ApiErrorShape
  }
}

export function listInbox(unreadOnly = false, limit = 50): Promise<InboxList> {
  const params = new URLSearchParams({ unread_only: String(unreadOnly), limit: String(limit) })
  return request<InboxList>(`/inbox?${params.toString()}`)
}

export function markInboxRead(inboxId: string): Promise<InboxItem> {
  return request<InboxItem>(`/inbox/${encodeURIComponent(inboxId)}/read`, { method: 'POST' })
}

export function markAllInboxRead(): Promise<{ updated: number }> {
  return request<{ updated: number }>('/inbox/read-all', { method: 'POST' })
}
