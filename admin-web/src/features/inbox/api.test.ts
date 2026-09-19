import { listInbox, markAllInboxRead, markInboxRead } from './api'
import type { InboxItem } from './types'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const readItem: InboxItem = { inbox_id: 'i-1', kind: 'task.approved', title: '任务已通过', target_type: 'task', target_id: 'task-1', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z' }

describe('inbox api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists notifications with the unread filter and limit', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ({ ok: true, json: async () => ({ items: [], unread_count: 3 }) }) as Response)
    vi.stubGlobal('fetch', fetchMock)

    await expect(listInbox(true, 10)).resolves.toEqual({ items: [], unread_count: 3 })

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/inbox?')
    expect(url).toContain('unread_only=true')
    expect(url).toContain('limit=10')
  })

  it('marks a single notification as read', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ({ ok: true, json: async () => readItem }) as Response)
    vi.stubGlobal('fetch', fetchMock)

    await expect(markInboxRead('i-1')).resolves.toMatchObject({ inbox_id: 'i-1', read_at: '2026-09-11T03:00:00Z' })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/inbox/i-1/read')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('marks all notifications as read', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ({ ok: true, json: async () => ({ updated: 2 }) }) as Response)
    vi.stubGlobal('fetch', fetchMock)

    await expect(markAllInboxRead()).resolves.toEqual({ updated: 2 })

    expect(String(fetchMock.mock.calls[0][0])).toContain('/inbox/read-all')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('normalizes unauthorized responses into a Chinese error', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response))

    await expect(listInbox()).rejects.toMatchObject({ status: 401, unauthorized: true, message: '当前账号没有查看通知的权限。' })
  })
})
