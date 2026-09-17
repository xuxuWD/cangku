import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmOpportunitiesPage } from './CrmOpportunitiesPage'
import type { CrmOpportunity } from './types'

const qualification: CrmOpportunity = {
  opportunity_id: 'opp-1', account_id: 'acc-1', name: '云启一期', stage: 'qualification', amount_cents: 1250000,
  expected_close: '2026-10-31', owner_id: 'admin', stage_entered_at: '2026-09-10T00:00:00Z', closed_at: null,
  custom_fields: {}, created_at: '2026-09-03T00:00:00Z',
}
const won: CrmOpportunity = { ...qualification, opportunity_id: 'opp-2', name: '恒远续约', stage: 'won', closed_at: '2026-09-15T00:00:00Z' }

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

describe('CrmOpportunitiesPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists opportunities with stage, integer-cent amount and only the legal transitions', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [qualification, won], total: 2, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByText('云启一期')).toBeInTheDocument()
    expect(screen.getByText('资格确认', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('赢单', { selector: '.status-badge' })).toBeInTheDocument()
    // 整数分换算成元：1250000 → ¥12500.00
    expect(screen.getAllByText('¥12500.00')).toHaveLength(2)

    // qualification 的合法迁移只有 proposal 与 lost。
    expect(screen.getByRole('button', { name: '将「云启一期」推进到 方案报价' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '将「云启一期」推进到 输单' })).toBeInTheDocument()
    // 终态不可回迁：赢单行没有推进按钮。
    expect(screen.queryByRole('button', { name: '将「恒远续约」推进到 资格确认' })).not.toBeInTheDocument()
    expect(screen.getByText('终态，不可回迁')).toBeInTheDocument()
  })

  it('advances the stage through the dedicated endpoint and updates the row', async () => {
    const fetchMock = makeFetch((url, init) => {
      if (url.includes('/stage')) {
        expect(init?.method).toBe('POST')
        return json({ ...qualification, stage: 'proposal', stage_entered_at: '2026-09-17T00:00:00Z' })
      }
      return json({ items: [qualification], total: 1, limit: 50, offset: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '将「云启一期」推进到 方案报价' }))

    expect(await screen.findByText('阶段已迁移为「方案报价」')).toBeInTheDocument()
    expect(screen.getByText('方案报价', { selector: '.status-badge' })).toBeInTheDocument()
    expect(JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).includes('/stage'))?.[1]?.body))).toEqual({ to_stage: 'proposal' })
  })

  it('reports a 409 conflict, asks for a refresh and reloads the list', async () => {
    const fetchMock = makeFetch((url) => url.includes('/stage')
      ? json({ detail: '阶段已被变更' }, 409)
      : json({ items: [qualification], total: 1, limit: 50, offset: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '将「云启一期」推进到 方案报价' }))

    expect(await screen.findByText('状态已被变更，请刷新')).toBeInTheDocument()
    // 冲突后必须重新拉取，避免停留在过期数据上。
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/crm/opportunities?')).length).toBe(2))
  })

  it('shows the empty state when no opportunity matches', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByText('暂无商机')).toBeInTheDocument()
  })

  it('shows a failure notice when the list cannot be loaded', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({}, 503)))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('商机列表加载失败')
  })
})