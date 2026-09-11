import { directoryErrorFromStatus } from './state'
import { PAGE_LIMIT, type DigitalEmployee, type DirectoryList, type JobRole, type WorkforceCandidates } from './types'

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
    throw directoryErrorFromStatus(0)
  }
  if (!response.ok) throw directoryErrorFromStatus(response.status, await detailFrom(response))
  return await response.json() as T
}

function listPath(resource: string, filters: Record<string, string | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  params.set('limit', String(PAGE_LIMIT))
  params.set('offset', '0')
  return `/workforce/${resource}?${params.toString()}`
}

export function listRoles(status?: string): Promise<DirectoryList<JobRole>> {
  return request<DirectoryList<JobRole>>(listPath('roles', { status }))
}

export function createRole(payload: { role_key: string; name: string; description: string }): Promise<JobRole> {
  return request<JobRole>('/workforce/roles', { method: 'POST', body: JSON.stringify(payload) })
}

// 标识不可改：这里刻意只允许提交中文名、描述与状态。
export function updateRole(roleKey: string, payload: { name?: string; description?: string; status?: string }): Promise<JobRole> {
  return request<JobRole>(`/workforce/roles/${encodeURIComponent(roleKey)}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function listAgents(filters: { status?: string; role_key?: string } = {}): Promise<DirectoryList<DigitalEmployee>> {
  return request<DirectoryList<DigitalEmployee>>(listPath('agents', filters))
}

export function createAgent(payload: { agent_key: string; name: string; role_key: string; description: string }): Promise<DigitalEmployee> {
  return request<DigitalEmployee>('/workforce/agents', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateAgent(agentKey: string, payload: { name?: string; description?: string; role_key?: string; status?: string }): Promise<DigitalEmployee> {
  return request<DigitalEmployee>(`/workforce/agents/${encodeURIComponent(agentKey)}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function listCandidates(): Promise<WorkforceCandidates> {
  return request<WorkforceCandidates>('/workforce/candidates')
}
