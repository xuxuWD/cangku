import { getUsageSummary } from './api'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('billing api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('requests the commercial usage endpoint with identity headers', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ tenant_id: 'demo-tenant', units: 3, cost_cents: 25 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getUsageSummary()).resolves.toEqual({ tenant_id: 'demo-tenant', units: 3, cost_cents: 25 })

    const [url, init] = fetchMock.mock.calls[0]
    expect(new URL(String(url)).pathname).toBe('/api/v1/commercial/usage')
    expect(init?.method ?? 'GET').toBe('GET')
    expect(init?.headers).toHaveProperty('X-User-Role')
  })

  it('maps 403 to a fixed permission message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '只有客户管理员或超级管理员可以管理租户商业化设置' }) }) as Response))

    await expect(getUsageSummary()).rejects.toMatchObject({ status: 403, retryable: false, message: '当前账号没有查看用量与费用的权限。' })
  })

  it('maps 404 to a fixed unregistered-tenant message instead of leaking the raw detail', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 404, json: async () => ({ detail: '租户不存在' }) }) as Response))

    await expect(getUsageSummary()).rejects.toMatchObject({ status: 404, retryable: false, message: '本租户尚未在商业化模块登记，暂时没有可展示的用量与费用。' })
  })

  it('maps 401 to a re-login message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response))

    await expect(getUsageSummary()).rejects.toMatchObject({ status: 401, message: '登录态已失效，请重新登录。' })
  })

  it('maps network failures and 5xx to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('offline') }))
    await expect(getUsageSummary()).rejects.toMatchObject({ status: 0, retryable: true })

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 503, json: async () => ({}) }) as Response))
    await expect(getUsageSummary()).rejects.toMatchObject({ status: 503, retryable: true, message: '用量与费用服务暂时不可用，请检查网络后重新尝试。' })
  })
})
