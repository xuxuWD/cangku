import type { ApiErrorShape, InboxState } from './types'

export const initialInboxState: InboxState = { items: [], unreadCount: 0, loading: true, error: null, markingId: null, markingAll: false, toast: null }

// 把接口层抛出的错误规整成页面可直接展示的中文提示，不暴露技术细节。
export function asInboxError(error: unknown): ApiErrorShape {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const candidate = error as Partial<ApiErrorShape>
    return { status: candidate.status || 0, message: candidate.message || '请求暂时无法完成。', retryable: candidate.retryable !== false, unauthorized: candidate.unauthorized === true }
  }
  return { status: 0, message: '通知服务暂时不可用，请检查网络后重新尝试。', retryable: true, unauthorized: false }
}
