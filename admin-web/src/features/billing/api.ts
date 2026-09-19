import { billingErrorFromStatus, exportErrorFromStatus } from './state'
import type { ExportPackageDetail, ExportPackageList, LifecycleJob, UsageSummary } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw billingErrorFromStatus(0)
  }
  if (!response.ok) throw billingErrorFromStatus(response.status)
  return await response.json() as T
}

async function exportRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...options, headers: headers(options.headers) })
  } catch {
    throw exportErrorFromStatus(0)
  }
  if (!response.ok) throw exportErrorFromStatus(response.status)
  return await response.json() as T
}

// 只读：复用既有商业化用量接口，不接受任何写动作。
export function getUsageSummary(): Promise<UsageSummary> {
  return request<UsageSummary>('/commercial/usage')
}

// ---------------------------------------------------------------------------
// B-1（2026-09-19）：数据导出闭环
// 申请（异步作业）→ 查作业状态确认生成 → 列出导出包 → 按包号取回载荷。
// 「列出」这一步是必需的：取回要 `package_id`，而申请响应与作业视图都不携带。
// ---------------------------------------------------------------------------

/** 申请租户数据导出（服务端只创建异步作业并返回 `202`）。 */
export function requestExport(): Promise<LifecycleJob> {
  return exportRequest<LifecycleJob>('/commercial/exports', { method: 'POST' })
}

/** 查导出作业状态（用于确认后台是否已生成导出包）。 */
export function getLifecycleJob(jobId: string): Promise<LifecycleJob> {
  return exportRequest<LifecycleJob>(`/commercial/lifecycle/${encodeURIComponent(jobId)}`)
}

/** 列出本租户已生成的导出包（元数据；不含载荷）。 */
export async function listExportPackages(limit = 20, offset = 0): Promise<ExportPackageList> {
  const page = await exportRequest<ExportPackageList>(`/commercial/exports?limit=${limit}&offset=${offset}`)
  // 边界校验（响应来自外部服务）：条目不是数组说明响应不符合契约 ⇒ 按「服务不可用（可重试）」处理，
  // 既不静默当成空列表，也不让一次异常响应把整页渲染打崩。
  if (!page || !Array.isArray(page.items)) throw exportErrorFromStatus(0)
  return page
}

/** 取回导出包全文（脱敏载荷）：只在「下载」动作里使用。 */
export function getExportPackage(packageId: string): Promise<ExportPackageDetail> {
  return exportRequest<ExportPackageDetail>(`/commercial/exports/${encodeURIComponent(packageId)}`)
}
