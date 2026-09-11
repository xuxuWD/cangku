// 站内通知（收件箱）类型：与服务端 /api/v1/inbox 契约保持一致。
export type InboxKind =
  | 'task.approved'
  | 'plan.approved'
  | 'plan.rejected'
  | 'orchestration.approved'
  | 'orchestration.rejected'
  | 'publication.manual_takeover'
  | 'run.failed'
  | 'account.registration.approved'

export type InboxTargetType = 'task' | 'plan_proposal' | 'orchestration_proposal' | 'publication' | 'run'

export interface InboxItem {
  inbox_id: string
  kind: InboxKind
  title: string
  target_type: InboxTargetType | null
  target_id: string | null
  created_at: string
  read_at: string | null
}

export interface InboxList {
  items: InboxItem[]
  unread_count: number
}

export const INBOX_KIND_LABELS: Record<InboxKind, string> = {
  'task.approved': '任务已通过',
  'plan.approved': '计划已通过',
  'plan.rejected': '计划被驳回',
  'orchestration.approved': '编排优化已通过',
  'orchestration.rejected': '编排优化被驳回',
  'publication.manual_takeover': '发布转人工接管',
  'run.failed': '运行失败',
  'account.registration.approved': '注册申请已通过',
}

// 服务端新增 kind 时给出兜底文案，避免出现空白标签。
export function inboxKindLabel(kind: string): string {
  return INBOX_KIND_LABELS[kind as InboxKind] ?? '通知'
}
