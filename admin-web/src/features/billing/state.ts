import type { BillingErrorShape, BillingState, ExportSectionState } from './types'

const DEFAULT_BILLING_ERROR = '用量与费用服务暂时不可用，请检查网络后重新尝试。'
const DEFAULT_EXPORT_ERROR = '数据导出服务暂时不可用，请检查网络后重新尝试。'

export const initialBillingState: BillingState = { usage: null, loading: true, error: null }

export const initialExportState: ExportSectionState = {
  packages: [],
  total: 0,
  loading: true,
  error: null,
  phase: 'idle',
  jobId: null,
  requestError: null,
  downloadingId: null,
  downloadError: null,
  notice: null,
}

// 账本以**整数分**记账：这里用整数运算换算成元，绝不用浮点除法（避免 0.1+0.2 那类误差）。
// 冲正会写入负值记录，因此累计可能为负，需要正确显示负号。
export function formatCents(cents: number): string {
  const safe = Number.isFinite(cents) ? Math.trunc(cents) : 0
  const sign = safe < 0 ? '-' : ''
  const absolute = Math.abs(safe)
  return `${sign}¥${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}

// 固定中文提示：不透出服务端原始 detail，避免后端改词或换实现时界面文案漂移。
// `404` 是「本租户未在商业化模块登记」（常见态，不是故障），单独给出语义。
export function billingErrorFromStatus(status: number): BillingErrorShape {
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 403) return { status, message: '当前账号没有查看用量与费用的权限。', retryable: false }
  if (status === 404) return { status, message: '本租户尚未在商业化模块登记，暂时没有可展示的用量与费用。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_BILLING_ERROR, retryable: true }
  return { status, message: `请求不被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asBillingError(error: unknown): BillingErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_BILLING_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_BILLING_ERROR, retryable: true }
}

// ---------------------------------------------------------------------------
// B-1（2026-09-19）：数据导出的错误口径
// 与用量接口分开：403 的语义是「没有导出权限」，404 是「本租户未登记」，
// 二者都不该伪装成空态；只有网络/5xx 才给「重新尝试」。
// ---------------------------------------------------------------------------

export function exportErrorFromStatus(status: number): BillingErrorShape {
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 403) return { status, message: '当前账号没有查看数据导出的权限。', retryable: false }
  if (status === 404) return { status, message: '本租户尚未在商业化模块登记，暂时不能导出数据。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_EXPORT_ERROR, retryable: true }
  return { status, message: `请求不被接受（${status}）。`, retryable: false }
}

export function asExportError(error: unknown): BillingErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_EXPORT_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_EXPORT_ERROR, retryable: true }
}

/** 过期判定与服务端同口径：`expires_at <= 当前时刻` 即过期（正点即过期）。 */
export function isPackageExpired(expiresAt: string, now: number = Date.now()): boolean {
  const parsed = new Date(expiresAt).getTime()
  if (Number.isNaN(parsed)) return true // 时间不可解析时按「不可下载」处理（宁可保守）
  return parsed <= now
}
