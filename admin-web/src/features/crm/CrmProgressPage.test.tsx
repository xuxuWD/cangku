import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmProgressPage } from './CrmProgressPage'
import type { CrmProgressSummary } from './types'

const baseMetrics: CrmProgressSummary = {
  pipeline_coverage: null, pipeline_coverage_note: 'no_target',
  win_rate: null, sales_cycle_days: null,
  stage_conversion: { 'qualification->proposal': null },
  pipeline_age_days: 12.5,
  creation_rate_30d: 0,
  health_distribution: { green: 1, yellow: 0, red: 2, uncomputed: 3 },
  renewal_window_count: 2, renewal_window_amount_cents: 500000,
  payment_progress: null, overdue_contract_count: 0,
  target_attainment_amount: null, target_attainment_count: null, target_note: 'no_target',
}
const withTargetMetrics: CrmProgressSummary = {
  ...baseMetrics,
  pipeline_coverage: 3.5, pipeline_coverage_note: '',
  win_rate: 0.5, sales_cycle_days: 30.25,
  payment_progress: 0.25,
  target_attainment_amount: 0.8, target_attainment_count: 1, target_note: '',
}

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string) => Response) {
  return vi.fn(async (input: RequestInfo | URL) => handler(String(input)))
}

describe('CrmProgressPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('never shows 0 for empty denominators: 无目标 / — instead', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json(baseMetrics)))

    render(<CrmProgressPage />)

    expect(await screen.findByText('管线覆盖率')).toBeInTheDocument()
    // 缺口径的指标：无目标（覆盖率 + 金额/单数达成度）与「—」（赢率 / 销售周期 / 回款进度）。
    await waitFor(() => expect(screen.getAllByText('无目标').length).toBeGreaterThanOrEqual(3))
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
    // 真实为零的计数仍然显示 0（创建速率 30 天为 0、yellow 分档为 0）。
    expect(screen.getAllByText('0')).toHaveLength(2)
    expect(screen.getByText('0 份')).toBeInTheDocument()
    expect(screen.getByText('2 份')).toBeInTheDocument()
    expect(screen.getByText(/窗口内合同金额 ¥5,000.00/)).toBeInTheDocument()
    expect(screen.getByText('12.5 天')).toBeInTheDocument()
  })

  it('renders ratios with targets present', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json(withTargetMetrics)))

    render(<CrmProgressPage />)

    expect(await screen.findByText('3.50×')).toBeInTheDocument()
    expect(screen.getByText('50.00%')).toBeInTheDocument()
    expect(screen.getByText('30.25 天')).toBeInTheDocument()
    expect(screen.getByText('25.00%')).toBeInTheDocument()
    expect(screen.getByText('80.00%')).toBeInTheDocument()
    expect(screen.getByText('100.00%')).toBeInTheDocument()
    expect(screen.queryByText('无目标')).not.toBeInTheDocument()
  })

  it('requests scope=all and surfaces the server 403 as-is', async () => {
    const fetchMock = makeFetch((url) => url.includes('scope=all')
      ? json({ detail: '当前岗位无权查看全量进度指标' }, 403)
      : json(baseMetrics))
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmProgressPage />)
    await screen.findByText('管线覆盖率')
    await userEvent.click(screen.getByRole('tab', { name: '全量' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('当前账号无权查看全量指标')
    expect(screen.getByText('当前账号没有执行该操作的权限。')).toBeInTheDocument()
    expect(screen.getByText(/仅对部门负责人 \/ CEO \/ 超级管理员开放/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('scope=all'))).toBe(true)
  })

  it('shows a retryable failure notice for the default scope', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      attempts += 1
      return attempts === 1 ? json({}, 500) : json(baseMetrics)
    }))

    render(<CrmProgressPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('进度指标加载失败')
    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('管线覆盖率')).toBeInTheDocument()
  })
})