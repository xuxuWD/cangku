import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmOpportunitiesPage } from './CrmOpportunitiesPage'
import type { CrmOpportunity, CrmStageEvent } from './types'

const qualification: CrmOpportunity = {
  opportunity_id: 'opp-1', account_id: 'acc-1', name: '云启一期', stage: 'qualification', amount_cents: 1250000,
  expected_close: '2026-10-31', owner_id: 'admin', stage_entered_at: '2026-09-10T00:00:00Z', closed_at: null,
  custom_fields: {}, created_at: '2026-09-03T00:00:00Z',
}
const won: CrmOpportunity = { ...qualification, opportunity_id: 'opp-2', name: '恒远续约', stage: 'won', closed_at: '2026-09-15T00:00:00Z' }

// 阶段事件（append-only）：首条 from_stage 为 null（＝创建）。
const createdEvent: CrmStageEvent = {
  event_id: 'ev-1', from_stage: null, to_stage: 'qualification', amount_cents: 1250000, actor_id: 'admin',
  occurred_at: '2026-09-03T00:00:00Z',
}
const advancedEvent: CrmStageEvent = {
  event_id: 'ev-2', from_stage: 'qualification', to_stage: 'proposal', amount_cents: 1250000, actor_id: 'admin',
  occurred_at: '2026-09-15T00:00:00Z',
}

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

// 客户名映射分支：页面挂载时会取一次 /crm/accounts（见 useAccountNames）。
function crmFetch(handler: (url: string, init?: RequestInit) => Response) {
  return makeFetch((url, init) => url.includes('/crm/accounts?')
    ? json({ items: [{ account_id: 'acc-1', name: '云启科技' }], total: 1, limit: 200, offset: 0 })
    : handler(url, init))
}

describe('CrmOpportunitiesPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists opportunities with stage, integer-cent amount and only the legal transitions', async () => {
    vi.stubGlobal('fetch', crmFetch(() => json({ items: [qualification, won], total: 2, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByText('云启一期')).toBeInTheDocument()
    expect(screen.getByText('资格确认', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('赢单', { selector: '.status-badge' })).toBeInTheDocument()
    // 整数分换算成元并加千分位：1250000 → ¥12,500.00
    expect(screen.getAllByText('¥12,500.00')).toHaveLength(2)
    // 客户列展示客户名（不是 account_id）；account_id 保留在 title 上便于核对。
    expect(await screen.findAllByText('云启科技')).toHaveLength(2)
    expect(screen.queryAllByText('acc-1')).toHaveLength(0)
    expect(screen.getAllByTitle('acc-1')).toHaveLength(2)

    // qualification 的合法迁移只有 proposal 与 lost。
    expect(screen.getByRole('button', { name: '将「云启一期」推进到 方案报价' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '将「云启一期」推进到 输单' })).toBeInTheDocument()
    // 终态不可回迁：赢单行没有推进按钮。
    expect(screen.queryByRole('button', { name: '将「恒远续约」推进到 资格确认' })).not.toBeInTheDocument()
    expect(screen.getByText('终态，不可回迁')).toBeInTheDocument()
  })

  it('advances the stage through the dedicated endpoint and updates the row', async () => {
    const fetchMock = crmFetch((url, init) => {
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
    const fetchMock = crmFetch((url) => url.includes('/stage')
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
    vi.stubGlobal('fetch', crmFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByText('暂无商机')).toBeInTheDocument()
  })

  it('shows a failure notice when the list cannot be loaded', async () => {
    vi.stubGlobal('fetch', crmFetch(() => json({}, 503)))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('商机列表加载失败')
    // 客户名映射请求同样失败时静默降级：不额外弹错，也不阻塞列表加载。
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('falls back to the account id when the customer name map cannot be loaded', async () => {
    vi.stubGlobal('fetch', makeFetch((url) => url.includes('/crm/accounts?')
      ? json({}, 503)
      : json({ items: [qualification], total: 1, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)

    expect(await screen.findByText('云启一期')).toBeInTheDocument()
    // 映射缺失只影响可读性：回落显示 account_id，且不因辅助请求失败报错。
    expect(screen.getByText('acc-1')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('opens the detail from a list row and renders the basic info plus the stage timeline', async () => {
    vi.stubGlobal('fetch', crmFetch((url) => {
      if (url.includes('/crm/opportunities/opp-1')) return json({ opportunity: qualification, stage_events: [createdEvent, advancedEvent] })
      return json({ items: [qualification, won], total: 2, limit: 50, offset: 0 })
    }))

    render(<CrmOpportunitiesPage />)
    // 行本身可点击（与「查看详情」按钮同一入口）。
    await userEvent.click(await screen.findByText('云启一期'))

    expect(await screen.findByRole('heading', { name: '基本信息' })).toBeInTheDocument()
    // 客户名解析、金额千分位、预计成交日与阶段中文标签。
    expect(screen.getByText('云启科技')).toBeInTheDocument()
    expect(screen.getByText('2026-10-31')).toBeInTheDocument()
    expect(screen.getByText('资格确认', { selector: '.status-badge' })).toBeInTheDocument()
    // 金额出现在「金额」与两条事件的「金额快照」中。
    expect(screen.getAllByText(/¥12,500\.00/)).toHaveLength(3)
    // 当前阶段停留天数（由 stage_entered_at 与当前时间差整日向下取整）。
    expect(screen.getByText('当前阶段停留')).toBeInTheDocument()
    expect(screen.getByText(/^\d+ 天$/)).toBeInTheDocument()
    // 时间线正序：首条 from 为 null ⇒ 显示「创建」。
    expect(screen.getByText('创建 → 资格确认')).toBeInTheDocument()
    expect(screen.getByText('资格确认 → 方案报价')).toBeInTheDocument()
    expect(screen.getAllByText(/操作者：admin/)).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: '返回列表' }))
    expect(await screen.findByText('恒远续约')).toBeInTheDocument()
  })

  it('advances the stage inside the detail and refreshes the timeline', async () => {
    let detailCalls = 0
    const fetchMock = crmFetch((url) => {
      if (url.includes('/crm/opportunities/opp-1/stage')) {
        return json({ ...qualification, stage: 'proposal', stage_entered_at: '2026-09-17T00:00:00Z' })
      }
      if (url.includes('/crm/opportunities/opp-1')) {
        detailCalls += 1
        return detailCalls === 1
          ? json({ opportunity: qualification, stage_events: [createdEvent] })
          : json({ opportunity: { ...qualification, stage: 'proposal' }, stage_events: [createdEvent, advancedEvent] })
      }
      return json({ items: [qualification], total: 1, limit: 50, offset: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByText('云启一期'))
    await userEvent.click(await screen.findByRole('button', { name: '将「云启一期」推进到 方案报价' }))

    expect(await screen.findByText('阶段已迁移为「方案报价」')).toBeInTheDocument()
    // 成功后刷新详情：阶段标签与时间线都要更新。
    expect(await screen.findByText('资格确认 → 方案报价')).toBeInTheDocument()
    expect(screen.getByText('方案报价', { selector: '.status-badge' })).toBeInTheDocument()
    await waitFor(() => expect(detailCalls).toBe(2))
  })

  it('reports a 409 conflict inside the detail, asks for a refresh and reloads it', async () => {
    let detailCalls = 0
    const fetchMock = crmFetch((url) => {
      if (url.includes('/crm/opportunities/opp-1/stage')) return json({ detail: '阶段已被变更' }, 409)
      if (url.includes('/crm/opportunities/opp-1')) {
        detailCalls += 1
        return json({ opportunity: qualification, stage_events: [createdEvent] })
      }
      return json({ items: [qualification], total: 1, limit: 50, offset: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByText('云启一期'))
    await userEvent.click(await screen.findByRole('button', { name: '将「云启一期」推进到 方案报价' }))

    expect(await screen.findByText('状态已被变更，请刷新')).toBeInTheDocument()
    // 冲突后必须重新拉取详情与时间线，避免停留在过期数据上。
    await waitFor(() => expect(detailCalls).toBe(2))
  })

  it('renders an empty timeline and tolerates missing fields without crashing', async () => {
    vi.stubGlobal('fetch', crmFetch((url) => {
      if (url.includes('/crm/opportunities/opp-1')) {
        return json({
          opportunity: { ...qualification, account_id: null, expected_close: null },
          stage_events: [],
        })
      }
      return json({ items: [qualification], total: 1, limit: 50, offset: 0 })
    }))

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByText('云启一期'))

    expect(await screen.findByText('暂无阶段事件')).toBeInTheDocument()
    // 缺失字段回落「—」，不崩、不伪造 0。
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('0 条（按发生时间正序）')).toBeInTheDocument()
  })

  it('shows the failure notice when the detail payload carries no opportunity', async () => {
    vi.stubGlobal('fetch', crmFetch((url) => url.includes('/crm/opportunities/opp-1')
      ? json({ stage_events: [createdEvent] })
      : json({ items: [qualification], total: 1, limit: 50, offset: 0 })))

    render(<CrmOpportunitiesPage />)
    await userEvent.click(await screen.findByText('云启一期'))

    expect(await screen.findByRole('alert')).toHaveTextContent('商机详情加载失败')
    expect(screen.getByText('没有找到该商机。')).toBeInTheDocument()
  })
})