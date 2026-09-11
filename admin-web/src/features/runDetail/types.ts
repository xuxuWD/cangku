// 运行详情页前端类型：与服务端 /api/v1/runs 契约保持一致。
export interface RunMetrics {
  run_id: string
  task_id: string
  proposal_id: string | null
  runtime_key: string
  status: string
  step_count: number
  completed_step_count: number
  tool_calls: number
  successful_tools: number
  knowledge_hits: number
  latency_ms: number
  started_at: string
  finished_at: string | null
  finish_reason: string | null
}

export interface RunTask {
  id: string
  tenant_id: string
  project_id: string | null
  created_by: string
  employee_key: string
  title: string
  risk_level: string
  budget: number
  idempotency_key: string
  status: string
  audit_count: number
}

export interface RunEvent {
  cursor: string
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
}

export interface RunApproval {
  approval_id: string
  step_id: string | null
  tool: string | null
  status: string
}

export interface RunApprovalList {
  items: RunApproval[]
}

export interface RunApprovalDecision {
  run_id: string
  approval_id: string
  status: string
  run_status: string
}

export interface RunErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface RunDetailState {
  metrics: RunMetrics | null
  task: RunTask | null
  events: RunEvent[]
  approvals: RunApproval[]
  metricsError: RunErrorShape | null
  taskError: RunErrorShape | null
  eventsError: RunErrorShape | null
  approvalsError: RunErrorShape | null
  loadingOverview: boolean
  loadingEvents: boolean
  loadingApprovals: boolean
  decidingId: string | null
  toast: string | null
}

// 运行状态中文标签；未知状态原样展示，避免出现空白。
export const RUN_STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  running: '运行中',
  paused: '已暂停',
  failed: '失败',
  cancelled: '已取消',
}

// 结束原因中文标签；null 由 finishReasonLabel 渲染为「—」。
export const FINISH_REASON_LABELS: Record<string, string> = {
  run_completed: '正常完成',
  cancelled_by_user: '用户取消',
  step_failed: '步骤失败',
  approval_rejected: '审批被驳回',
}

// 运行事件中文标签；未知类型统一兜底为「其他事件」。
export const RUN_EVENT_LABELS: Record<string, string> = {
  'plan.created': '计划已创建',
  'step.started': '步骤开始',
  'tool.call': '工具调用',
  'tool.result': '工具结果',
  'approval.requested': '请求审批',
  'approval.decided': '审批已决议',
  'checkpoint.saved': '保存检查点',
  'run.paused': '运行暂停',
  'run.failed': '运行失败',
  'run.completed': '运行完成',
}

// 审批状态中文标签。
export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已驳回',
}

// 事件 payload 只允许渲染这些字段，避免把适配器带出的意外内容透到界面。
export const RUN_EVENT_PAYLOAD_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'step_id', label: '步骤' },
  { key: 'tool', label: '工具' },
  { key: 'status', label: '状态' },
  { key: 'reason', label: '原因' },
  { key: 'approval_id', label: '审批' },
  { key: 'approved', label: '决议' },
  { key: 'step_count', label: '步数' },
  { key: 'knowledge_hit', label: '知识命中' },
]

export function runStatusLabel(status: string): string {
  return RUN_STATUS_LABELS[status] ?? status
}

export function finishReasonLabel(reason: string | null): string {
  if (!reason) return '—'
  return FINISH_REASON_LABELS[reason] ?? reason
}

export function runEventLabel(eventType: string): string {
  return RUN_EVENT_LABELS[eventType] ?? '其他事件'
}

export function approvalStatusLabel(status: string): string {
  return APPROVAL_STATUS_LABELS[status] ?? status
}
