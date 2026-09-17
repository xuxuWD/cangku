import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmContractsPage } from './CrmContractsPage'
import type { CrmContract } from './types'

const draftContract: CrmContract = {
  contract_id: 'c-1', account_id: 'acc-1', quote_id: 'q-1', opportunity_id: null, contract_no: 'C-202609-0001',
  title: '年度服务合同', status: 'draft', amount_cents: 1200000, paid_cents: 0, starts_on: '2026-10-01',
  ends_on: '2027-09-30', document_object_key: '', signed_at: null, owner_id: 'admin', created_at: '2026-09-17T00:00:00Z',
}
const pendingContract: CrmContract = { ...draftContract, status: 'pending_sign' }
const signedContract: CrmContract = { ...draftContract, contract_id: 'c-2', contract_no: 'C-202609-0002', status: 'signed', signed_at: '2026-09-17T02:00:00Z', paid_cents: 300000 }

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

function detailFetch(contract: CrmContract, onWrite?: (url: string, init?: RequestInit) => Response | null) {
  return makeFetch((url, init) => {
    if (onWrite) {
      const written = onWrite(url, init)
      if (written) return written
    }
    if (url.includes('/crm/contracts?')) return json({ items: [contract], total: 1, limit: 50, offset: 0 })
    if (url.includes(`/crm/contracts/${contract.contract_id}`)) return json(contract)
    return json({})
  })
}

describe('CrmContractsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists contracts with integer-cent amounts and payment progress', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [draftContract, signedContract], total: 2, limit: 50, offset: 0 })))

    render(<CrmContractsPage />)

    expect(await screen.findByText('C-202609-0001')).toBeInTheDocument()
    expect(screen.getByText('草稿', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('已签署（人工登记）', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getAllByText('¥12000.00')).toHaveLength(2)
    expect(screen.getByText('¥3000.00')).toBeInTheDocument()
    expect(screen.getByText('25.00%')).toBeInTheDocument()
    expect(screen.getByText('0.00%')).toBeInTheDocument()
  })

  it('states that signing is a manual ledger entry without legal effect', async () => {
    vi.stubGlobal('fetch', detailFetch(signedContract))

    render(<CrmContractsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    expect(await screen.findByText('签署为人工登记，系统不承诺法律效力')).toBeInTheDocument()
    expect(screen.getByText(/不对签署效力或存证效力作任何承诺/)).toBeInTheDocument()
  })

  it('registers a payment converted from yuan into integer cents', async () => {
    const fetchMock = detailFetch(signedContract, (url, init) => {
      if (!url.includes('/register-payment')) return null
      expect(init?.method).toBe('POST')
      return json({ ...signedContract, paid_cents: 1500000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmContractsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    await userEvent.type(await screen.findByLabelText('回款金额（元）'), '12000.00')
    await userEvent.click(screen.getByRole('button', { name: '登记回款' }))

    expect(await screen.findByText('回款已登记（人工输入）')).toBeInTheDocument()
    const body = JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).includes('/register-payment'))?.[1]?.body))
    expect(body).toEqual({ amount_cents: 1200000 })
    expect(screen.getByText('¥15000.00')).toBeInTheDocument()
  })

  it('registers a signature with the plain (non-ISO) datetime input, converting to Z form', async () => {
    const fetchMock = detailFetch(pendingContract, (url, init) => {
      if (!url.includes('/register-signature')) return null
      expect(init?.method).toBe('POST')
      return json(signedContract)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<CrmContractsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    const signedAt = await screen.findByLabelText('签署时间')
    fireEvent.change(signedAt, { target: { value: '2026-09-17T10:00' } })
    await userEvent.type(screen.getByLabelText('签署件对象键'), 'obj/signed.pdf')
    await userEvent.click(screen.getByRole('button', { name: '登记签署结果' }))

    expect(await screen.findByText(/已登记签署结果（人工台账/)).toBeInTheDocument()
    const body = JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).includes('/register-signature'))?.[1]?.body))
    expect(body.signed_at).toBe(new Date('2026-09-17T10:00').toISOString())
    expect(body.document_object_key).toBe('obj/signed.pdf')
  })

  it('reports the payment 409 conflict with the over-limit explanation', async () => {
    vi.stubGlobal('fetch', detailFetch(signedContract, (url) => url.includes('/register-payment') ? json({ detail: '回款金额超过合同金额' }, 409) : null))

    render(<CrmContractsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    await userEvent.type(await screen.findByLabelText('回款金额（元）'), '999.00')
    await userEvent.click(screen.getByRole('button', { name: '登记回款' }))

    expect(await screen.findByText('回款登记被拒绝：仅已签署合同可登记，且累计回款不能超过合同金额。')).toBeInTheDocument()
  })

  it('shows the empty state and the failure notice', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))
    const first = render(<CrmContractsPage />)
    expect(await screen.findByText('暂无合同')).toBeInTheDocument()
    first.unmount()

    vi.stubGlobal('fetch', makeFetch(() => json({}, 500)))
    render(<CrmContractsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('合同列表加载失败')
  })
})