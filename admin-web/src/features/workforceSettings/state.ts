import type { DirectoryErrorShape, DirectoryState } from './types'

const DEFAULT_DIRECTORY_ERROR = '名单暂时读不出来，请检查网络后重新尝试。'
const INVALID_INPUT = '提交的内容不符合要求：标识只能是小写字母、数字、点、下划线与短横线，中文名不能为空。'

export const initialDirectoryState: DirectoryState = {
  tab: 'roles',
  roles: { items: [], total: 0, limit: 200, offset: 0 },
  agents: { items: [], total: 0, limit: 200, offset: 0 },
  candidates: { roles: [], agents: [] },
  loading: true,
  error: null,
  saving: false,
  formError: null,
  toast: null,
}

// 按 HTTP 状态码映射为固定中文提示。
// 仅当服务端返回的 `detail` 是**字符串**时才透出（那是我们自己的中文文案）；
// Pydantic 的参数校验错误 `detail` 是数组，一律丢弃，避免把校验结构 dump 到界面。
export function directoryErrorFromStatus(status: number, detail?: string | null): DirectoryErrorShape {
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 403) return { status, message: '当前账号没有管理岗位与数字员工的权限。', retryable: false }
  if (status === 404) return { status, message: '该岗位或数字员工不存在，可能已被移除。', retryable: false }
  if (status === 409) return { status, message: detail || '该标识已存在，或所属岗位不可用。', retryable: false }
  if (status === 422) return { status, message: detail || INVALID_INPUT, retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_DIRECTORY_ERROR, retryable: true }
  return { status, message: `请求不被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asDirectoryError(error: unknown): DirectoryErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_DIRECTORY_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_DIRECTORY_ERROR, retryable: true }
}
