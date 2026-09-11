import { fetchWorkforceRoster } from './api'
import type { WorkforceRosterResponse } from './types'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const page: WorkforceRosterResponse = { items: [{ key: 'content-operator', role_knowledge_base_ids: ['company-general'], agent_knowledge_base_ids: [], task_count: 3 }], total: 1 }

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('workforce api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('requests the read-only roster endpoint with identity headers', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok(page))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchWorkforceRoster()).resolves.toEqual(page)

    const url = String(fetchMock.mock.calls[0][0])
    // 精确断言路径：写成子串匹配会漏掉多一个字符这类错误。
    expect(new URL(url).pathname).toBe('/api/v1/workforce/roster')
    const init = fetchMock.mock.calls[0][1]
    expect(init?.headers).toMatchObject({ Accept: 'application/json' })
    expect(init?.headers).toHaveProperty('X-Tenant-Id')
    expect(init?.headers).toHaveProperty('X-User-Id')
    expect(init?.headers).toHaveProperty('X-User-Role')
  })

  it('maps 403 to a fixed Chinese permission message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '只有超级管理员可以查看岗位与数字员工清单' }) }) as Response))

    await expect(fetchWorkforceRoster()).rejects.toMatchObject({ status: 403, retryable: false, message: '当前账号没有查看岗位与数字员工的权限。' })
  })

  it('maps 401 to a re-login message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response))

    await expect(fetchWorkforceRoster()).rejects.toMatchObject({ status: 401, retryable: false, message: '登录态已失效，请重新登录。' })
  })

  it('maps other 4xx responses to a parameter message without leaking details', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 422, json: async () => ({ detail: '内部堆栈细节' }) }) as Response))

    await expect(fetchWorkforceRoster()).rejects.toMatchObject({ status: 422, retryable: false, message: '请求参数不被接受（422）。' })
  })

  it('maps a network failure to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('boom') }))

    await expect(fetchWorkforceRoster()).rejects.toMatchObject({ status: 0, retryable: true, message: '岗位与数字员工服务暂时不可用，请检查网络后重新尝试。' })
  })

  it('maps a 5xx response to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 503, json: async () => ({}) }) as Response))

    await expect(fetchWorkforceRoster()).rejects.toMatchObject({ status: 503, retryable: true, message: '岗位与数字员工服务暂时不可用，请检查网络后重新尝试。' })
  })
})
