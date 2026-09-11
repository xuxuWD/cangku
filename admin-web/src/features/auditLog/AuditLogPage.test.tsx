import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuditLogPage } from './AuditLogPage'
import type { AuditRecord } from './types'

const loginRecord: AuditRecord = { record_id: 'audit-1', action: 'account.login.succeeded', actor_id: 'admin', target_type: 'task', target_id: 'task-1', phone_masked: '138****8000', detail: { reason: '手动触发', provider: 'wechat', attempts: 2, approved: true, nested: { step_id: 's-1' } }, occurred_at: '2026-09-11T02:00:00Z' }
const failedRecord: AuditRecord = { record_id: 'audit-2', action: 'inbox.write_failed', actor_id: null, target_type: null, target_id: null, phone_masked: null, detail: {}, occurred_at: '2026-09-10T02:00:00Z' }

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string) => Response) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    return handler(url)
  })
}

describe('AuditLogPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads and renders records with labels, masked phone and scalar details', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [loginRecord, failedRecord], total: 2, limit: 50, offset: 0 })))

    render(<AuditLogPage />)

    expect(await screen.findByText('account.login.succeeded')).toBeInTheDocument()
    expect(screen.getByText(/登录成功/, { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText(/138\*\*\*\*8000/)).toBeInTheDocument()
    expect(screen.getByText(/task:task-1/)).toBeInTheDocument()
    expect(screen.getByText('reason: 手动触发')).toBeInTheDocument()
    expect(screen.getByText('attempts: 2')).toBeInTheDocument()
    expect(screen.getByText('approved: 是')).toBeInTheDocument()
    // 嵌套对象只折叠为「…」，不 dump 结构。
    expect(screen.getByText('nested: …')).toBeInTheDocument()
    expect(screen.getByText(/共 2 条（第 1–2 条）/)).toBeInTheDocument()
  })

  it('resets offset to zero when a filter is submitted', async () => {
    const fetchMock = makeFetch((url) => json({ items: [loginRecord], total: 120, limit: 50, offset: Number(new URL(url).searchParams.get('offset') ?? '0') }))
    vi.stubGlobal('fetch', fetchMock)
    const auditUrls = () => fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes('/audits?'))
    const lastAuditUrl = () => auditUrls()[auditUrls().length - 1] ?? ''

    render(<AuditLogPage />)
    await screen.findByText('account.login.succeeded')

    await userEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(lastAuditUrl()).toContain('offset=50'))

    await userEvent.type(screen.getByLabelText('操作者'), 'someone')
    await userEvent.click(screen.getByRole('button', { name: '查询' }))

    await waitFor(() => expect(lastAuditUrl()).toContain('actor_id=someone'))
    expect(lastAuditUrl()).toContain('offset=0')
  })

  it('disables pagination buttons at both boundaries', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [loginRecord], total: 120, limit: 50, offset: 0 })))

    const first = render(<AuditLogPage />)
    await screen.findByText('account.login.succeeded')
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '上一页' })).toBeEnabled())
    first.unmount()

    vi.stubGlobal('fetch', makeFetch(() => json({ items: [loginRecord], total: 30, limit: 50, offset: 0 })))
    render(<AuditLogPage />)
    await screen.findByText('account.login.succeeded')
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  })

  it('shows the empty state when nothing matches', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))

    render(<AuditLogPage />)

    expect(await screen.findByText('没有匹配的审计记录')).toBeInTheDocument()
  })

  it('shows an error and retries the same query', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      attempts += 1
      if (attempts === 1) return json({}, 500)
      return json({ items: [failedRecord], total: 1, limit: 50, offset: 0 })
    }))

    render(<AuditLogPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('审计日志加载失败')
    expect(screen.getByText('审计服务暂时不可用，请检查网络后重新尝试。')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('inbox.write_failed')).toBeInTheDocument()
  })
})
