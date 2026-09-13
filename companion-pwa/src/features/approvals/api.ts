import { loadSession } from '../../app/session'
import {
  DEFAULT_APPROVAL_ROLE,
  type PendingApproval,
  type PendingApprovalsResponse,
  type RunApprovalDecision,
  type RunApprovalDetail,
} from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// 认证请求（待办列表、审批动作）遇到 401 时抛出：上层据此清理会话并要求重新登录。
export class SessionExpiredError extends ApiError {
  constructor(message = '登录已过期，请重新登录。') {
    super(message, 401)
    this.name = 'SessionExpiredError'
  }
}

export interface SessionResponse {
  access_token: string
  token_type: string
  expires_in: number
  tenant_id: string
  user_id: string
  role: string
  scope: string
}

function jsonHeaders(): Record<string, string> {
  return { Accept: 'application/json', 'Content-Type': 'application/json' }
}

function authHeaders(): Record<string, string> {
  const session = loadSession()
  const headers = jsonHeaders()
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

async function authenticatedPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (response.status === 401) throw new SessionExpiredError()
  if (!response.ok) throw new ApiError(await friendlyMessage(response), response.status)
  return (await response.json().catch(() => ({}))) as T
}

export async function createSession(phone: string, password: string, totpCode?: string): Promise<SessionResponse> {
  const payload: Record<string, string> = { phone, password }
  if (totpCode) payload.totp_code = totpCode
  const response = await fetch(`${apiBase}/auth/sessions`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new ApiError(await friendlyMessage(response), response.status)
  return (await response.json()) as SessionResponse
}

export async function listPendingApprovals(limit = 50): Promise<PendingApprovalsResponse> {
  const response = await fetch(`${apiBase}/approvals/pending?limit=${encodeURIComponent(String(limit))}`, {
    headers: authHeaders(),
  })
  if (response.status === 401) throw new SessionExpiredError()
  if (!response.ok) throw new ApiError(await friendlyMessage(response), response.status)
  return (await response.json()) as PendingApprovalsResponse
}

export interface ApproveOptions {
  /** 账号注册审批必须指定被分配的角色；不传时按最小权限的 employee 提交。 */
  role?: string
}

const MISSING_RUN_INFO = '该待办缺少运行信息，请刷新后重试。'

// 从 detail 中取运行审批信息；缺少关键字段时返回 null，避免拼出错误路径。
function extractRunApprovalDetail(item: PendingApproval): RunApprovalDetail | null {
  const { run_id: runId, approval_id: approvalId, step_id: stepId, tool } = item.detail
  if (typeof runId !== 'string' || runId === '') return null
  if (typeof approvalId !== 'string' || approvalId === '') return null
  return {
    run_id: runId,
    approval_id: approvalId,
    step_id: typeof stepId === 'string' ? stepId : null,
    tool: typeof tool === 'string' ? tool : null,
  }
}

// 运行审批决议路径：POST /runs/{run_id}/approvals/{approval_id}/approval
function runApprovalPath(item: PendingApproval): string | null {
  const detail = extractRunApprovalDetail(item)
  if (!detail) return null
  return `/runs/${encodeURIComponent(detail.run_id)}/approvals/${encodeURIComponent(detail.approval_id)}/approval`
}

export function approveItem(item: PendingApproval, options: ApproveOptions = {}): Promise<unknown> {
  if (item.kind === 'task_approval') {
    return authenticatedPost(`/tasks/${encodeURIComponent(item.target_id)}/approve`, {})
  }
  if (item.kind === 'plan_proposal') {
    return authenticatedPost(`/plan-proposals/${encodeURIComponent(item.target_id)}/approval`, {})
  }
  // 运行审批必须先于账号注册兜底分支判断，否则会被误发到注册接口。
  if (item.kind === 'run_approval') {
    const path = runApprovalPath(item)
    if (!path) return Promise.reject(new ApiError(MISSING_RUN_INFO, 400))
    // 响应含可选 `execution`（§4.1.6-7）；按契约类型解析，未知字段不报错。
    return authenticatedPost<RunApprovalDecision>(path, { approved: true })
  }
  // 账号注册审批必须带 role 与 tenant_id：角色由审批人指定，租户取当前会话。
  const session = loadSession()
  return authenticatedPost(`/auth/registrations/${encodeURIComponent(item.target_id)}/approval`, {
    role: options.role ?? DEFAULT_APPROVAL_ROLE,
    tenant_id: session?.tenantId ?? '',
  })
}

export function rejectItem(item: PendingApproval, reason: string): Promise<unknown> {
  if (item.kind === 'plan_proposal') {
    return authenticatedPost(`/plan-proposals/${encodeURIComponent(item.target_id)}/rejection`, { reason })
  }
  // 运行审批的驳回同样打到决议接口，仅 body 的 approved 取 false。
  if (item.kind === 'run_approval') {
    const path = runApprovalPath(item)
    if (!path) return Promise.reject(new ApiError(MISSING_RUN_INFO, 400))
    return authenticatedPost<RunApprovalDecision>(path, { approved: false })
  }
  if (item.kind === 'account_registration') {
    return authenticatedPost(`/auth/registrations/${encodeURIComponent(item.target_id)}/rejection`, { reason })
  }
  return Promise.reject(new ApiError('该类型待办不支持驳回。', 400))
}
