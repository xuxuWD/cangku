import { changeOpportunityStage, getOpportunity, getProgressSummary, listAccounts, listContracts, listQuotes, registerPayment, registerSignature, revealContact } from './api'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('crm api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends pagination and only non-empty filters', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ items: [], total: 0, limit: 50, offset: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listAccounts({ status: '', limit: 50, offset: 0 })
    let url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/crm/accounts?')
    expect(url).not.toContain('status=')
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=0')

    await listAccounts({ status: 'active', limit: 20, offset: 40 })
    url = String(fetchMock.mock.calls[1][0])
    expect(url).toContain('status=active')
    expect(url).toContain('limit=20')
    expect(url).toContain('offset=40')

    await listQuotes({ status: 'confirmed', limit: 50, offset: 0 })
    expect(String(fetchMock.mock.calls[2][0])).toContain('/crm/quotes?status=confirmed')

    await listContracts({ status: '', limit: 50, offset: 0 })
    expect(String(fetchMock.mock.calls[3][0])).toContain('/crm/contracts?limit=50')
  })

  it('posts the stage transition body and surfaces 409 as a conflict error', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ({ ok: false, status: 409, json: async () => ({}) }) as Response)
    vi.stubGlobal('fetch', fetchMock)

    await expect(changeOpportunityStage('opp-1', 'proposal')).rejects.toMatchObject({ status: 409, retryable: false })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/crm/opportunities/opp-1/stage')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ to_stage: 'proposal' })
  })

  it('fetches the opportunity detail with its stage timeline', async () => {
    const detail = { opportunity: { opportunity_id: 'opp-1' }, stage_events: [] }
    const fetchMock = vi.fn<FetchMock>(async () => ok(detail))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getOpportunity('opp-1')).resolves.toEqual(detail)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/crm/opportunities/opp-1')
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined()
  })

  it('reveals a single sensitive field through the dedicated POST endpoint', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ contact_id: 'ct-1', field: 'phone', value: '13800001234' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(revealContact('ct-1', 'phone')).resolves.toEqual({ contact_id: 'ct-1', field: 'phone', value: '13800001234' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/crm/contacts/ct-1/reveal')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ field: 'phone' })
  })

  it('sends signature registration and integer-cent payments', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ contract_id: 'c-1' }))
    vi.stubGlobal('fetch', fetchMock)

    await registerSignature('c-1', { signed_at: '2026-09-17T02:00:00.000Z', document_object_key: 'obj/key.pdf' })
    await registerPayment('c-1', 1200000)

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ signed_at: '2026-09-17T02:00:00.000Z', document_object_key: 'obj/key.pdf' })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ amount_cents: 1200000 })
  })

  it('always sends the scope for the progress summary', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await getProgressSummary('me')
    await getProgressSummary('all')

    expect(String(fetchMock.mock.calls[0][0])).toContain('scope=me')
    expect(String(fetchMock.mock.calls[1][0])).toContain('scope=all')
  })

  it('maps status codes to fixed messages without leaking the server detail', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '当前岗位无权查看全量进度指标' }) }) as Response))
    await expect(getProgressSummary('all')).rejects.toMatchObject({ status: 403, message: '当前账号没有执行该操作的权限。', retryable: false })

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 404, json: async () => ({}) }) as Response))
    await expect(listAccounts({ status: '', limit: 50, offset: 0 })).rejects.toMatchObject({ status: 404, retryable: false })

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 422, json: async () => ({ detail: '未知字段' }) }) as Response))
    await expect(listAccounts({ status: '', limit: 50, offset: 0 })).rejects.toMatchObject({ status: 422 })

    // 模型网关失败（502）可重试；不降级、不伪造建议。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 502, json: async () => ({}) }) as Response))
    await expect(listAccounts({ status: '', limit: 50, offset: 0 })).rejects.toMatchObject({ status: 502, retryable: true })

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('boom') }))
    await expect(listAccounts({ status: '', limit: 50, offset: 0 })).rejects.toMatchObject({ status: 0, retryable: true, message: 'CRM 服务暂时不可用，请检查网络后重新尝试。' })
  })
})