/**
 * 用量与费用 / 数据导出类型 —— 与服务端商业化契约一致（只读）。
 *
 * **来源**：由 `admin-web/src/features/billing/types.ts` 合并移植（字段逐字保留）。
 *
 * 契约面：
 *  - `GET  /api/v1/commercial/usage`
 *  - `POST /api/v1/commercial/exports`（异步作业，`202`）
 *  - `GET  /api/v1/commercial/exports?limit=&offset=`（导出包列表，不含载荷）
 *  - `GET  /api/v1/commercial/exports/{package_id}`（导出包全文，脱敏）
 *  - `GET  /api/v1/commercial/lifecycle/{job_id}`（作业状态）
 */

/** 累计用量与费用（服务端账本汇总）。 */
export interface UsageSummary {
  tenant_id: string
  units: number
  /** 累计费用，**整数分**；发生过冲正时可能为负。 */
  cost_cents: number
}

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

/** 导出包全文（取回）：载荷**只在下载时进入文件**，不渲染到页面上。 */
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
