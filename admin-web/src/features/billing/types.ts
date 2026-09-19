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

// ---------------------------------------------------------------------------
// B-1（2026-09-19）：数据导出面 —— 与商业化导出契约一致
// （`GET/POST /commercial/exports`、`GET /commercial/exports/{package_id}`、
//  `GET /commercial/lifecycle/{job_id}`）。
// ---------------------------------------------------------------------------

/** 导出包元数据（列表面）：不含载荷。 */
export interface ExportPackageSummary {
  package_id: string
  tenant_id: string
  job_id: string | null
  created_at: string
  expires_at: string
}

export interface ExportPackageList {
  items: ExportPackageSummary[]
  total: number
  limit: number
  offset: number
}

/** 导出包全文（取回）：载荷只在下载时进入文件，不渲染到页面上。 */
export interface ExportPackageDetail extends ExportPackageSummary {
  payload: Record<string, unknown>
}

export interface LifecycleJob {
  job_id: string
  tenant_id: string
  kind: string
  status: string
  requested_by: string
  requested_at: string
  execute_after: string | null
  final_exported: boolean
}

/** 申请导出的推进阶段：提交中 → 等后台生成 → 已生成 / 超时未完成 / 提交失败。 */
export type ExportRequestPhase = 'idle' | 'requesting' | 'waiting' | 'done' | 'timeout' | 'failed'

export interface ExportSectionState {
  packages: ExportPackageSummary[]
  total: number
  loading: boolean
  error: BillingErrorShape | null
  phase: ExportRequestPhase
  jobId: string | null
  requestError: BillingErrorShape | null
  downloadingId: string | null
  downloadError: BillingErrorShape | null
  /** 阶段性如实说明（生成完成 / 下载已触发），非报错。 */
  notice: string | null
}
