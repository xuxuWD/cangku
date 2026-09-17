import { crmErrorFromStatus } from './state'
import type {
  CrmAccount,
  CrmAccountFilters,
  CrmActivity,
  CrmContact,
  CrmContract,
  CrmContractFilters,
  CrmInsight,
  CrmOpportunity,
  CrmOpportunityDetail,
  CrmOpportunityFilters,
  CrmPage,
  CrmProgressSummary,
  CrmQuote,
  CrmQuoteDetail,
  CrmQuoteFilters,
  CrmRevealField,
} from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw crmErrorFromStatus(0)
  }
  if (!response.ok) throw crmErrorFromStatus(response.status)
  return await response.json() as T
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

function params(entries: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(entries)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  return search.toString()
}

// ---------------------------------------------------------------- 客户 / 联系人 / 活动

export function listAccounts(filters: CrmAccountFilters): Promise<CrmPage<CrmAccount>> {
  return request<CrmPage<CrmAccount>>(`/crm/accounts?${params({ status: filters.status, limit: filters.limit, offset: filters.offset })}`)
}

export function getAccount(accountId: string): Promise<CrmAccount> {
  return request<CrmAccount>(`/crm/accounts/${encodeURIComponent(accountId)}`)
}

export function listContacts(accountId: string, limit = 50, offset = 0): Promise<CrmPage<CrmContact>> {
  return request<CrmPage<CrmContact>>(`/crm/accounts/${encodeURIComponent(accountId)}/contacts?${params({ limit, offset })}`)
}

// 敏感字段揭示：**专用端点**（POST，避免明文进浏览器历史 / 代理日志）；服务端独立判定权限并落审计。
export function revealContact(contactId: string, field: CrmRevealField): Promise<{ contact_id: string; field: string; value: string }> {
  return post(`/crm/contacts/${encodeURIComponent(contactId)}/reveal`, { field })
}

export function listActivities(query: { accountId?: string; opportunityId?: string; limit?: number; offset?: number }): Promise<CrmPage<CrmActivity>> {
  return request<CrmPage<CrmActivity>>(`/crm/activities?${params({ account_id: query.accountId, opportunity_id: query.opportunityId, limit: query.limit ?? 50, offset: query.offset ?? 0 })}`)
}

export function generateFollowupPlan(accountId: string): Promise<CrmInsight> {
  return post<CrmInsight>(`/crm/accounts/${encodeURIComponent(accountId)}/followup-plan`)
}

export function listInsights(accountId: string, limit = 50, offset = 0): Promise<CrmPage<CrmInsight>> {
  return request<CrmPage<CrmInsight>>(`/crm/accounts/${encodeURIComponent(accountId)}/insights?${params({ limit, offset })}`)
}

// ---------------------------------------------------------------- 商机

export function listOpportunities(filters: CrmOpportunityFilters & { accountId?: string }): Promise<CrmPage<CrmOpportunity>> {
  return request<CrmPage<CrmOpportunity>>(`/crm/opportunities?${params({ account_id: filters.accountId, stage: filters.stage, limit: filters.limit, offset: filters.offset })}`)
}

// 阶段迁移（白名单；非法 / 并发先写 ⇒ 409）。
export function changeOpportunityStage(opportunityId: string, toStage: string): Promise<CrmOpportunity> {
  return post<CrmOpportunity>(`/crm/opportunities/${encodeURIComponent(opportunityId)}/stage`, { to_stage: toStage })
}

// 商机详情 + 阶段事件时间线（append-only）。
export function getOpportunity(opportunityId: string): Promise<CrmOpportunityDetail> {
  return request<CrmOpportunityDetail>(`/crm/opportunities/${encodeURIComponent(opportunityId)}`)
}

// ---------------------------------------------------------------- 报价（金额由服务端重算）

export function listQuotes(filters: CrmQuoteFilters): Promise<CrmPage<CrmQuote>> {
  return request<CrmPage<CrmQuote>>(`/crm/quotes?${params({ status: filters.status, limit: filters.limit, offset: filters.offset })}`)
}

export function getQuote(quoteId: string): Promise<CrmQuoteDetail> {
  return request<CrmQuoteDetail>(`/crm/quotes/${encodeURIComponent(quoteId)}`)
}

export interface QuoteLineInput {
  description: string
  qty: string
  unit_price_cents: number
  tax_rate_bp: number
}

// 行全量替换（仅 draft；confirmed 冻结 ⇒ 409）。
export function replaceQuoteLines(quoteId: string, lines: QuoteLineInput[]): Promise<CrmQuoteDetail> {
  return request<CrmQuoteDetail>(`/crm/quotes/${encodeURIComponent(quoteId)}/lines`, { method: 'PUT', body: JSON.stringify({ lines }) })
}

export function confirmQuote(quoteId: string): Promise<CrmQuote> {
  return post<CrmQuote>(`/crm/quotes/${encodeURIComponent(quoteId)}/confirm`)
}

export function voidQuote(quoteId: string): Promise<CrmQuote> {
  return post<CrmQuote>(`/crm/quotes/${encodeURIComponent(quoteId)}/void`)
}

// 报价转合同（单事务；仅 confirmed）。
export function convertQuoteToContract(quoteId: string): Promise<CrmContract> {
  return post<CrmContract>(`/crm/quotes/${encodeURIComponent(quoteId)}/convert-to-contract`)
}

// ---------------------------------------------------------------- 合同（签署 / 回款均人工登记）

export function listContracts(filters: CrmContractFilters): Promise<CrmPage<CrmContract>> {
  return request<CrmPage<CrmContract>>(`/crm/contracts?${params({ status: filters.status, limit: filters.limit, offset: filters.offset })}`)
}

export function getContract(contractId: string): Promise<CrmContract> {
  return request<CrmContract>(`/crm/contracts/${encodeURIComponent(contractId)}`)
}

export function submitContractForSign(contractId: string): Promise<CrmContract> {
  return post<CrmContract>(`/crm/contracts/${encodeURIComponent(contractId)}/submit-for-sign`)
}

// 人工登记签署结果（本段无 provider；系统只做台账，不承诺法律效力）。
export function registerSignature(contractId: string, body: { signed_at: string; document_object_key?: string }): Promise<CrmContract> {
  return post<CrmContract>(`/crm/contracts/${encodeURIComponent(contractId)}/register-signature`, body)
}

// 人工登记回款（原子增量；超合同金额 ⇒ 409）。
export function registerPayment(contractId: string, amountCents: number): Promise<CrmContract> {
  return post<CrmContract>(`/crm/contracts/${encodeURIComponent(contractId)}/register-payment`, { amount_cents: amountCents })
}

export function voidContract(contractId: string): Promise<CrmContract> {
  return post<CrmContract>(`/crm/contracts/${encodeURIComponent(contractId)}/void`)
}

// ---------------------------------------------------------------- 进度概览

// `scope=all` 需管理角色（否则 403，服务端判定，前端不做权限判断）。
export function getProgressSummary(scope: 'me' | 'all'): Promise<CrmProgressSummary> {
  return request<CrmProgressSummary>(`/crm/progress/summary?${params({ scope })}`)
}