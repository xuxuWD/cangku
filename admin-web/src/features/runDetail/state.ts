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

// 干预类操作（暂停 / 恢复 / 取消）与验收决议的状态码映射：与读取类不同——这里的 409 是「当前状态不允许」，
// 服务端会带原因（如「运行已结束」「运行尚未结束，暂不能验收」），优先原样展示；
// 422 是「入参语义不合法」（如打回未写原因），同样优先展示服务端的中文原因；
// 401/403/404 用固定文案，不泄露内部细节。
export function runActionErrorFromStatus(status: number, detail?: string | null): RunErrorShape {
  const text = detail && detail.trim() ? detail.trim() : ''
  if (status === 401) return { status, message: '登录状态已失效，请重新登录后再试。', retryable: false }
  if (status === 403) return { status, message: text || '当前账号没有执行该操作的权限。', retryable: false }
  if (status === 404) return { status, message: '运行不存在，或你没有权限操作。', retryable: false }
  if (status === 409) return { status, message: text || '该运行当前的状态不允许此操作，正在刷新最新状态。', retryable: false }
  if (status === 422) return { status, message: text || '提交的内容不符合要求，请检查后重试。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_RUN_ERROR, retryable: true }
  return { status, message: DEFAULT_RUN_ERROR, retryable: false }
}
