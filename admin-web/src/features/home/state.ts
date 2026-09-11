import type { HomeErrorShape, HomeState } from './types'

const DEFAULT_HOME_ERROR = '工作台服务暂时不可用，请检查网络后重新尝试。'

export const initialHomeState: HomeState = {
  employees: [],
  employeesLoading: true,
  employeesError: null,
  drafts: [],
  draftsLoading: true,
  draftsError: null,
  submitting: false,
  submitError: null,
  toast: null,
}

// 按 HTTP 状态码映射为固定中文提示，不把堆栈、URL 或原始异常文本透到界面。
export function homeErrorFromStatus(status: number, detail?: string | null): HomeErrorShape {
  if (status === 403) return { status, message: detail || '当前岗位不能创建任务，请联系管理员调整权限。', retryable: false }
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 409) return { status, message: detail || '同一请求已提交过，请勿重复创建。', retryable: false }
  if (status === 422) return { status, message: detail || '任务描述或执行人不符合要求，请检查后重试。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_HOME_ERROR, retryable: true }
  return { status, message: detail || `请求未被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asHomeError(error: unknown): HomeErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_HOME_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_HOME_ERROR, retryable: true }
}
