import type { CollaborationDynamic } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'employee', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'employee', ...extra }
}

export async function listCollaborationDynamics(limit = 50): Promise<CollaborationDynamic[]> {
  const response = await fetch(`${apiBase}/collaboration-dynamics?limit=${limit}`, { headers: headers() })
  if (!response.ok) {
    const unauthorized = response.status === 401 || response.status === 403
    throw new Error(unauthorized ? '当前账号没有查看协同动态的权限。' : `协同动态暂时无法加载（${response.status}）。`)
  }
  return await response.json() as CollaborationDynamic[]
}
