export type PendingApprovalKind = 'task_approval' | 'plan_proposal' | 'account_registration' | 'run_approval'

// run_approval 的 detail 字段：客户端据此拼出决议接口路径（其余 kind 的 detail 各异，故统一用 Record 承载）。
export interface RunApprovalDetail {
  run_id: string
  approval_id: string
  step_id: string | null
  tool: string | null
}

export interface PendingApproval {
  kind: PendingApprovalKind
  target_id: string
  title: string
  requested_by: string | null
  created_at: string
  detail: Record<string, unknown>
}

// 运行审批决议的响应（规格 §4.1.6-7）：在既有字段之上**新增可选** `execution`；
// 客户端须对未知字段容错——缺省即「无执行结局」（如 backend=mock）。既有字段不变。
export type RunApprovalOutcome = 'executed' | 'pending_approval' | 'rejected' | 'failed'

export interface RunApprovalExecution {
  outcome: RunApprovalOutcome
  code?: number
  message_id?: string
}

export interface RunApprovalDecision {
  run_id: string
  approval_id: string
  status: string
  run_status: string
  execution?: RunApprovalExecution
}

export interface PendingApprovalCounts {
  task_approval: number
  plan_proposal: number
  account_registration: number
  run_approval: number
  total: number
}

export interface PendingApprovalsResponse {
  items: PendingApproval[]
  counts: PendingApprovalCounts
}

// 与服务端 app/accounts/service.py 的 _SUPPORTED_ROLES 保持一致；角色由审批人在通过时指定。
export const APPROVABLE_ROLES = ['employee', 'department_lead', 'ceo', 'super_admin', 'customer_admin'] as const

export type ApprovableRole = (typeof APPROVABLE_ROLES)[number]

export const ROLE_LABELS: Record<ApprovableRole, string> = {
  employee: '普通员工',
  department_lead: '部门负责人',
  ceo: 'CEO',
  super_admin: '超级管理员',
  customer_admin: '客户管理员',
}

export const DEFAULT_APPROVAL_ROLE: ApprovableRole = 'employee'
