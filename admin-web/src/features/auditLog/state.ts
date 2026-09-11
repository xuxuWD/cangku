import type { AuditErrorShape, AuditFilters, AuditLogState } from './types'

const DEFAULT_AUDIT_ERROR = '审计服务暂时不可用，请检查网络后重新尝试。'

export const initialAuditFilters: AuditFilters = { actions: [], actorId: '', targetType: '', targetId: '', since: '', until: '', limit: 50, offset: 0 }

export const initialAuditLogState: AuditLogState = { items: [], total: 0, loading: true, error: null }

// 按 HTTP 状态码映射为固定中文提示，不把堆栈、URL 或原始异常文本透到界面。
export function auditErrorFromStatus(status: number): AuditErrorShape {
  if (status === 403) return { status, message: '当前账号没有查看审计日志的权限。', retryable: false }
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_AUDIT_ERROR, retryable: true }
  return { status, message: `请求参数不被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asAuditError(error: unknown): AuditErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_AUDIT_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_AUDIT_ERROR, retryable: true }
}
