import { render, screen, waitFor } from '@testing-library/react'
import { clearSession, loadSession, saveSession, type Session } from '../../app/session'
import { InboxSection } from './InboxSection'
import type { InboxItem } from './types'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'ceo',
  expiresAt: Date.now() + 100_000,
}

const item: InboxItem = { inbox_id: 'i-1', kind: 'task.approved', title: '整理本周选题已通过', target_type: 'task', target_id: 'task-1', created_at: '2026-09-11T02:00:00Z', read_at: null }

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

describe('InboxSection', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders notifications and the unread count', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ items: [item], unread_count: 1 })))

    render(<InboxSection />)

    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
    expect(screen.getByLabelText('未读通知 1 条')).toBeInTheDocument()
    expect(screen.getByText('未读')).toBeInTheDocument()
  })

  it('shows the empty state when there are no notifications', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ items: [], unread_count: 0 })))

    render(<InboxSection />)

    expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  })

  it('notifies the parent and clears the session on 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }) as unknown as Response))

    const onSessionExpired = vi.fn(() => clearSession())
    render(<InboxSection onSessionExpired={onSessionExpired} />)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(loadSession()).toBeNull()
  })
})
