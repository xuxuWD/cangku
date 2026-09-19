import { getExportPackage, getLifecycleJob, getUsageSummary, listExportPackages, requestExport } from './api'

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

// ---------------------------------------------------------------------------
// B-1（2026-09-19）：导出闭环的四个调用点（路径 / 方法 / 参数 与契约一一对应）
// ---------------------------------------------------------------------------

describe('billing export api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('requests an export with POST and reads the job status by job id', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ job_id: 'lifecycle-1', tenant_id: 'demo-tenant', kind: 'export', status: 'queued', requested_by: 'admin', requested_at: '2026-09-19T08:00:00Z', execute_after: null, final_exported: false }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestExport()).resolves.toMatchObject({ job_id: 'lifecycle-1', status: 'queued' })
    await getLifecycleJob('lifecycle-1')

    const [createUrl, createInit] = fetchMock.mock.calls[0]
    expect(new URL(String(createUrl)).pathname).toBe('/api/v1/commercial/exports')
    expect(createInit?.method).toBe('POST')
    const [jobUrl, jobInit] = fetchMock.mock.calls[1]
    expect(new URL(String(jobUrl)).pathname).toBe('/api/v1/commercial/lifecycle/lifecycle-1')
    expect(jobInit?.method ?? 'GET').toBe('GET')
  })

  it('lists export packages with pagination and fetches one package by id', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ items: [], total: 0, limit: 20, offset: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listExportPackages(20, 40)
    await getExportPackage('export-1')

    const listUrl = new URL(String(fetchMock.mock.calls[0][0]))
    expect(listUrl.pathname).toBe('/api/v1/commercial/exports')
    expect(listUrl.searchParams.get('limit')).toBe('20')
    expect(listUrl.searchParams.get('offset')).toBe('40')
    expect(new URL(String(fetchMock.mock.calls[1][0])).pathname).toBe('/api/v1/commercial/exports/export-1')
  })

  it('maps 403 to the export-specific permission message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '当前账号无权管理该租户数据' }) }) as Response))

    await expect(listExportPackages()).rejects.toMatchObject({ status: 403, retryable: false, message: '当前账号没有查看数据导出的权限。' })
  })

  it('maps an expired package (404) to a non-retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 404, json: async () => ({ detail: '导出包已过期' }) }) as Response))

    await expect(getExportPackage('export-old')).rejects.toMatchObject({ status: 404, retryable: false })
  })

  it('treats a malformed list response as retryable instead of a silent empty list', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ tenant_id: 'demo-tenant', units: 1, cost_cents: 1 })))

    await expect(listExportPackages()).rejects.toMatchObject({ status: 0, retryable: true })
  })
})
