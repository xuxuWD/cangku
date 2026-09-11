import type { RunDetailState, RunErrorShape } from './types'

const DEFAULT_RUN_ERROR = '运行服务暂时不可用，请检查网络后重新尝试。'

export const initialRunDetailState: RunDetailState = {
  metrics: null,
  task: null,
  events: [],
  approvals: [],
  metricsError: null,
  taskError: null,
  eventsError: null,
  approvalsError: null,
  loadingOverview: true,
  loadingEvents: true,
  loadingApprovals: true,
  decidingId: null,
  toast: null,
}

// 按 HTTP 状态码映射为固定中文提示，不把堆栈、URL 或原始异常文本透到界面。
export function runErrorFromStatus(status: number, detail?: string | null): RunErrorShape {
  if (status === 401) return { status, message: '当前账号没有查看该运行的权限。', retryable: false }
  // 403 优先展示后端友好文案（如「发起人不能审批自己发起的运行」）。
  if (status === 403) return { status, message: detail && detail.trim() ? detail.trim() : '当前账号没有执行该操作的权限。', retryable: false }
  if (status === 404) return { status, message: '运行不存在，或你没有权限查看。', retryable: false }
  if (status === 409) return { status, message: '该审批已决议，正在刷新最新状态。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_RUN_ERROR, retryable: true }
  return { status, message: DEFAULT_RUN_ERROR, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asRunError(error: unknown): RunErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_RUN_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_RUN_ERROR, retryable: true }
}
