/**
 * 统一请求层用例（第 6 轮 · 接线批 1）。
 *
 * 覆盖四件必须成立的事：
 *  ① 令牌只进 `Authorization` 头，**绝不进 URL**（header 断言 + URL 反断言）；
 *  ② `401` 一律清本地会话（回到登录页），其余状态码不自动重试；
 *  ③ 失败分类与固定文案（400/403/404/409/422/429/503/网络失败）；
 *  ④ 服务端 `detail` 只取"短且干净"的字符串，堆栈 / SQL / 内部路径一律丢弃。
 */
import { ApiError, request, safeDetail } from '../client'
import { DETAIL_MAX_LENGTH } from '../config'
import { ROLE_STORAGE_KEY, TOKEN_STORAGE_KEY, useSession } from '../../app/session'
import { signInAs, signOutForTest } from '../../test/renderWithProviders'

/** 最小 `fetch` 桩：只实现请求层用到的三样（`status` / `ok` / `text`），不发真实网络请求。 */
function stubFetch(reply: { status?: number; body?: unknown; text?: string } = {}) {
  const { status = 200, body, text } = reply
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (text !== undefined ? text : body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return calls
}

/** 取请求头（`Init` 里是普通对象，测试里直接按字典读）。 */
function headersOf(call: { init: RequestInit }): Record<string, string> {
  return call.init.headers as Record<string, string>
}

describe('统一请求层 client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    signOutForTest()
  })

  it('已登录：令牌只进 Authorization 头，不出现在 URL 里；查询参数照常拼接', async () => {
    signInAs('employee')
    const calls = stubFetch({ body: { ok: true } })

    await request('/api/v1/inbox', { query: { unread_only: true, limit: 50 } })

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/v1/inbox?unread_only=true&limit=50')
    expect(calls[0].url).not.toContain('test-token')
    expect(headersOf(calls[0]).Authorization).toBe('Bearer test-token')
  })

  it('未登录：不带 Authorization 头（后端据此返回 401）', async () => {
    signOutForTest()
    const calls = stubFetch({ body: {} })

    await request('/api/v1/inbox')

    expect(headersOf(calls[0]).Authorization).toBeUndefined()
  })

  it('POST：请求体序列化并带 Content-Type；GET 不带（少一个头）', async () => {
    signInAs('employee')
    const calls = stubFetch({ body: {} })

    await request('/api/v1/auth/sessions', { method: 'POST', body: { phone: '13800000000', password: 'pw' } })
    await request('/api/v1/inbox')

    expect(calls[0].init.method).toBe('POST')
    expect(calls[0].init.body).toBe('{"phone":"13800000000","password":"pw"}')
    expect(headersOf(calls[0])['Content-Type']).toBe('application/json')
    expect(calls[1].init.method).toBe('GET')
    expect(calls[1].init.body).toBeUndefined()
    expect(headersOf(calls[1])['Content-Type']).toBeUndefined()
  })

  it('401：清本地会话（令牌 + 角色）并抛 unauthorized，界面据此回到登录页', async () => {
    signInAs('employee')
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('test-token')
    stubFetch({ status: 401, body: { detail: '登录凭证已失效，请重新登录' } })

    const error = await request('/api/v1/inbox').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, failure: 'unauthorized' })
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    expect(sessionStorage.getItem(ROLE_STORAGE_KEY)).toBeNull()
    expect(useSession.getState().status).toBe('anonymous')
    expect(useSession.getState().role).toBeNull()
  })

  it('403 / 404 / 409 / 429 / 503：分类正确，且无 detail 时回落到本地固定文案', async () => {
    const cases: [number, string, string][] = [
      [403, 'forbidden', '无权限执行该操作。'],
      [404, 'not_found', '请求的内容不存在或不可见。'],
      [409, 'conflict', '与当前状态冲突，请刷新后重试。'],
      [429, 'rate_limited', '操作过于频繁，请稍后重试。'],
      [503, 'unavailable', '服务暂时不可用，请稍后重试或联系管理员。'],
    ]

    for (const [status, failure, message] of cases) {
      stubFetch({ status })
      const error = await request('/api/v1/inbox').catch((caught: unknown) => caught)
      expect(error).toMatchObject({ status, failure, message })
    }

    // 非 401 不得清会话（403 只是"无权限"，不是"登录失效"）
    signInAs('employee')
    stubFetch({ status: 403 })
    await request('/api/v1/inbox').catch(() => undefined)
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('test-token')
  })

  it('干净的短 detail 优先于固定文案；脏 detail（堆栈 / SQL / 路径）被丢弃', async () => {
    stubFetch({ status: 401, body: { detail: '需要动态验证码' } })
    await expect(request('/api/v1/auth/sessions', { method: 'POST', body: {} })).rejects.toMatchObject({
      message: '需要动态验证码',
    })

    stubFetch({ status: 400, body: { detail: 'Traceback (most recent call last): File "/app/main.py", line 1' } })
    await expect(request('/api/v1/inbox')).rejects.toMatchObject({
      status: 400,
      message: '请求参数有误，请检查后重试。',
    })
  })

  it('网络失败：归类 unavailable 并给"服务不可达"，不暴露底层错误原文', async () => {
    vi.stubGlobal(
      'fetch',
      (async () => {
        throw new TypeError('Failed to fetch: ECONNREFUSED 127.0.0.1:8000')
      }) as unknown as typeof fetch,
    )

    const error = await request('/api/v1/inbox').catch((caught: unknown) => caught)

    expect(error).toMatchObject({ status: 0, failure: 'unavailable', message: '服务不可达：请检查网络后重试。' })
    expect((error as Error).message).not.toMatch(/ECONNREFUSED|127\.0\.0\.1/)
  })

  it('响应体不是 JSON：不抛解析错，按失败分类处理', async () => {
    stubFetch({ status: 503, text: '<html>Service Unavailable</html>' })

    await expect(request('/api/v1/inbox')).rejects.toMatchObject({
      status: 503,
      failure: 'unavailable',
    })
  })

  it('204：正常返回 undefined（登出一类"无响应体"的接口）', async () => {
    signInAs('employee')
    const calls = stubFetch({ status: 204 })

    await expect(request('/api/v1/auth/logout', { method: 'POST' })).resolves.toBeUndefined()

    expect(calls[0].url).toBe('/api/v1/auth/logout')
  })

  it('safeDetail 白名单：只接受短且干净的字符串', () => {
    expect(safeDetail('账号或密码不正确')).toBe('账号或密码不正确')
    expect(safeDetail('a'.repeat(DETAIL_MAX_LENGTH))).toBe('a'.repeat(DETAIL_MAX_LENGTH))

    // 超长 / 空 / 非字符串 / 脏内容一律丢弃
    expect(safeDetail('a'.repeat(DETAIL_MAX_LENGTH + 1))).toBeUndefined()
    expect(safeDetail('   ')).toBeUndefined()
    expect(safeDetail(undefined)).toBeUndefined()
    expect(safeDetail({ detail: 'x' })).toBeUndefined()
    expect(safeDetail('Traceback (most recent call last):')).toBeUndefined()
    expect(safeDetail('at create_session (/app/main.py:4582)')).toBeUndefined()
    expect(safeDetail('见 /api/v1/internal/accounts')).toBeUndefined()
    expect(safeDetail('SELECT phone FROM accounts WHERE 1=1')).toBeUndefined()
    expect(safeDetail('psycopg error: relation "accounts" does not exist')).toBeUndefined()
  })
})