/**
 * 认证适配层（第 6 轮 · 接线批 1）：登录 / 登出 —— 只走 `src/api/client.ts`（唯一 HTTP 出口）。
 *
 * 字段与后端**逐字一致**（`app/main.py:4582` 的 `SessionCreate`，`extra="forbid"`）：
 * 只发 `phone` / `password` / `totp_code` 三个键，多一个字段会被后端 `422` 拒绝。
 */
import { request } from '../../../api/client'
import type { Role } from '../../../app/session'

/**
 * 建会话响应（`app/main.py:4825` 的实际键，逐个点名）：
 * `access_token` / `token_type` / `expires_in` / `tenant_id` / `user_id` / `role` / `scope`。
 * **没有**展示名字段（界面因此只用角色名，不编造姓名）。
 */
export interface SessionResponse {
  access_token: string
  token_type: string
  expires_in: number
  tenant_id: string
  user_id: string
  role: Role
  scope: string
}

/** 受限会话范围：`app/auth.py:14` 的 `totp_enrollment`（动态验证码登记中，权限受限）。 */
export const TOTP_ENROLLMENT_SCOPE = 'totp_enrollment'

export interface LoginInput {
  phone: string
  password: string
  totp_code?: string
  /** 测试注入的 fetch（不引 MSW）。 */
  fetchImpl?: typeof fetch
}

/** 登录：`POST /api/v1/auth/sessions`。失败一律抛 `ApiError`（含 401 / 429 / 503 的固定文案）。 */
export async function login(input: LoginInput): Promise<SessionResponse> {
  return request<SessionResponse>('/api/v1/auth/sessions', {
    method: 'POST',
    body: { phone: input.phone, password: input.password, totp_code: input.totp_code },
    fetchImpl: input.fetchImpl,
  })
}

/**
 * 登出：`POST /api/v1/auth/logout`（204，服务端把该令牌 jti 记入撤销名单，立即失效）。
 * 失败必须如实抛错 —— 调用方**仍需清本地**，但不能假装"服务端也退干净了"。
 */
export async function logout(fetchImpl?: typeof fetch): Promise<void> {
  await request<void>('/api/v1/auth/logout', { method: 'POST', fetchImpl })
}