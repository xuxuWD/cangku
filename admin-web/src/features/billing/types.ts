// 用量与费用前端类型：与服务端 GET /api/v1/commercial/usage 契约一致（只读）。
export interface UsageSummary {
  tenant_id: string
  units: number
  cost_cents: number
}

export interface BillingErrorShape {
  status: number
  message: string
  retryable: boolean
}

export interface BillingState {
  usage: UsageSummary | null
  loading: boolean
  error: BillingErrorShape | null
}
