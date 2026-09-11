import { saveSession, type Session } from '../../app/session'
import { approveItem, createSession, listPendingApprovals, rejectItem, SessionExpiredError } from './api'
import type { PendingApproval } from './types'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-9',
  userId: 'user-1',
  role: 'super_admin',
  expiresAt: Date.now() + 100_000,
}

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

function makeItem(kind: PendingApproval['kind']): PendingApproval {
  return { kind, target_id: 'x-1', title: '标题', requested_by: 'u-2', created_at: '2026-01-01T00:00:00Z', detail: {} }
}

describe('approvals api', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('parses pending approvals and injects the bearer token', async () => {
    const fetchMock = vi.fn<FetchMock>(async () =>
      jsonResponse({ items: [], counts: { task_approval: 0, plan_proposal: 0, account_registration: 0, total: 0 } })
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await listPendingApprovals(20)

    expect(result.counts.total).toBe(0)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/approvals/pending?limit=20')
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe('Bearer token-abc')
  })

  it('throws SessionExpiredError on 401', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as unknown as Response))

    await expect(listPendingApprovals()).rejects.toBeInstanceOf(SessionExpiredError)
  })

  it('posts task approvals to the task approve endpoint', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await approveItem(makeItem('task_approval'))

    expect(String(fetchMock.mock.calls[0][0])).toContain('/tasks/x-1/approve')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST')
  })

  it('posts plan proposal approval and rejection to the right endpoints', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await approveItem(makeItem('plan_proposal'))
    await rejectItem(makeItem('plan_proposal'), '方案不完整')

    expect(String(fetchMock.mock.calls[0][0])).toContain('/plan-proposals/x-1/approval')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/plan-proposals/x-1/rejection')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ reason: '方案不完整' })
  })

  it('posts account registration approval with the default role and session tenant', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await approveItem(makeItem('account_registration'))

    expect(String(fetchMock.mock.calls[0][0])).toContain('/auth/registrations/x-1/approval')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ role: 'employee', tenant_id: 'tenant-9' })
  })

  it('posts the role chosen by the approver for account registration approval', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await approveItem(makeItem('account_registration'), { role: 'department_lead' })

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      role: 'department_lead',
      tenant_id: 'tenant-9',
    })
  })

  it('posts account registration rejection with the reason', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await rejectItem(makeItem('account_registration'), '资料不全')

    expect(String(fetchMock.mock.calls[0][0])).toContain('/auth/registrations/x-1/rejection')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ reason: '资料不全' })
  })

  it('createSession posts credentials and returns the server session', async () => {
    const fetchMock = vi.fn<FetchMock>(async () =>
      jsonResponse({ access_token: 'a', token_type: 'Bearer', expires_in: 900, tenant_id: 't-1', user_id: 'u-1', role: 'ceo', scope: 'default' })
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await createSession('13800000000', 'pw')

    expect(result.access_token).toBe('a')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/auth/sessions')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ phone: '13800000000', password: 'pw' })
  })
})
