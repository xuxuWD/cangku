/**
 * 站内通知（收件箱）类型 —— 与服务端 `/api/v1/inbox` 契约一致。
 *
 * **来源**：由 `admin-web/src/features/inbox/types.ts` 合并移植（字段逐字保留，未改契约）。
 * 契约原文见 `docs/api-contract.md`「站内通知（收件箱）」；服务端实现见 `app/inbox.py` +
 * `migrations/019_inbox_items.sql`。
 */

/** 通知类型（服务端 `kind` 全集）。 */
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

/** 通知目标的类型（决定"能不能从这里跳到目标页"）。 */
export type InboxTargetType =
  | 'task'
  | 'plan_proposal'
  | 'orchestration_proposal'
  | 'publication'
  | 'run'
  | 'crm_activity'
  | 'crm_contract'

export interface InboxItem {
  inbox_id: string
  kind: InboxKind
  title: string
  target_type: InboxTargetType | null
  target_id: string | null
  /** 服务端反查出的**上文标识**（可空）——有会话时用于直达「该会话（的该条卡）」。 */
  target_conversation_id: string | null
  target_approval_id: string | null
  created_at: string
  read_at: string | null
}

export interface InboxList {
  /** 硬标记：`true` = 开发期样例数据（界面必须显示「示例数据（未接后端）」）；`false` = 后端真实数据。 */
  sample: boolean
  items: InboxItem[]
  unread_count: number
}

/** 通知类型 → 中文标签（唯一来源；服务端新增 kind 时由 `inboxKindLabel` 兜底）。 */
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

/** 服务端新增 kind 时给出兜底文案，避免出现空白标签。 */
export function inboxKindLabel(kind: string): string {
  return INBOX_KIND_LABELS[kind as InboxKind] ?? '通知'
}

/** 目标类型 → 中文名（用于「为什么不能从这里打开」的如实说明）。 */
export const INBOX_TARGET_LABELS: Record<InboxTargetType, string> = {
  task: '任务详情',
  plan_proposal: '计划提案',
  orchestration_proposal: '编排优化提案',
  publication: '内容发布',
  run: '运行详情',
  crm_activity: 'CRM 跟进任务',
  crm_contract: 'CRM 合同',
}

/** 页内筛选档（**纯前端**，只作用于已加载的那一页数据，不改变任何服务端语义）。 */
export type InboxFilter = 'all' | 'unread'
