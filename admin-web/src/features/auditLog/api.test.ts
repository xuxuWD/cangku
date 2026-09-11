import { listAudits } from './api'
import { initialAuditFilters } from './state'
import type { AuditListResponse } from './types'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const page: AuditListResponse = { items: [], total: 0, limit: 50, offset: 0 }

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('auditLog api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('appends each selected action once', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok(page))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listAudits({ ...initialAuditFilters, actions: ['plan.approved', 'plan.rejected'] })).resolves.toEqual(page)

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/audits?')
    expect(url.split('action=').length - 1).toBe(2)
    expect(url).toContain('action=plan.approved')
    expect(url).toContain('action=plan.rejected')
  })

  it('omits empty filters but always sends limit and offset', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok(page))
    vi.stubGlobal('fetch', fetchMock)

    await listAudits(initialAuditFilters)

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).not.toContain('action=')
    expect(url).not.toContain('actor_id=')
    expect(url).not.toContain('target_type=')
    expect(url).not.toContain('target_id=')
    expect(url).not.toContain('since=')
    expect(url).not.toContain('until=')
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=0')
  })

  it('sends the timezone-aware ISO values produced by the page', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok(page))
    vi.stubGlobal('fetch', fetchMock)

    await listAudits({ ...initialAuditFilters, since: '2026-09-11T02:00:00.000Z', until: '2026-09-12T02:00:00.000Z', actorId: 'admin', targetType: 'task', targetId: 'task-1' })

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain(`since=${encodeURIComponent('2026-09-11T02:00:00.000Z')}`)
    expect(url).toContain(`until=${encodeURIComponent('2026-09-12T02:00:00.000Z')}`)
    expect(url).toContain('actor_id=admin')
    expect(url).toContain('target_type=task')
    expect(url).toContain('target_id=task-1')
  })

  it('maps 403 to a fixed Chinese permission message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 403, json: async () => ({ detail: '只有 CEO 或超级管理员可以查看审计日志' }) }) as Response))

    await expect(listAudits(initialAuditFilters)).rejects.toMatchObject({ status: 403, retryable: false, message: '当前账号没有查看审计日志的权限。' })
  })

  it('maps 401 to a re-login message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response))

    await expect(listAudits(initialAuditFilters)).rejects.toMatchObject({ status: 401, retryable: false, message: '登录态已失效，请重新登录。' })
  })

  it('maps other 4xx responses to a parameter message without leaking details', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 422, json: async () => ({ detail: '未知的审计动作：nope' }) }) as Response))

    await expect(listAudits(initialAuditFilters)).rejects.toMatchObject({ status: 422, retryable: false, message: '请求参数不被接受（422）。' })
  })

  it('maps a network failure to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('boom') }))

    await expect(listAudits(initialAuditFilters)).rejects.toMatchObject({ status: 0, retryable: true, message: '审计服务暂时不可用，请检查网络后重新尝试。' })
  })

  it('maps a 5xx response to a retryable message', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 503, json: async () => ({}) }) as Response))

    await expect(listAudits(initialAuditFilters)).rejects.toMatchObject({ status: 503, retryable: true, message: '审计服务暂时不可用，请检查网络后重新尝试。' })
  })
})
