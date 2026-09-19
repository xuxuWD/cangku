/**
 * 统一请求层（第 6 轮 · 接线批 1）—— 全前端**唯一**发 HTTP 的地方。
 *
 * 纪律：
 *  ① 认证令牌只走 `Authorization: Bearer <token>` 头，**绝不进 URL / query / localStorage / 日志**；
 *     令牌取自会话（`sessionStorage`，键 `workbench.token`）。
 *  ② `401` 一律**清本地会话并抛错**（引导重新登录），**不做静默重试**；其余状态码不自动重试
 *     （重试在 queryClient 层统一关闭，避免放大限流与重复写）。
 *  ③ 错误文案：优先取服务端 `detail`（仅当它是"短且干净"的字符串），否则用本地固定文案；
 *     **绝不把堆栈 / SQL / 内部路径 / 服务端异常原文渲染到界面**。
 *  ④ 失败必须**抛错**，绝不静默返回空数据（空数据会被读成"真的没有内容"）。
 *  ⑤ 可注入 `fetchImpl`（测试用，不引 MSW），生产走全局 `fetch`。
 */
import { DETAIL_MAX_LENGTH, REQUEST_TIMEOUT_MS, buildUrl } from './config'
import type { QueryParams } from './config'
import { clearSession, readToken } from '../app/session'

/** 失败分类（界面据此决定四态与文案，不解析错误字符串）。 */
export type ApiFailure =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'unavailable'
  | 'failed'

export interface ApiErrorInit {
  status: number
  failure: ApiFailure
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly failure: ApiFailure

  constructor({ status, failure, message }: ApiErrorInit) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.failure = failure
  }
}

/** 状态码 → 分类与固定文案（**不把服务端原文直接给用户**）。 */
const STATUS_MAP: Record<number, { failure: ApiFailure; message: string }> = {
  400: { failure: 'failed', message: '请求参数有误，请检查后重试。' },
  401: { failure: 'unauthorized', message: '需要登录：登录状态已失效，请重新登录。' },
  403: { failure: 'forbidden', message: '无权限执行该操作。' },
  404: { failure: 'not_found', message: '请求的内容不存在或不可见。' },
  409: { failure: 'conflict', message: '与当前状态冲突，请刷新后重试。' },
  422: { failure: 'failed', message: '请求参数不合法，已拒绝。' },
  429: { failure: 'rate_limited', message: '操作过于频繁，请稍后重试。' },
  503: { failure: 'unavailable', message: '服务暂时不可用，请稍后重试或联系管理员。' },
}

/** 明显不该出现在界面上的内容（堆栈 / SQL / 数据库驱动原文 / 内部路径 / 源码位置）。 */
const UNSAFE_DETAIL = /traceback|\bat \w+\(|\/api\/|select\s+.*\bfrom\b|postgres|sqlite|psycopg|\.py:|\.tsx?:|file:\/\//i

/** 取 `detail`：只接受"短且干净"的字符串，其余返回 `undefined`（由调用方回落到固定文案）。 */
export function safeDetail(rawDetail: unknown): string | undefined {
  if (typeof rawDetail !== 'string') return undefined
  const text = rawDetail.trim()
  if (text.length === 0 || text.length > DETAIL_MAX_LENGTH) return undefined
  if (UNSAFE_DETAIL.test(text)) return undefined
  return text
}

/** 由响应构造 `ApiError`（含 401 清会话）。 */
function toApiError(status: number, payload: unknown): ApiError {
  const mapped = STATUS_MAP[status] ?? {
    failure: (status >= 500 ? 'unavailable' : 'failed') as ApiFailure,
    message: status >= 500 ? '服务暂时不可用，请稍后重试。' : '请求失败，请稍后重试。',
  }
  const detail = safeDetail((payload as { detail?: unknown } | null)?.detail)
  const error = new ApiError({ status, failure: mapped.failure, message: detail ?? mapped.message })
  if (mapped.failure === 'unauthorized') {
    // 令牌失效：清本地会话，界面据此回到登录页（不做静默重试、不假装还能用）
    clearSession()
  }
  return error
}

/** 解析响应体：先当 JSON，失败则当纯文本（`detail` 可能不是 JSON 对象）。 */
function parseBody(text: string): unknown {
  if (text.length === 0) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return { detail: text }
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  /** JSON 请求体（自动序列化并带 `Content-Type`）。 */
  body?: unknown
  query?: QueryParams
  signal?: AbortSignal
  /** 测试注入的 fetch（不引 MSW）；默认用全局 `fetch`。 */
  fetchImpl?: typeof fetch
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query } = options
  const doFetch = options.fetchImpl ?? globalThis.fetch
  const token = readToken()

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const forwardAbort = () => controller.abort()
  options.signal?.addEventListener('abort', forwardAbort)

  try {
    const response = await doFetch(buildUrl(path, query), {
      method,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: 'same-origin',
    })

    if (response.status === 204) return undefined as T

    const text = await response.text()
    if (!response.ok) throw toApiError(response.status, parseBody(text))

    const parsed = parseBody(text)
    return parsed as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    // 网络失败 / 超时 / 中止：一律"服务不可达"，不暴露底层错误原文
    throw new ApiError({ status: 0, failure: 'unavailable', message: '服务不可达：请检查网络后重试。' })
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', forwardAbort)
  }
}