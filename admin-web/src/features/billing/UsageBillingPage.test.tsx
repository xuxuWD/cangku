import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsageBillingPage } from './UsageBillingPage'
import { formatCents } from './state'
import { formatLocalTime } from '../../utils/time'

function json(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response
}

/** 导出面的默认兜底：空列表（既有用例不必关心导出请求）。 */
function emptyExportList(): Response {
  return json({ items: [], total: 0, limit: 20, offset: 0 })
}

type ExportRoutes = (method: string, url: string) => Response

function makeFetch(handler: (url: string) => Response, options: { exports?: ExportRoutes } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (url.includes('/commercial/exports') || url.includes('/commercial/lifecycle/')) {
      return options.exports ? options.exports(method, url) : emptyExportList()
    }
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
    expect(screen.getByText(/尚未交付的部分如实说明/)).toBeInTheDocument()
    // 外壳的通知角标也会发请求，因此按路径筛选而不是取第 0 次调用
    const usageCalls = fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes('/commercial/usage'))
    expect(usageCalls).toHaveLength(1)
  })

  it('explains the empty state when nothing has been recorded', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ tenant_id: 'demo-tenant', units: 0, cost_cents: 0 })))

    render(<UsageBillingPage />)

    // 空态改用统一 EmptyState，标题随之统一为「暂无用量记录」。
    expect(await screen.findByText('暂无用量记录')).toBeInTheDocument()
    expect(screen.getByText(/有计量事件写入账本后/)).toBeInTheDocument()
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

// ---------------------------------------------------------------------------
// B-1（2026-09-19）：数据导出闭环（申请 → 等生成 → 列表 → 下载）。
// 后端取回端点要 `package_id`，列表端点负责「发现」；本组用例钉住客户端的整条链。
// ---------------------------------------------------------------------------

const PACKAGE = {
  package_id: 'export-walk-1',
  tenant_id: 'demo-tenant',
  job_id: 'lifecycle-walk-1',
  created_at: '2026-09-19T08:00:00Z',
  expires_at: '2026-09-26T08:00:00Z',
}

const COMPLETED_JOB = {
  job_id: 'lifecycle-walk-1',
  tenant_id: 'demo-tenant',
  kind: 'export',
  status: 'completed',
  requested_by: 'admin',
  requested_at: '2026-09-19T07:59:00Z',
  execute_after: null,
  final_exported: false,
}

const USAGE = { tenant_id: 'demo-tenant', units: 3, cost_cents: 300 }

describe('UsageBillingPage 数据导出（B-1）', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('空态：没有导出包时如实说明，并给出「申请导出」入口', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE)))

    render(<UsageBillingPage />)

    expect(await screen.findByText('暂无导出包')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '申请导出' })).toBeInTheDocument()
    // 过期口径要写在页面上（7 天），不能让用户自己猜。
    expect(screen.getByText(/自生成起 7 天内有效/)).toBeInTheDocument()
  })

  it('申请导出：按作业状态确认生成后再以服务端列表回流（不做本地乐观插入）', async () => {
    let listCalls = 0
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE), {
      exports: (method, url) => {
        if (method === 'POST') return json({ ...COMPLETED_JOB, status: 'queued' }, 202)
        if (url.includes('/commercial/lifecycle/')) return json(COMPLETED_JOB)
        listCalls += 1
        return listCalls === 1 ? emptyExportList() : json({ items: [PACKAGE], total: 1, limit: 20, offset: 0 })
      },
    }))

    render(<UsageBillingPage />)
    await screen.findByText('暂无导出包')

    await userEvent.click(screen.getByRole('button', { name: '申请导出' }))

    expect(await screen.findByText('导出包已生成，可在下方下载')).toBeInTheDocument()
    expect(screen.getByText(`有效期至 ${formatLocalTime(PACKAGE.expires_at)}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下载' })).toBeInTheDocument()
    // 列表来自服务端二次取数（不是把申请响应直接当成列表内容）。
    expect(listCalls).toBeGreaterThanOrEqual(2)
  })

  it('下载：取回脱敏载荷并以文件形式落盘（页面不展示载荷内容）', async () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, writable: true, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, writable: true, configurable: true })
    const detail = { ...PACKAGE, payload: { tenant_id: 'demo-tenant', resources: { users: [] } } }
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE), {
      exports: (method, url) => (url.includes('/commercial/exports/export-walk-1') ? json(detail) : json({ items: [PACKAGE], total: 1, limit: 20, offset: 0 })),
    }))

    render(<UsageBillingPage />)
    await userEvent.click(await screen.findByRole('button', { name: '下载' }))

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled())
    expect(revokeObjectURL).toHaveBeenCalled()
    expect(await screen.findByText(/已开始下载/)).toBeInTheDocument()
    // 页面不展示载荷内容（载荷只进文件）。
    expect(screen.queryByText(/resources/)).not.toBeInTheDocument()
  })

  it('过期包：标注「已过期」且不提供下载', async () => {
    const expired = { ...PACKAGE, package_id: 'export-old-1', expires_at: '2020-01-01T00:00:00Z' }
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE), {
      exports: () => json({ items: [expired], total: 1, limit: 20, offset: 0 }),
    }))

    render(<UsageBillingPage />)

    expect(await screen.findByText('已过期')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '下载' })).not.toBeInTheDocument()
  })

  it('无权限：明确说明是权限问题（不伪装成空态、不给无效重试）', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE), {
      exports: () => json({ detail: '只有客户管理员或超级管理员可以管理租户商业化设置' }, 403),
    }))

    render(<UsageBillingPage />)

    expect(await screen.findByText('当前账号没有查看数据导出的权限。')).toBeInTheDocument()
    expect(screen.queryByText('暂无导出包')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })

  it('列表失败：给出错误与重试，重试后恢复（服务端权威）', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => json(USAGE), {
      exports: () => {
        attempts += 1
        if (attempts === 1) return json({}, 500)
        return json({ items: [PACKAGE], total: 1, limit: 20, offset: 0 })
      },
    }))

    render(<UsageBillingPage />)
    await screen.findByText('导出包列表加载失败')

    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByRole('button', { name: '下载' })).toBeInTheDocument()
  })
})
