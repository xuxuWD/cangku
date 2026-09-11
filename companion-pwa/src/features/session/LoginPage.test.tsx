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

    expect(await screen.findByRole('alert')).toHaveTextContent('手机号、密码或动态验证码不正确')
    expect(loadSession()).toBeNull()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })
})
