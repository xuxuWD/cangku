/**
 * 「运行详情 / 运行干预」模块的**文案表、错误类与形状**（模块级唯一来源）。
 *
 * **来源**：由 `admin-web/src/features/runDetail/state.ts` 合并移植。
 *
 * ⚠️ **移植时的一处实质改动（如实登记）**：
 * 原实现的 `asRunError` 靠 `candidate.retryable !== false` 判断可重试。基座请求层抛的 `ApiError`
 * **没有 `retryable` 字段** ⇒ `undefined !== false` 恒为 `true`，会把 **403 也标成可重试**。
 * 故这里改为**按状态码判定**（`runRetryable`），并让服务层抛带状态码的 `RunError`。
 *
 * ⚠️ **两套口径必须分开**（原实现的设计，保留）：
 *  - **读取类**（`runErrorFromStatus`）：403/404 用固定文案，**不透出**服务端细节；
 *  - **干预类**（`runActionErrorFromStatus`）：暂停/恢复/取消/验收的 409 是「当前状态不允许」，
 *    服务端会带原因（如「运行已结束」），**优先原样展示**；422 同理。
 */
import { ServiceError, type ServiceFailure } from '../../utils/serviceKit'
import type { RunDetailState, RunErrorShape } from './types'

export const DEFAULT_RUN_ERROR = '运行服务暂时不可用，请检查网络后重新尝试。'

/** 可重试：网络失败与 5xx。其余（含 401/403/404/409/422）**不重试**。 */
export function runRetryable(status: number): boolean {
  return status === 0 || status >= 500
}

/** 适配层错误：带**状态码**，供 hook 的 `asRunError` 分流。 */
export class RunError extends ServiceError {
  readonly status: number

  constructor(message: string, failure: ServiceFailure, status: number) {
    super(message, failure)
    this.name = 'RunError'
    this.status = status
  }
}

/** 读取类：按状态码的固定文案（403 优先服务端友好文案）。 */
export function runErrorFromStatus(status: number, detail?: string | null): RunErrorShape {
  const text = detail?.trim() ?? ''
  if (status === 401) return { status, message: '当前账号没有查看该运行的权限。', retryable: false }
  if (status === 403) return { status, message: text || '当前账号没有执行该操作的权限。', retryable: false }
  if (status === 404) return { status, message: '运行不存在，或你没有权限查看。', retryable: false }
  if (status === 409) return { status, message: '该审批已决议，正在刷新最新状态。', retryable: false }
  return { status, message: DEFAULT_RUN_ERROR, retryable: runRetryable(status) }
}

/** 干预类：409 / 422 **优先原样展示服务端原因**；401/403/404 用固定文案（不泄露内部细节）。 */
export function runActionErrorFromStatus(status: number, detail?: string | null): RunErrorShape {
  const text = detail?.trim() ?? ''
  if (status === 401) return { status, message: '登录状态已失效，请重新登录后再试。', retryable: false }
  if (status === 403) return { status, message: text || '当前账号没有执行该操作的权限。', retryable: false }
  if (status === 404) return { status, message: '运行不存在，或你没有权限操作。', retryable: false }
  if (status === 409) return { status, message: text || '该运行当前的状态不允许此操作，正在刷新最新状态。', retryable: false }
  if (status === 422) return { status, message: text || '提交的内容不符合要求，请检查后重试。', retryable: false }
  return { status, message: DEFAULT_RUN_ERROR, retryable: runRetryable(status) }
}

/** 由本层错误构造形状（**文案已在服务层定好**，这里只补状态码与可重试性）。 */
export function runErrorShapeOf(error: RunError): RunErrorShape {
  return { status: error.status, message: error.message, retryable: runRetryable(error.status) }
}

/** 把任意异常规整成页面可直接展示的中文提示（**不吞异常语义**，只做形状归一）。 */
export function asRunError(error: unknown): RunErrorShape {
  if (error instanceof RunError) return runErrorShapeOf(error)
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    return {
      status,
      message: typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_RUN_ERROR,
      // ⚠️ 按状态码判定，**不**看 `candidate.retryable`（基座的 ApiError 没有这个字段 ⇒ 会恒真）
      retryable: runRetryable(status),
    }
  }
  return { status: 0, message: DEFAULT_RUN_ERROR, retryable: true }
}

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
