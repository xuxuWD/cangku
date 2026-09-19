import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { loadSession } from '../../app/session'
import { LoginPage } from './LoginPage'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

const sessionBody = {
  access_token: 'token-xyz',
  token_type: 'Bearer',
  expires_in: 900,
  tenant_id: 'tenant-1',
  user_id: 'user-1',
  role: 'ceo',
  scope: 'default',
}

describe('LoginPage', () => {
  beforeEach(() => localStorage.clear())

  afterEach(() => vi.unstubAllGlobals())

  it('saves the session and notifies the app on success', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok(sessionBody)))
    const onAuthenticated = vi.fn()
    const user = userEvent.setup()

    render(<LoginPage onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('手机号'), '13800000000')
    await user.type(screen.getByLabelText('密码'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledTimes(1))
    expect(loadSession()).toMatchObject({ accessToken: 'token-xyz', tenantId: 'tenant-1', userId: 'user-1', role: 'ceo' })
  })

  it('shows a friendly message on 401 and stores no session', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({ detail: '登录失败' }) }) as unknown as Response))
    const onAuthenticated = vi.fn()
    const user = userEvent.setup()

    render(<LoginPage onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('手机号'), '13800000000')
    await user.type(screen.getByLabelText('密码'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('手机号或密码不正确')
    expect(loadSession()).toBeNull()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('tells the user when the account needs a TOTP code (was: lumped into wrong-password)', async () => {
    // 服务端对「已绑定 TOTP 却未填码」返回 401 detail=需要动态验证码（`app/main.py:4774`）。
    // 不能显示成「手机号、密码或……不正确」，否则用户会以为密码错了而反复重试。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({ detail: '需要动态验证码' }) }) as unknown as Response))
    const onAuthenticated = vi.fn()
    const user = userEvent.setup()

    render(<LoginPage onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('手机号'), '13800000000')
    await user.type(screen.getByLabelText('密码'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('已绑定动态验证码')
    expect(loadSession()).toBeNull()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('tells the user when the TOTP code is wrong (not "password wrong")', async () => {
    // 动态码错误：如实区分，不见得是密码错。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({ detail: '动态验证码不正确' }) }) as unknown as Response))
    const user = userEvent.setup()

    render(<LoginPage onAuthenticated={vi.fn()} />)
    await user.type(screen.getByLabelText('手机号'), '13800000000')
    await user.type(screen.getByLabelText('密码'), 'correct-horse-battery')
    await user.type(screen.getByLabelText(/动态验证码/), '123456')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('动态验证码不正确')
    expect(loadSession()).toBeNull()
  })

  it('rejects a restricted (totp_enrollment) session instead of storing it', async () => {
    // 受限会话：服务端要求先绑定 TOTP（只放行绑定接口），伴侣端没有绑定入口
    // ⇒ 存下来只会让后续每个请求都 403 且用户不知为何，故**不保存**并说明去哪儿绑定。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ ...sessionBody, scope: 'totp_enrollment' }) as unknown as Response))
    const onAuthenticated = vi.fn()
    const user = userEvent.setup()

    render(<LoginPage onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('手机号'), '13800000000')
    await user.type(screen.getByLabelText('密码'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('需要先绑定动态验证码')
    expect(loadSession()).toBeNull()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })
})
