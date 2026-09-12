import { homeErrorFromStatus } from './state'
import type { Conversation, ConversationList } from '../conversation/types'
import type { HomeCreatedTask, HomeEmployeeList, HomeRiskLevel } from './types'

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
    throw homeErrorFromStatus(0)
  }
  if (!response.ok) throw homeErrorFromStatus(response.status, await detailFrom(response))
  return await response.json() as T
}

// 幂等键：优先用 crypto.randomUUID，环境不支持时退回时间戳 + 随机串。
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `home-${crypto.randomUUID()}`
  }
  return `home-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function listHomeEmployees(): Promise<HomeEmployeeList> {
  return request<HomeEmployeeList>('/workforce/agents?limit=50&offset=0')
}

export function listHomeConversations(limit: number): Promise<ConversationList> {
  return request<ConversationList>(`/conversations?limit=${limit}&offset=0`)
}

// 首页第一句话 = 建会话；`agent_key` 缺省即用默认员工。
export function createHomeConversation(payload: { agentKey?: string; title: string }): Promise<Conversation> {
  return request<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ agent_key: payload.agentKey, title: payload.title }),
  })
}

export function sendHomeMessage(conversationId: string, content: string): Promise<{ conversation_id: string; stub: boolean }> {
  return request<{ conversation_id: string; stub: boolean }>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

// 次要入口「或直接建任务」保留：POST /tasks 在整个前端只有首页在用。
export function createHomeTask(payload: {
  title: string
  employeeKey: string
  riskLevel: HomeRiskLevel
  idempotencyKey: string
}): Promise<HomeCreatedTask> {
  return request<HomeCreatedTask>('/tasks', {
    method: 'POST',
    body: JSON.stringify({
      title: payload.title,
      employee_key: payload.employeeKey,
      risk_level: payload.riskLevel,
      budget: 0,
      idempotency_key: payload.idempotencyKey,
    }),
  })
}
