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

// P2c-3：产物登记（**运行级元数据**）——契约「产物登记与只读端点」。
// **只含元数据**（虚拟路径 / 变更类型 / 字节 / sha256 / 时间），不含文件内容、不含 tenant_id。
export interface RunArtifact {
  artifact_id: string
  virtual_path: string
  change_kind: string
  bytes: number
  sha256: string
  created_at: string
  expires_at: string | null
}

export interface RunArtifactList {
  run_id: string
  items: RunArtifact[]
  total: number
}

// S4 干预（暂停 / 恢复 / 取消）的应答：服务端只回运行号与**权威状态**；
// 客户端据此不做本地乐观更新，而是重取概览 / 事件 / 审批。
export interface RunActionAck {
  run_id: string
  status: string
}

// S2 人工验收决议（契约「运行验收决议（S2 · 人工验收）」）：
// **人的结论**与机器结论（结构判定）分开存；本表 append-only，历史里带 `structural_verdict` 供追溯。
export type RunAcceptanceDecisionKind = 'confirmed' | 'rejected'

export interface RunAcceptanceDecision {
  decision_id: string
  decision: RunAcceptanceDecisionKind
  reason: string
  decided_by: string
  decided_at: string
  structural_verdict: 'met' | 'unmet'
}

// S2 沉淀入口（契约「运行沉淀（S2 · 存成任务）」）：一个运行最多沉淀一次；`promotion` 为空即还没沉淀。
export interface RunAcceptancePromotion {
  task_id: string
  title: string
  promoted_by: string
  promoted_at: string
}

export interface RunAcceptanceDecisionList {
  run_id: string
  items: RunAcceptanceDecision[]
  latest: RunAcceptanceDecision | null
  /** 未沉淀为 `null`（服务端权威；界面据此把「存成任务」显示成入口或「已存成任务」）。 */
  promotion: RunAcceptancePromotion | null
}

export interface RunPromotionResult {
  run_id: string
  task_id: string
  created: boolean
  promotion: RunAcceptancePromotion
  /** 承载任务不可见时服务端返回 `null`（界面只给标识，不编造内容）。 */
  task: RunTask | null
  task_created?: boolean
}

export const ACCEPTANCE_DECISION_LABELS: Record<string, string> = {
  confirmed: '已确认完成',
  rejected: '已打回重做',
}

export function acceptanceDecisionLabel(decision: string): string {
  return ACCEPTANCE_DECISION_LABELS[decision] ?? decision
}

// 变更类型中文标签；**未知取值原样展示**（不猜测）。
export const CHANGE_KIND_LABELS: Record<string, string> = {
  created: '新建',
  overwritten: '覆盖',
  deleted: '删除',
  // 兼容历史取值（P2c-2 前端预置位；服务端已冻结为上面三值）
  create: '新建',
  write: '写入',
  overwrite: '覆盖',
  delete: '删除',
  modify: '修改',
}

export function changeKindLabel(kind: string): string {
  return CHANGE_KIND_LABELS[kind] ?? kind
}

export interface RunApprovalDecision {
  run_id: string
  approval_id: string
  status: string
  run_status: string
  // 规格 §4.1.6-7：在既有字段之上**新增可选**执行结局；既有字段不变。
  // 客户端须对未知字段容错——缺省即「无执行结局」（如 backend=mock）。
  execution?: RunApprovalExecution
}

// §4.1.6-7 的 `execution`：只含结局码与消息指针，**不含**参数原文 / 宿主路径 / 凭据。
export type RunApprovalOutcome = 'executed' | 'pending_approval' | 'rejected' | 'failed'

export interface RunApprovalExecution {
  outcome: RunApprovalOutcome
  code?: number
  message_id?: string
}

export const RUN_APPROVAL_OUTCOME_LABELS: Record<RunApprovalOutcome, string> = {
  executed: '已执行',
  pending_approval: '待审批',
  rejected: '已拒绝',
  failed: '执行失败',
}

export function runApprovalOutcomeLabel(outcome: string): string {
  return RUN_APPROVAL_OUTCOME_LABELS[outcome as RunApprovalOutcome] ?? outcome
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
// `tool_key` 为 P2c-1 新增的受控展示字段（工具键本身非敏感；参数值 / digest 仍不渲染）。
export const RUN_EVENT_PAYLOAD_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'step_id', label: '步骤' },
  { key: 'tool', label: '工具' },
  { key: 'tool_key', label: '工具键' },
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
