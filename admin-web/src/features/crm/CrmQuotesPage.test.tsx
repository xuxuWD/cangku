import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmQuotesPage } from './CrmQuotesPage'
import type { CrmQuote, CrmQuoteLine } from './types'

const draftQuote: CrmQuote = {
  quote_id: 'q-1', account_id: 'acc-1', opportunity_id: null, quote_no: 'Q-202609-0001', status: 'draft',
  subtotal_cents: 10000, tax_cents: 1300, total_cents: 11300, valid_until: '2026-10-31', confirmed_at: null,
  converted_contract_id: null, owner_id: 'admin', created_at: '2026-09-17T00:00:00Z',
}
const draftLine: CrmQuoteLine = {
  line_no: 1, description: '年度服务', qty: '1.000', unit_price_cents: 10000, tax_rate_bp: 1300,
  line_subtotal_cents: 10000, line_tax_cents: 1300,
}
const confirmedQuote: CrmQuote = { ...draftQuote, quote_id: 'q-2', quote_no: 'Q-202609-0002', status: 'confirmed', confirmed_at: '2026-09-17T01:00:00Z' }

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

function detailFetch(quote: CrmQuote, lines: CrmQuoteLine[], onWrite?: (url: string, init?: RequestInit) => Response | null) {
  return makeFetch((url, init) => {
    if (onWrite) {
      const written = onWrite(url, init)
      if (written) return written
    }
    if (url.includes('/crm/quotes?')) return json({ items: [quote], total: 1, limit: 50, offset: 0 })
    if (url.includes(`/crm/quotes/${quote.quote_id}`)) return json({ quote, lines })
    return json({})
  })
}

describe('CrmQuotesPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists quotes with status and integer-cent totals converted to yuan', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [draftQuote, confirmedQuote], total: 2, limit: 50, offset: 0 })))

    render(<CrmQuotesPage />)

    expect(await screen.findByText('Q-202609-0001')).toBeInTheDocument()
    expect(screen.getByText('草稿', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('已确认（冻结）', { selector: '.status-badge' })).toBeInTheDocument()
    // 11300 分 → ¥113.00（整数运算，不用浮点）
    expect(screen.getAllByText('¥113.00')).toHaveLength(2)
  })

  it('edits draft lines and submits integer cents computed from the yuan input', async () => {
    const fetchMock = detailFetch(draftQuote, [draftLine], (url, init) => {
      if (!url.includes('/lines')) return null
      expect(init?.method).toBe('PUT')
      return json({
        quote: { ...draftQuote, subtotal_cents: 1234, tax_cents: 160, total_cents: 1394 },
        lines: [{ ...draftLine, unit_price_cents: 1234, line_subtotal_cents: 1234, line_tax_cents: 160 }],
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmQuotesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    const priceInput = await screen.findByLabelText('第 1 行单价')
    await userEvent.clear(priceInput)
    await userEvent.type(priceInput, '12.34')
    await userEvent.click(screen.getByRole('button', { name: '保存报价行' }))

    expect(await screen.findByText('报价行已全量替换，金额由服务端重算')).toBeInTheDocument()
    const body = JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).includes('/lines'))?.[1]?.body))
    expect(body).toEqual({ lines: [{ description: '年度服务', qty: '1.000', unit_price_cents: 1234, tax_rate_bp: 1300 }] })
    // 服务端重算后的合计以元展示
    expect(screen.getByText('合计 ¥13.94')).toBeInTheDocument()
  })

  it('freezes a confirmed quote: no line editing, only the follow-up actions', async () => {
    vi.stubGlobal('fetch', detailFetch(confirmedQuote, [draftLine]))

    render(<CrmQuotesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    expect(await screen.findByText('报价已冻结')).toBeInTheDocument()
    expect(screen.queryByLabelText('第 1 行单价')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存报价行' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '转合同' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '作废报价' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认报价' })).not.toBeInTheDocument()
  })

  it('confirms a draft quote and switches to the frozen state', async () => {
    vi.stubGlobal('fetch', detailFetch(draftQuote, [draftLine], (url) => url.includes('/confirm') ? json(confirmedQuote) : null))

    render(<CrmQuotesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    await userEvent.click(await screen.findByRole('button', { name: '确认报价' }))

    expect(await screen.findByText('报价已确认并冻结')).toBeInTheDocument()
    expect(screen.getByText('报价已冻结')).toBeInTheDocument()
  })

  it('surfaces a 409 conflict when the server refuses a frozen write', async () => {
    vi.stubGlobal('fetch', detailFetch(draftQuote, [draftLine], (url) => url.includes('/lines') ? json({ detail: '报价已确认' }, 409) : null))

    render(<CrmQuotesPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    await userEvent.click(await screen.findByRole('button', { name: '保存报价行' }))

    expect(await screen.findByText('状态已被变更，请刷新')).toBeInTheDocument()
  })

  it('shows the empty state when no quote matches', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))

    render(<CrmQuotesPage />)

    expect(await screen.findByText('暂无报价')).toBeInTheDocument()
  })
})