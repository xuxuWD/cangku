import { runActionErrorFromStatus, runErrorFromStatus } from './state'
import type { RunAcceptanceDecision, RunAcceptanceDecisionKind, RunAcceptanceDecisionList, RunActionAck, RunApprovalDecision, RunApprovalList, RunArtifactList, RunEvent, RunMetrics, RunPromotionResult, RunTask } from './types'

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

// P2c-3：产物登记只读列表（**只含元数据**；保留期已到的条目服务端不再返回）。
export function listRunArtifacts(runId: string): Promise<RunArtifactList> {
  return request<RunArtifactList>(`/runs/${encodeURIComponent(runId)}/artifacts`)
}

export function decideRunApproval(runId: string, approvalId: string, approved: boolean): Promise<RunApprovalDecision> {
  return request<RunApprovalDecision>(`/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/approval`, { method: 'POST', body: JSON.stringify({ approved }) })
}

// S4：运行干预（暂停 / 恢复 / 取消）。三端点都是 POST，服务端判定操作权
// （任务创建人 / CEO / 超管；越权以 404 收敛——不泄露运行是否存在）。
// 暂停与取消的 `reason` 是**必填**（1..500 字，服务端 `extra=forbid`），由调用方给定业务口径文案。
async function action<T>(path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw runActionErrorFromStatus(0)
  }
  if (!response.ok) {
    throw runActionErrorFromStatus(response.status, await readDetail(response))
  }
  return await response.json() as T
}

export function pauseRun(runId: string, reason: string): Promise<RunActionAck> {
  return action<RunActionAck>(`/runs/${encodeURIComponent(runId)}/pause`, { reason })
}

export function resumeRun(runId: string): Promise<RunActionAck> {
  return action<RunActionAck>(`/runs/${encodeURIComponent(runId)}/resume`)
}

export function cancelRun(runId: string, reason: string): Promise<RunActionAck> {
  return action<RunActionAck>(`/runs/${encodeURIComponent(runId)}/cancel`, { reason })
}

// S2 人工验收决议（契约「运行验收决议（S2 · 人工验收）」）：
// 只记录「人怎么判的」，不改运行状态、不触发重跑；同幂等键重放返回既有决议（`created: false`）。
export function listRunAcceptanceDecisions(runId: string): Promise<RunAcceptanceDecisionList> {
  return request<RunAcceptanceDecisionList>(`/runs/${encodeURIComponent(runId)}/acceptance/decisions`)
}

export function decideRunAcceptance(
  runId: string,
  payload: { decision: RunAcceptanceDecisionKind; reason?: string; idempotencyKey: string },
): Promise<RunAcceptanceDecision & { run_id: string; created: boolean }> {
  return action<RunAcceptanceDecision & { run_id: string; created: boolean }>(
    `/runs/${encodeURIComponent(runId)}/acceptance/decisions`,
    {
      decision: payload.decision,
      reason: payload.reason ?? '',
      idempotency_key: payload.idempotencyKey,
    },
  )
}

/** 每次决议生成一个新幂等键：同一次点击重放由服务端返回既有决议，不产生第二行。 */
export function newAcceptanceIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `acceptance-${crypto.randomUUID()}`
  }
  return `acceptance-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

// S2 沉淀入口（契约「运行沉淀（S2 · 存成任务）」）：把**已确认完成**的这次运行存成一个可再跑的任务。
// 幂等由服务端保证（一个运行只沉淀一次）：重复提交返回既有任务且 `created: false`，前端因此不需要幂等键。
export function promoteRunToTask(runId: string, title: string): Promise<RunPromotionResult> {
  return action<RunPromotionResult>(`/runs/${encodeURIComponent(runId)}/acceptance/tasks`, { title })
}
