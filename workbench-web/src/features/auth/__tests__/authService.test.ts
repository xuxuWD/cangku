/**
 * 认证适配层用例（第 6 轮 · 接线批 1）。
 *
 * 重点：**字段与服务端逐字对齐**（`app/main.py:4803` 的 `SessionCreate`，`extra="forbid"`）——
 * 只发 `phone` / `password` / `totp_code` 三个键，多一个字段会被后端 `422` 拒绝；响应字段逐个点名核对。
 */
import { TOTP_ENROLLMENT_SCOPE, login, logout } from '../services/authService'
import type { SessionResponse } from '../services/authService'

/** 最小 `fetch` 桩：只实现请求层用到的三样（`status` / `ok` / `text`）。 */
function stubFetch(reply: { status?: number; body?: unknown } = {}) {
  const { status = 200, body } = reply
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  return { fetchImpl, calls }
}

/** 服务端实际返回的键（`app/main.py:4825`），一个不多一个不少。 */
const SESSION: SessionResponse = {
  access_token: 'token-abc',
  token_type: 'Bearer',
  expires_in: 3600,
  tenant_id: 'tenant-0001',
  user_id: 'user-0001',
  role: 'employee',
  scope: 'full',
}

describe('authService 适配层', () => {
  it('登录：POST /api/v1/auth/sessions，body 只含 phone / password / totp_code', async () => {
    const { fetchImpl, calls } = stubFetch({ body: SESSION })

    const session = await login({ phone: '13800000000', password: 'pw-123456', fetchImpl })

    expect(calls[0].url).toBe('/api/v1/auth/sessions')
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      phone: '13800000000',
      password: 'pw-123456',
      totp_code: undefined,
    })
    // 未填验证码时该键被序列化丢弃（后端 `extra="forbid"`，多键即 422）
    expect(Object.keys(JSON.parse(String(calls[0].init.body)))).toEqual(['phone', 'password'])
    expect(session).toEqual(SESSION)
  })

  it('登录：响应字段逐个点名（access_token / token_type / expires_in / tenant_id / user_id / role / scope）', async () => {
    const { fetchImpl } = stubFetch({ body: SESSION })

    const session = await login({ phone: '13800000000', password: 'pw-123456', totp_code: '123456', fetchImpl })

    expect(Object.keys(session).sort()).toEqual([
      'access_token',
      'expires_in',
      'role',
      'scope',
      'tenant_id',
      'token_type',
      'user_id',
    ])
    // **没有**展示名字段：界面因此只用角色名，不编造姓名
    expect(Object.keys(session)).not.toContain('display_name')
  })

  it('登录失败：401 透传服务端短文案（密码错 / 需要动态验证码）', async () => {
    const wrongPassword = stubFetch({ status: 401, body: { detail: '手机号或密码不正确' } })
    await expect(login({ phone: '13800000000', password: 'bad', fetchImpl: wrongPassword.fetchImpl })).rejects.toMatchObject(
      { status: 401, failure: 'unauthorized', message: '手机号或密码不正确' },
    )

    const needTotp = stubFetch({ status: 401, body: { detail: '需要动态验证码' } })
    await expect(login({ phone: '13800000000', password: 'pw', fetchImpl: needTotp.fetchImpl })).rejects.toMatchObject({
      status: 401,
      message: '需要动态验证码',
    })
  })

  it('登录失败：429 / 503 分类正确（限流与服务未就绪都不静默吞掉）', async () => {
    const limited = stubFetch({ status: 429, body: { detail: '登录尝试过于频繁，请稍后再试' } })
    await expect(login({ phone: '13800000000', password: 'pw', fetchImpl: limited.fetchImpl })).rejects.toMatchObject({
      status: 429,
      failure: 'rate_limited',
    })

    const noSecret = stubFetch({ status: 503, body: { detail: '会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET' } })
    await expect(login({ phone: '13800000000', password: 'pw', fetchImpl: noSecret.fetchImpl })).rejects.toMatchObject({
      status: 503,
      failure: 'unavailable',
    })
  })

  it('登出：POST /api/v1/auth/logout（204 无响应体），失败必须抛错而不是假装成功', async () => {
    const ok = stubFetch({ status: 204 })
    await expect(logout(ok.fetchImpl)).resolves.toBeUndefined()
    expect(ok.calls[0].url).toBe('/api/v1/auth/logout')
    expect(ok.calls[0].init.method).toBe('POST')

    const failed = stubFetch({ status: 401, body: { detail: '请使用有效的登录凭证' } })
    await expect(logout(failed.fetchImpl)).rejects.toMatchObject({ status: 401, failure: 'unauthorized' })
  })

  it('受限会话范围常量与后端一致（`app/auth.py`）', () => {
    expect(TOTP_ENROLLMENT_SCOPE).toBe('totp_enrollment')
  })
})