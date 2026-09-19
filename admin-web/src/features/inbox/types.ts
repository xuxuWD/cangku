// 站内通知（收件箱）前端类型：与服务端 /api/v1/inbox 契约保持一致。
export type InboxKind =
  | 'task.approved'
  | 'plan.approved'
  | 'plan.rejected'
  | 'orchestration.approved'
  | 'orchestration.rejected'
  | 'publication.manual_takeover'
  | 'run.failed'
  | 'run.cancelled'
  | 'run.approval_rejected'
  | 'account.registration.approved'
  | 'crm.activity.due'
  | 'crm.renewal.window'
// 注：最后两个为 P5a CRM（crm-p5a-design §2.11）跟进任务到期 / 合同续约窗口提醒。

export type InboxTargetType = 'task' | 'plan_proposal' | 'orchestration_proposal' | 'publication' | 'run' | 'crm_activity' | 'crm_contract'

export interface InboxItem {
  inbox_id: string
  kind: InboxKind
  title: string
  target_type: InboxTargetType | null
  target_id: string | null
  // S1 第三款：服务端反查出的**上文标识**（可空）——有会话就能直达「该会话（的该条卡）」，
  // 为空时按 target_type / target_id 的既有落点打开（存量通知即此形态）。
  target_conversation_id: string | null
  target_approval_id: string | null
  created_at: string
  read_at: string | null
}

export interface InboxList {
  items: InboxItem[]
  unread_count: number
}

export interface ApiErrorShape {
  status: number
  message: string
  retryable: boolean
  unauthorized: boolean
}

export interface InboxState {
  items: InboxItem[]
  unreadCount: number
  loading: boolean
  error: ApiErrorShape | null
  markingId: string | null
  markingAll: boolean
  toast: string | null
}

export const INBOX_KIND_LABELS: Record<InboxKind, string> = {
  'task.approved': '任务已通过',
  'plan.approved': '计划已通过',
  'plan.rejected': '计划被驳回',
  'orchestration.approved': '编排优化已通过',
  'orchestration.rejected': '编排优化被驳回',
  'publication.manual_takeover': '发布转人工接管',
  'run.failed': '运行失败',
  'run.cancelled': '运行被取消',
  'run.approval_rejected': '运行审批被驳回',
  'account.registration.approved': '注册申请已通过',
  'crm.activity.due': '跟进任务到期',
  'crm.renewal.window': '合同进入续约窗口',
}

// 服务端新增 kind 时给出兜底文案，避免出现空白标签。
export function inboxKindLabel(kind: string): string {
  return INBOX_KIND_LABELS[kind as InboxKind] ?? '通知'
}
