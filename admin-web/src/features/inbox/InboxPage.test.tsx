import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InboxPage } from './InboxPage'
import type { InboxItem } from './types'

const unreadItem: InboxItem = { inbox_id: 'i-1', kind: 'task.approved', title: '整理本周选题已通过', target_type: 'task', target_id: 'task-1', created_at: '2026-09-11T02:00:00Z', read_at: null }
const readItem: InboxItem = { inbox_id: 'i-2', kind: 'run.failed', title: '发布任务运行失败', target_type: 'run', target_id: 'run-9', created_at: '2026-09-10T02:00:00Z', read_at: '2026-09-10T03:00:00Z' }

function json(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('InboxPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders notifications and the unread count', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem, readItem], unread_count: 1 })
    }))

    render(<InboxPage />)

    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
    expect(screen.getByText('发布任务运行失败')).toBeInTheDocument()
    expect(screen.getByText('未读通知 1 条')).toBeInTheDocument()
  })

  it('shows the empty state when there are no notifications', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], unread_count: 0 })))

    render(<InboxPage />)

    expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  })

  it('shows a retryable error and reloads the list', async () => {
    let listAttempts = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      listAttempts += 1
      if (listAttempts === 1) return { ok: false, status: 500 } as Response
      return json({ items: [unreadItem], unread_count: 1 })
    }))

    render(<InboxPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('通知加载失败')
    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))
    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
  })

  it('marks a single notification as read when clicked', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/inbox/i-1/read')) return json({ ...unreadItem, read_at: '2026-09-11T05:00:00Z' })
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)

    await screen.findByText('整理本周选题已通过')
    await userEvent.click(screen.getByRole('button', { name: '标为已读' }))

    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/inbox/i-1/read') && (call[1] as RequestInit)?.method === 'POST')).toBe(true))
    expect(await screen.findByText('已读', { selector: 'span.status-badge' })).toBeInTheDocument()
  })

  it('marks all notifications as read', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/inbox/read-all')) return json({ updated: 1 })
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)

    await screen.findByText('整理本周选题已通过')
    await userEvent.click(screen.getByRole('button', { name: '全部标记已读' }))

    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/inbox/read-all') && (call[1] as RequestInit)?.method === 'POST')).toBe(true))
    expect(await screen.findByText('未读通知 0 条')).toBeInTheDocument()
  })
})
