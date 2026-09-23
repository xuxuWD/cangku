/**
 * 「用量与费用」页面用例。
 *
 * 覆盖口径（本页最关键的三条纪律）：
 *  - **状态保真**：加载中 / 失败时不显示 0；`404`（未登记）按"未配置"呈现，**不是**"加载失败"、也不给重试；
 *  - **金额负值**：冲正后累计为负，界面必须显示 `-¥15.00` 而不是原样数字；
 *  - **导出闭环**：申请 → 轮询作业 → 列表 → 下载；过期包**不给下载按钮**（如实显示"已过期"）。
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { UsageBillingPage } from '../UsageBillingPage'
import { setMockUsageNegative, setServiceMode } from '../services/billingService'

/**
 * 路由桩：键可写成 `'GET /path'` / `'POST /path'`（区分方法），也可只写 `'/path'`（任意方法）。
 * 本页 `/commercial/exports` 同时有 GET（列包）与 POST（申请），必须按方法分流。
 */
function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const method = init?.method ?? 'GET'
    const path = Object.keys(routes).find((key) => {
      const parts = key.split(' ')
      if (parts.length === 2) return parts[0] === method && String(url).startsWith(parts[1])
      return String(url).startsWith(key)
    })
    if (!path) throw new Error(`未预期的请求：${method} ${url}`)
    const { status = 200, body } = routes[path]
    return { status, ok: status >= 200 && status < 300, text: async () => (body === undefined ? '' : JSON.stringify(body)) }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return { calls }
}

const USAGE = { tenant_id: 'demo-tenant', units: 1280, cost_cents: 4321 }

const PKG = (over: Record<string, unknown> = {}) => ({
  package_id: 'pkg-1',
  tenant_id: 'demo-tenant',
  job_id: 'job-1',
  created_at: '2026-09-23T01:00:00Z',
  expires_at: '2026-09-30T01:00:00Z',
  ...over,
})

describe('用量与费用页', () => {
  afterEach(() => {
    setServiceMode('mock')
    setMockUsageNegative(false)
    vi.unstubAllGlobals()
  })

  it('渲染累计用量与累计费用（金额走整数分格式化）', async () => {
    setServiceMode('http')
    stubFetch({
      '/api/v1/commercial/usage': { body: USAGE },
      '/api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } },
    })

    renderWithProviders(<UsageBillingPage />)

    expect(await screen.findByText('累计用量')).toBeInTheDocument()
    expect(screen.getByText('1280')).toBeInTheDocument()
    expect(screen.getByText('¥43.21')).toBeInTheDocument()
  })

  it('冲正后累计为负 ⇒ 显示 -¥15.00（不是原样数字、不是 0）', async () => {
    setServiceMode('mock')
    setMockUsageNegative(true)

    renderWithProviders(<UsageBillingPage />)

    expect(await screen.findByText('-¥15.00')).toBeInTheDocument()
  })

  it('404（未登记）⇒ 如实说明且**不给重试**，文案与"加载失败"不同', async () => {
    setServiceMode('http')
    stubFetch({
      '/api/v1/commercial/usage': { status: 404, body: { detail: '租户不存在' } },
      '/api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } },
    })

    renderWithProviders(<UsageBillingPage />)

    expect(await screen.findByText('本租户尚未登记用量账本')).toBeInTheDocument()
    expect(screen.getByText(/不是故障/)).toBeInTheDocument()
    expect(screen.queryByText('用量与费用加载失败，请稍后重试。')).not.toBeInTheDocument()
  })

  it('加载失败：金额区**不显示 0**（状态保真）', async () => {
    setServiceMode('http')
    stubFetch({
      '/api/v1/commercial/usage': { status: 500 },
      '/api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } },
    })

    renderWithProviders(<UsageBillingPage />)

    await screen.findByText('用量与费用服务暂时不可用，请检查网络后重新尝试。')
    // 绝不能把失败渲染成 0 或 ¥0.00
    expect(screen.queryByText('¥0.00')).not.toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  describe('数据导出', () => {
    it('列出导出包：未过期给下载按钮，过期**不给按钮**且标注已过期', async () => {
      setServiceMode('http')
      stubFetch({
        '/api/v1/commercial/usage': { body: USAGE },
        '/api/v1/commercial/exports': {
          body: {
            items: [PKG(), PKG({ package_id: 'pkg-old', expires_at: '2026-01-01T00:00:00Z' })],
            total: 2,
            limit: 20,
            offset: 0,
          },
        },
      })

      renderWithProviders(<UsageBillingPage />)

      expect(await screen.findByText('共 2 个导出包')).toBeInTheDocument()
      expect(screen.getByText('已过期')).toBeInTheDocument()
      // 只有未过期那一个才有「下载」按钮（AntD 会给双汉字按钮名插空白 ⇒ 宽松匹配）
      expect(screen.getAllByRole('button', { name: /下\s*载/ })).toHaveLength(1)
    })

    it('没有导出包 ⇒ 空态说明（不是"加载失败"）', async () => {
      setServiceMode('http')
      stubFetch({
        '/api/v1/commercial/usage': { body: USAGE },
        '/api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } },
      })

      renderWithProviders(<UsageBillingPage />)

      expect(await screen.findByText(/暂无导出包/)).toBeInTheDocument()
    })

    it('申请导出 → 轮询作业 → 生成完成给出提示并重新列出导出包', async () => {
      setServiceMode('http')
      const user = userEvent.setup()
      stubFetch({
        'GET /api/v1/commercial/usage': { body: USAGE },
        'POST /api/v1/commercial/exports': { status: 202, body: { job_id: 'job-9', status: 'queued' } },
        'GET /api/v1/commercial/lifecycle/': { body: { job_id: 'job-9', status: 'completed' } },
        'GET /api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } },
      })
      renderWithProviders(<UsageBillingPage />)
      await screen.findByText('累计用量')

      await user.click(screen.getByRole('button', { name: '申请导出' }))

      await waitFor(() => {
        expect(screen.getByText('导出包已生成，可在下方下载')).toBeInTheDocument()
      })
    })
  })
})
