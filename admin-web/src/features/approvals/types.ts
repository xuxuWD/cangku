// 「待我审批」聚合前端类型：与 `GET /api/v1/approvals/pending` 契约逐字对齐。
// 契约为**只读查询**（不执行任何审批动作）；四类事项的 `detail` 只含既有接口已暴露的非敏感字段。
export type PendingApprovalKind = 'task_approval' | 'plan_proposal' | 'account_registration' | 'run_approval'

export interface PendingApprovalItem {
  kind: PendingApprovalKind
  target_id: string
  title: string
  requested_by: string
  created_at: string
  detail: Record<string, unknown>
}

export interface PendingApprovalCounts {
  task_approval: number
  plan_proposal: number
  account_registration: number
  run_approval: number
  total: number
}

export interface PendingApprovalList {
  items: PendingApprovalItem[]
  counts: PendingApprovalCounts
}

export const PENDING_APPROVAL_KIND_LABELS: Record<PendingApprovalKind, string> = {
  task_approval: '任务审批',
  plan_proposal: '计划提案',
  account_registration: '账号注册',
  run_approval: '运行内审批',
}

export function pendingApprovalKindLabel(kind: string): string {
  return PENDING_APPROVAL_KIND_LABELS[kind as PendingApprovalKind] ?? kind
}

export const EMPTY_PENDING_COUNTS: PendingApprovalCounts = {
  task_approval: 0,
  plan_proposal: 0,
  account_registration: 0,
  run_approval: 0,
  total: 0,
}

/** 运行内审批的 `detail` 里带 `run_id`（客户端据此打开运行详情去决议）。 */
export function pendingApprovalRunId(item: PendingApprovalItem): string | null {
  const value = item.detail?.run_id
  return typeof value === 'string' && value.trim() ? value : null
}

export function pendingApprovalDetailText(item: PendingApprovalItem): string {
  if (item.kind === 'task_approval') {
    const risk = typeof item.detail?.risk_level === 'string' ? item.detail.risk_level : ''
    const employee = typeof item.detail?.employee_key === 'string' ? item.detail.employee_key : ''
    return [risk && `风险 ${risk}`, employee && `执行人 ${employee}`].filter(Boolean).join(' · ')
  }
  if (item.kind === 'plan_proposal') {
    const steps = typeof item.detail?.step_count === 'number' ? item.detail.step_count : null
    return steps === null ? '' : `${steps} 步计划`
  }
  if (item.kind === 'account_registration') {
    return typeof item.detail?.position === 'string' ? `岗位 ${item.detail.position}` : ''
  }
  const step = typeof item.detail?.step_id === 'string' ? item.detail.step_id : ''
  const tool = typeof item.detail?.tool === 'string' ? item.detail.tool : ''
  return [step && `步骤 ${step}`, tool && `工具 ${tool}`].filter(Boolean).join(' · ')
}