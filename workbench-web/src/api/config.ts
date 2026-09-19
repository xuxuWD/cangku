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

/** 查询参数（`undefined` / `null` / 空串一律不拼进 URL）。 */
export type QueryParams = Record<string, string | number | boolean | undefined | null>

/** 拼 URL：所有键值都过 `encodeURIComponent`；**token 一律不进 URL**（只走 Authorization 头）。 */
export function buildUrl(path: string, query?: QueryParams): string {
  const base = `${API_BASE_URL}${path}`
  if (!query) return base
  const parts = Object.entries(query)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  return parts.length === 0 ? base : `${base}?${parts.join('&')}`
}