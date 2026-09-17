// CRM（P5a）前端类型：与服务端 `/api/v1/crm/*` 契约（docs/api-contract.md「CRM（P5a）」章节）保持一致。
// 金额一律为**整数分**（`*_cents`）；日期为 `YYYY-MM-DD`，时间戳为 ISO 串。

export type CrmAccountStatus = 'active' | 'inactive'
export type CrmHealthBand = 'green' | 'yellow' | 'red'
export type CrmOpportunityStage = 'qualification' | 'proposal' | 'negotiation' | 'won' | 'lost'
export type CrmQuoteStatus = 'draft' | 'confirmed' | 'converted' | 'voided'
export type CrmContractStatus = 'draft' | 'pending_sign' | 'signed' | 'voided' | 'expired'
export type CrmActivityKind = 'call' | 'meeting' | 'email' | 'note' | 'task'
export type CrmActivityStatus = 'planned' | 'done' | 'cancelled'
export type CrmRevealField = 'phone' | 'email'
export type CrmScope = 'me' | 'all'

export interface CrmAccount {
  account_id: string
  name: string
  industry: string
  source: string
  status: string
  owner_id: string
  custom_fields: Record<string, unknown>
  // 未计算 = null（**不伪造 0 分**，契约 §「健康度 NULL 语义」）。
  health_score: number | null
  health_band: string | null
  health_computed_at: string | null
  created_at: string
  updated_at: string
}

export interface CrmContact {
  contact_id: string
  account_id: string | null
  name: string
  title: string
  phone: string
  email: string
  is_primary: boolean
  birthday: string | null
  owner_id: string
  custom_fields: Record<string, unknown>
  created_at: string
}

export interface CrmOpportunity {
  opportunity_id: string
  account_id: string
  name: string
  stage: string
  amount_cents: number
  expected_close: string | null
  owner_id: string
  stage_entered_at: string
  closed_at: string | null
  custom_fields: Record<string, unknown>
  created_at: string
}

export interface CrmActivity {
  activity_id: string
  kind: string
  subject: string
  account_id: string | null
  contact_id: string | null
  opportunity_id: string | null
  owner_id: string
  status: string
  due_at: string | null
  occurred_at: string
  created_by_kind: string
}

export interface CrmQuoteLine {
  line_no: number
  description: string
  qty: string | number
  unit_price_cents: number
  tax_rate_bp: number
  line_subtotal_cents: number
  line_tax_cents: number
}

export interface CrmQuote {
  quote_id: string
  account_id: string
  opportunity_id: string | null
  quote_no: string
  status: string
  subtotal_cents: number
  tax_cents: number
  total_cents: number
  valid_until: string | null
  confirmed_at: string | null
  converted_contract_id: string | null
  owner_id: string
  created_at: string
}

export interface CrmQuoteDetail {
  quote: CrmQuote
  lines: CrmQuoteLine[]
}

export interface CrmContract {
  contract_id: string
  account_id: string
  quote_id: string | null
  opportunity_id: string | null
  contract_no: string
  title: string
  status: string
  amount_cents: number
  paid_cents: number
  starts_on: string | null
  ends_on: string | null
  document_object_key: string
  signed_at: string | null
  owner_id: string
  created_at: string
}

export interface CrmFollowupAction {
  action_type: string
  target_ref: string
  reason: string
  evidence_refs: string[]
  confidence: number
}

export interface CrmInsightContent {
  actions: CrmFollowupAction[]
  summary: string
  insufficient_evidence?: boolean
}

export interface CrmDroppedRef {
  reason: string
  raw?: unknown
}

export interface CrmInsight {
  insight_id: string
  account_id: string
  kind: string
  content: CrmInsightContent
  evidence_refs: string[]
  dropped_refs: CrmDroppedRef[]
  model_key: string
  generated_by: string
  created_at: string
}

export interface CrmProgressSummary {
  // 分母为零一律 null（`no_target` 由 note 标注），前端必须显示「无目标」/「—」而不是 0。
  pipeline_coverage: number | null
  pipeline_coverage_note: string
  win_rate: number | null
  sales_cycle_days: number | null
  stage_conversion: Record<string, number | null>
  pipeline_age_days: number | null
  creation_rate_30d: number
  health_distribution: Record<string, number>
  renewal_window_count: number
  renewal_window_amount_cents: number
  payment_progress: number | null
  overdue_contract_count: number
  target_attainment_amount: number | null
  target_attainment_count: number | null
  target_note: string
}

export interface CrmPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface CrmErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface CrmAccountFilters {
  status: string
  limit: number
  offset: number
}

export interface CrmOpportunityFilters {
  stage: string
  limit: number
  offset: number
}

export interface CrmQuoteFilters {
  status: string
  limit: number
  offset: number
}

export interface CrmContractFilters {
  status: string
  limit: number
  offset: number
}

export const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  active: '活跃',
  inactive: '停用',
}

export const HEALTH_BAND_LABELS: Record<string, string> = {
  green: '健康',
  yellow: '关注',
  red: '风险',
}

export const OPPORTUNITY_STAGE_LABELS: Record<string, string> = {
  qualification: '资格确认',
  proposal: '方案报价',
  negotiation: '商务谈判',
  won: '赢单',
  lost: '输单',
}

// 进行中阶段（与后端 `_ACTIVE_STAGES` 同口径：终态不计管线）。
export const ACTIVE_OPPORTUNITY_STAGES: string[] = ['qualification', 'proposal', 'negotiation']

// 阶段机合法迁移白名单（唯一事实源：crm-p5a-design §2.3；终态不可回迁）。
export const OPPORTUNITY_STAGE_TRANSITIONS: Record<string, string[]> = {
  qualification: ['proposal', 'lost'],
  proposal: ['negotiation', 'lost'],
  negotiation: ['won', 'lost'],
  won: [],
  lost: [],
}

export const QUOTE_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认（冻结）',
  converted: '已转合同',
  voided: '已作废',
}

export const CONTRACT_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  pending_sign: '待签署',
  signed: '已签署（人工登记）',
  voided: '已作废',
  expired: '已到期',
}

export const ACTIVITY_KIND_LABELS: Record<string, string> = {
  call: '电话',
  meeting: '会议',
  email: '邮件',
  note: '备注',
  task: '任务',
}

export const ACTIVITY_STATUS_LABELS: Record<string, string> = {
  planned: '待办',
  done: '已完成',
  cancelled: '已取消',
}

// 跟进计划候选动作集（§2.7 固定枚举）。
export const FOLLOWUP_ACTION_LABELS: Record<string, string> = {
  call: '电话跟进',
  send_material: '发送资料',
  book_demo: '预约演示',
  send_quote: '发送报价',
  renewal_reminder: '续约提醒',
  escalate: '升级处理',
  park: '暂时搁置',
}

// 证据引用被丢弃的原因（结构层 + 引用校验层，§2.7）。
export const DROPPED_REF_LABELS: Record<string, string> = {
  invalid_action: '条目结构不合法',
  invalid_action_type: '动作类型不在候选集',
  invalid_target_ref: '目标引用无效或不属于本客户',
  invalid_evidence_ref: '证据引用无效或不属于本客户',
  too_many_actions: '动作条数超上限',
  missing_actions: '缺少 actions 字段',
}

// 标签缺失时回落显示原值，避免出现空白。
export function crmLabel(labels: Record<string, string>, key: string | null | undefined): string {
  if (!key) return '—'
  return labels[key] ?? key
}