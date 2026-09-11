import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsageBillingPage } from './UsageBillingPage'
import { formatCents } from './state'

function json(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string) => Response) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    return handler(url)
  })
}

describe('formatCents', () => {
  it('renders integer cents as exact yuan without float rounding', () => {
    expect(formatCents(0)).toBe('¥0.00')
    expect(formatCents(5)).toBe('¥0.05')
    expect(formatCents(100)).toBe('¥1.00')
    expect(formatCents(123456)).toBe('¥1234.56')
    // 大额也必须精确（浮点除法会在这里引入误差）
    expect(formatCents(999999999999)).toBe('¥9999999999.99')
  })

  it('supports negative amounts produced by ledger reversals', () => {
    expect(formatCents(-100)).toBe('-¥1.00')
    expect(formatCents(-5)).toBe('-¥0.05')
  })
})

describe('UsageBillingPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the tenant usage and cost totals', async () => {
    const fetchMock = makeFetch(() => json({ tenant_id: 'demo-tenant', units: 1234, cost_cents: 56789 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<UsageBillingPage />)

    expect(await screen.findByText('1234')).toBeInTheDocument()
    expect(screen.getByText('¥567.89')).toBeInTheDocument()
    expect(screen.getByText('demo-tenant')).toBeInTheDocument()
    // 只读与数据来源必须写在页面上
    expect(screen.getByText(/本页只读/)).toBeInTheDocument()
    expect(screen.getByText(/模型清单尚未实现/)).toBeInTheDocument()
    // 外壳的通知角标也会发请求，因此按路径筛选而不是取第 0 次调用
    const usageCalls = fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes('/commercial/usage'))
    expect(usageCalls).toHaveLength(1)
  })

  it('explains the empty state when nothing has been recorded', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ tenant_id: 'demo-tenant', units: 0, cost_cents: 0 })))

    render(<UsageBillingPage />)

    expect(await screen.findByText('本期还没有用量记录')).toBeInTheDocument()
  })

  it('shows a permission message for 403 without a retry', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ detail: '只有客户管理员或超级管理员可以管理租户商业化设置' }, 403)))

    render(<UsageBillingPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('当前账号没有查看用量与费用的权限。')
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })

  it('separates the unregistered-tenant 404 from real errors', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ detail: '租户不存在' }, 404)))

    render(<UsageBillingPage />)

    expect(await screen.findByText('本租户尚未登记用量账本')).toBeInTheDocument()
    expect(screen.getByText(/不是故障/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })

  it('retries after a server error', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      attempts += 1
      if (attempts === 1) return json({}, 500)
      return json({ tenant_id: 'demo-tenant', units: 7, cost_cents: 100 })
    }))

    render(<UsageBillingPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('用量与费用服务暂时不可用')
    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('7')).toBeInTheDocument()
    expect(screen.getByText('¥1.00')).toBeInTheDocument()
  })

  it('reloads when refresh is clicked', async () => {
    const fetchMock = makeFetch(() => json({ tenant_id: 'demo-tenant', units: 1, cost_cents: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<UsageBillingPage />)
    await screen.findByText('1')

    await userEvent.click(screen.getByRole('button', { name: '刷新' }))

    await waitFor(() => expect(fetchMock.mock.calls.filter((call) => String(call[0]).includes('/commercial/usage')).length).toBe(2))
  })
})
