import { runErrorFromStatus } from './state'
import type { RunApprovalDecision, RunApprovalList, RunEvent, RunMetrics, RunTask } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

// 403 时后端会带 detail 文案；读取失败则返回 null，由映射层兜底。
async function readDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.json() as { detail?: unknown }
    if (body && typeof body.detail === 'string' && body.detail.trim()) return body.detail.trim()
    return null
  } catch {
    return null
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw runErrorFromStatus(0)
  }
  if (!response.ok) {
    const detail = response.status === 403 ? await readDetail(response) : null
    throw runErrorFromStatus(response.status, detail)
  }
  return await response.json() as T
}

export function getRunMetrics(runId: string): Promise<RunMetrics> {
  return request<RunMetrics>(`/runs/${encodeURIComponent(runId)}/metrics`)
}

export function getTask(taskId: string): Promise<RunTask> {
  return request<RunTask>(`/tasks/${encodeURIComponent(taskId)}`)
}

export function listRunEvents(runId: string): Promise<RunEvent[]> {
  return request<RunEvent[]>(`/runs/${encodeURIComponent(runId)}/events`)
}

export function listRunApprovals(runId: string): Promise<RunApprovalList> {
  return request<RunApprovalList>(`/runs/${encodeURIComponent(runId)}/approvals`)
}

export function decideRunApproval(runId: string, approvalId: string, approved: boolean): Promise<RunApprovalDecision> {
  return request<RunApprovalDecision>(`/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/approval`, { method: 'POST', body: JSON.stringify({ approved }) })
}
