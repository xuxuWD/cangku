import { billingErrorFromStatus } from './state'
import type { UsageSummary } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw billingErrorFromStatus(0)
  }
  if (!response.ok) throw billingErrorFromStatus(response.status)
  return await response.json() as T
}

// 只读：复用既有商业化用量接口，不接受任何写动作。
export function getUsageSummary(): Promise<UsageSummary> {
  return request<UsageSummary>('/commercial/usage')
}
