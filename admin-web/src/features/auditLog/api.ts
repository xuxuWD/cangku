import { auditErrorFromStatus } from './state'
import type { AuditFilters, AuditListResponse } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw auditErrorFromStatus(0)
  }
  if (!response.ok) throw auditErrorFromStatus(response.status)
  return await response.json() as T
}

// action 可重复，每个动作 append 一次；其余条件非空才拼进查询串。
export function listAudits(filters: AuditFilters): Promise<AuditListResponse> {
  const params = new URLSearchParams()
  for (const action of filters.actions) {
    if (action) params.append('action', action)
  }
  if (filters.actorId) params.set('actor_id', filters.actorId)
  if (filters.targetType) params.set('target_type', filters.targetType)
  if (filters.targetId) params.set('target_id', filters.targetId)
  // 页面统一用 new Date(local).toISOString() 生成带时区的 Z 形式，避免服务端按 422 拒绝。
  if (filters.since) params.set('since', filters.since)
  if (filters.until) params.set('until', filters.until)
  params.set('limit', String(filters.limit))
  params.set('offset', String(filters.offset))
  return request<AuditListResponse>(`/audits?${params.toString()}`)
}
