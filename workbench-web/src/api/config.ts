/**
 * API 基础配置（第 6 轮 · 接线批 1）—— 后端地址**只有一个来源**。
 *
 * - `VITE_API_BASE_URL` 默认空 = **同源**：开发期由 Vite dev proxy 把 `/api` 转发到
 *   `http://127.0.0.1:8000`（见 `vite.config.ts` 的 `server.proxy`），生产期前后端同域部署（反代）。
 *   这样可绕开后端 fail-closed 的 CORS（空配置 = 不允许跨源）。
 * - **代码里不写死任何内网地址 / 端口 / 密钥**：换环境只改配置（配置外置）。
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/** 单请求超时（毫秒）。超时按"服务不可达"处理，**不静默重试**（重试会放大限流与重复写）。 */
export const REQUEST_TIMEOUT_MS = 10_000

/**
 * 错误文案的最大长度：服务端 `detail` 只取"短文案"，超长一律回落到本地固定文案，
 * 避免把堆栈 / SQL / 内部路径渲染到界面（见 `client.ts` 的 sanitize）。
 */
export const DETAIL_MAX_LENGTH = 120

/**
 * 查询参数（`undefined` / `null` / 空串一律不拼进 URL）。
 *
 * 值可以是**数组**（第 10 轮新增）：审计接口的 `action` 是**可重复 query**
 * （`?action=a&action=b`，见 `app/main.py` 的 `Query(list[str])`）⇒ 需要按重复键展开，
 * 逗号拼接**不被 FastAPI 识别**。
 */
export type QueryValue = string | number | boolean | undefined | null | readonly string[]
export type QueryParams = Record<string, QueryValue>

/** 拼 URL：所有键值都过 `encodeURIComponent`；**token 一律不进 URL**（只走 Authorization 头）。 */
export function buildUrl(path: string, query?: QueryParams): string {
  const base = `${API_BASE_URL}${path}`
  if (!query) return base
  const parts: string[] = []
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      // 数组值 ⇒ 重复键（空串项与空数组一律不拼）
      for (const item of value) {
        if (item === '') continue
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(item)}`)
      }
      continue
    }
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  }
  return parts.length === 0 ? base : `${base}?${parts.join('&')}`
}