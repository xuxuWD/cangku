/**
 * 登录页用例（第 6 轮 · 接线批 1）。
 *
 * 覆盖：成功登录（写 sessionStorage 的令牌与角色 + 进壳）、401（密码错 / 需要动态验证码）、
 * 429（限流）、503（后端未配会话密钥）、网络失败（服务不可达），以及**表单不预填任何凭据**。
 * 文案一律来自统一请求层：只可能是后端"短且干净"的 `detail` 或本地固定文案，不含堆栈 / 路径。
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from '../LoginPage'
import { AppShell } from '../../../app/AppShell'
import { ROLE_STORAGE_KEY, TOKEN_STORAGE_KEY, useSession } from '../../../app/session'
import { renderWithProviders, signOutForTest } from '../../../test/renderWithProviders'

/** 路由式 `fetch` 桩：未命中任何路径即抛错（顺带证明"没有多余请求"）。 */
function stubRoutes(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return calls
}

const SESSION = {
  access_token: 'token-abc',
  token_type: 'Bearer',
  expires_in: 3600,
  tenant_id: 'tenant-0001',
  user_id: 'user-0001',
  role: 'employee',
  scope: 'full',
}

/** 填写账号与密码并提交。 */
async function submit(phone = '13800000000', password = 'pw-123456'): Promise<void> {
  await userEvent.type(screen.getByLabelText('账号（手机号）'), phone)
  await userEvent.type(screen.getByLabelText('密码'), password)
  await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }))
}

describe('LoginPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    signOutForTest()
  })

  it('成功登录：写入会话（令牌 + 角色），并进入应用壳；请求体只带表单里的值', async () => {
    const calls = stubRoutes({ '/api/v1/auth/sessions': { body: SESSION } })
    renderWithProviders(<AppShell />)

    await submit()

    expect(await screen.findByRole('heading', { level: 1, name: '我的工作台' })).toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('token-abc')
    expect(sessionStorage.getItem(ROLE_STORAGE_KEY)).toBe('employee')
    expect(useSession.getState()).toMatchObject({ status: 'authenticated', token: 'token-abc', role: 'employee' })
    // 顶栏显示角色名（响应里没有展示名，不编造姓名）
    expect(screen.getByText('员工')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
    // 登录**只发了一次**请求，且没有硬编码 / 预填的凭据。
    // ⚠️ 2026-09-23：壳改成三栏 + **对话宿主常驻**（B3 §4）后，登录成功进壳会**另外**
    // 触发一次「拉会话列表」，所以不能再对**全部** fetch 计数 —— 只数**登录那一发**。
    const loginCalls = calls.filter((call) => call.url.includes('/auth/sessions'))
    expect(loginCalls).toHaveLength(1)
    expect(JSON.parse(String(loginCalls[0].init.body))).toEqual({ phone: '13800000000', password: 'pw-123456' })
  })

  it('表单不预填任何凭据（账号 / 密码 / 动态验证码都是空的）', () => {
    renderWithProviders(<LoginPage />)

    expect(screen.getByLabelText('账号（手机号）')).toHaveValue('')
    expect(screen.getByLabelText('密码')).toHaveValue('')
    expect(screen.getByLabelText('动态验证码（如已启用）')).toHaveValue('')
    expect(screen.queryByDisplayValue(/13800000000|admin|password/i)).not.toBeInTheDocument()
  })

  it('401 密码错：显示服务端短文案，且不写入任何会话', async () => {
    stubRoutes({ '/api/v1/auth/sessions': { status: 401, body: { detail: '手机号或密码不正确' } } })
    renderWithProviders(<LoginPage />)

    await submit()

    expect(await screen.findByText('手机号或密码不正确')).toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    expect(useSession.getState().status).toBe('anonymous')
  })

  it('401 需要动态验证码：如实提示，并保留验证码输入项供补齐后重试', async () => {
    stubRoutes({ '/api/v1/auth/sessions': { status: 401, body: { detail: '需要动态验证码' } } })
    renderWithProviders(<LoginPage />)

    await submit()

    expect(await screen.findByText('需要动态验证码')).toBeInTheDocument()
    expect(screen.getByLabelText('动态验证码（如已启用）')).toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('429 限流：显示限流文案（不重试、不假装成功）', async () => {
    stubRoutes({ '/api/v1/auth/sessions': { status: 429, body: { detail: '登录尝试过于频繁，请稍后再试' } } })
    renderWithProviders(<LoginPage />)

    await submit()

    expect(await screen.findByText('登录尝试过于频繁，请稍后再试')).toBeInTheDocument()
    expect(useSession.getState().status).toBe('anonymous')
  })

  it('503：后端未配会话密钥时，回落到本地固定文案（不暴露服务端原文 / 配置项名）', async () => {
    stubRoutes({ '/api/v1/auth/sessions': { status: 503 } })
    renderWithProviders(<LoginPage />)

    await submit()

    expect(await screen.findByText('服务暂时不可用，请稍后重试或联系管理员。')).toBeInTheDocument()
  })

  it('网络失败：提示服务不可达，且不暴露底层错误原文', async () => {
    vi.stubGlobal(
      'fetch',
      (async () => {
        throw new TypeError('Failed to fetch: ECONNREFUSED 127.0.0.1:8000')
      }) as unknown as typeof fetch,
    )
    renderWithProviders(<LoginPage />)

    await submit()

    const alert = await screen.findByText('服务不可达：请检查网络后重试。')
    expect(alert).toBeInTheDocument()
    expect(screen.queryByText(/ECONNREFUSED|127\.0\.0\.1/)).not.toBeInTheDocument()
  })
})