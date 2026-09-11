import type { ApiErrorShape, KnowledgeAudit, KnowledgeBinding, SubjectType } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
    if (!response.ok) {
      const unauthorized = response.status === 401 || response.status === 403
      throw { status: response.status, message: unauthorized ? '当前账号没有配置知识权限的权限。' : `服务暂时无法完成请求（${response.status}）。`, retryable: !unauthorized && response.status >= 500, unauthorized } satisfies ApiErrorShape
    }
    return await response.json() as T
  } catch (error) {
    if (typeof error === 'object' && error !== null && 'status' in error) throw error
    throw { status: 0, message: '权限服务暂时不可用，请检查网络后重新尝试。', retryable: true, unauthorized: false } satisfies ApiErrorShape
  }
}

export function getKnowledgeAccess(type: SubjectType, key: string): Promise<KnowledgeBinding> { return request(`/knowledge-access/${type === 'role' ? 'roles' : 'agents'}/${encodeURIComponent(key)}`) }
export function saveKnowledgeAccess(type: SubjectType, key: string, ids: string[], idempotencyKey: string): Promise<KnowledgeBinding> { return request(`/knowledge-access/${type === 'role' ? 'roles' : 'agents'}/${encodeURIComponent(key)}`, { method: 'PUT', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ knowledge_base_ids: ids }) }) }
export function getKnowledgeAudits(limit = 20): Promise<KnowledgeAudit[]> { return request(`/knowledge-access/audits?limit=${limit}`).then((data) => Array.isArray(data) ? data : (data as { items?: KnowledgeAudit[] }).items || []) }

export interface DirectorySubject { key: string; label: string; role_key?: string }
export interface DirectorySubjects { role: DirectorySubject[]; agent: DirectorySubject[] }

// 候选岗位/数字员工来自目录（「数字员工设置」），不再使用前端写死的清单。
export async function getDirectorySubjects(): Promise<DirectorySubjects> {
  const [roles, agents] = await Promise.all([
    request<{ items?: Array<{ role_key: string; name: string }> }>('/workforce/roles?status=active&limit=200&offset=0'),
    request<{ items?: Array<{ agent_key: string; name: string; role_key: string }> }>('/workforce/agents?status=active&limit=200&offset=0'),
  ])
  const roleItems = Array.isArray(roles.items) ? roles.items : []
  const agentItems = Array.isArray(agents.items) ? agents.items : []
  return {
    role: roleItems.map((item) => ({ key: item.role_key, label: item.name })),
    agent: agentItems.map((item) => ({ key: item.agent_key, label: item.name, role_key: item.role_key })),
  }
}
