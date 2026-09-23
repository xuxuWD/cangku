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
  /** 服务端自己写的、已 sanitize 的 `detail`（**没有则为 `undefined`**）。 */
  detail?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly failure: ApiFailure
  /**
   * **服务端自己写的中文原因**（已 sanitize），没有则为 `undefined`。
   *
   * ⚠️ 为什么单独留一个字段、而不是让调用方去翻 `message`：
   * `message` 是"服务端 detail **或**本层兜底文案"二选一的结果，**从外面分不出是哪个**。
   * 业务模块（对话 / 运行）都有**比自己兜底更具体**的文案，得靠这个字段才知道
   * "服务端到底说没说"。2026-09-23 合并 `runDetail` 时被一条用例照出来
   * （干预类 409 无服务端原因时，误把基座兜底文案当成了服务端原因）。
   */
  readonly detail?: string

  constructor({ status, failure, message, detail }: ApiErrorInit) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.failure = failure
    this.detail = detail
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
  const error = new ApiError({ status, failure: mapped.failure, message: detail ?? mapped.message, detail })
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
  // 受控枚举：与后端契约实际使用的方法集一致（`PUT` 是知识访问绑定的写路径，
  // 第 6 轮补入；此前缺它导致调用方只能做类型收窄 —— 见 decision-log 清理清单）。
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON 请求体（自动序列化并带 `Content-Type`）。 */
  body?: unknown
  query?: QueryParams
  signal?: AbortSignal
  /** 测试注入的 fetch（不引 MSW）；默认用全局 `fetch`。 */
  fetchImpl?: typeof fetch
  /**
   * 覆盖 `Accept`（默认由 `request` / `requestRaw` 决定）。
   * 2026-09-23 新增，用途只有一个：**SSE 读流**要 `text/event-stream`。
   */
  accept?: string
  /**
   * 追加自定义请求头（如 SSE 续播的 `Last-Event-ID`）。
   *
   * ⚠️ **不得用来传认证令牌** —— 令牌由本层从会话注入。为防止被绕过，
   * `Authorization` 在拼装时**排在最后**，调用方传什么都不可能覆盖它。
   */
  headers?: Record<string, string>
  /**
   * **长连接 / 流式响应**专用（2026-09-23 新增，用途只有 SSE）。
   *
   * 不加这个开关会踩两个坑（都由 `features/conversation` 的移植用例当场照出来）：
   *  ① **超时**：默认 `REQUEST_TIMEOUT_MS` 会在 10 秒时把整条流掐断 —— 长连接本来就会超过它；
   *  ② **中止失效**：默认在响应头到达后（`performRequest` 的 `finally`）就**拆掉** abort 转发，
   *     而流式响应此时才开始读体 ⇒ 调用方之后再怎么 `abort()` 都传不到底层 `fetch`，
   *     **流永远停不下来**（用例名：「切走即断」）。
   *
   * 置 `true` 时：**不设超时**，且 abort 转发**保留到调用方中止为止**（中止时自行摘除监听，不泄漏）。
   */
  streaming?: boolean
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await performRequest(path, options, 'application/json')
  if (response.status === 204) return undefined as T
  return parseBody(await response.text()) as T
}

/**
 * **原始响应**（第 13 轮新增）：给"不能走 JSON 解析"的请求用（目前只有**审计导出**的文件下载）。
 *
 * 与 `request` **共用同一份** 令牌注入 / 超时 / 错误映射（`performRequest`）——
 * 本文件仍是全前端**唯一**发 HTTP 的地方，调用方不得自己 `fetch`。
 */
export async function requestRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  return performRequest(path, options, '*/*')
}

/** 发请求 + 统一错误映射：`request` 与 `requestRaw` 的唯一实现。 */
async function performRequest(
  path: string,
  options: RequestOptions,
  accept: string,
): Promise<Response> {
  const { method = 'GET', body, query, accept: acceptOverride, headers: extraHeaders } = options
  const doFetch = options.fetchImpl ?? globalThis.fetch
  const token = readToken()

  const controller = new AbortController()
  // 流式（长连接）不设请求超时 —— 它本来就是长命连接（见 RequestOptions.streaming）
  const timer = options.streaming ? undefined : setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const forwardAbort = () => {
    controller.abort()
    // 流式下监听要留到中止为止；中止即自行摘除，避免泄漏
    options.signal?.removeEventListener('abort', forwardAbort)
  }
  options.signal?.addEventListener('abort', forwardAbort)

  try {
    const response = await doFetch(buildUrl(path, query), {
      method,
      headers: {
        Accept: acceptOverride ?? accept,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        // 调用方自定义头排在**认证之前**：`Authorization` 永远由本层决定，不可被覆盖
        ...extraHeaders,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: 'same-origin',
    })

    if (!response.ok) {
      const text = await response.text()
      throw toApiError(response.status, parseBody(text))
    }

    return response
  } catch (error) {
    if (error instanceof ApiError) throw error
    // 网络失败 / 超时 / 中止：一律"服务不可达"，不暴露底层错误原文
    throw new ApiError({ status: 0, failure: 'unavailable', message: '服务不可达：请检查网络后重试。' })
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    // ⚠️ 流式响应在**响应头到达**时本函数就返回，后面调用方才开始读体 ⇒
    // 此时**不能**摘掉转发，否则读体期间中止不了（用例「切走即断」就是照这个的）。
    if (!options.streaming) options.signal?.removeEventListener('abort', forwardAbort)
  }
}