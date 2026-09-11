import { act, renderHook, waitFor } from '@testing-library/react'
import { clearSession, loadSession, saveSession, type Session } from '../../app/session'
import { resolveInboxPollIntervalMs, useInbox } from './useInbox'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'ceo',
  expiresAt: Date.now() + 100_000,
}

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function inboxResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({ items: [], unread_count: 0 }),
  } as unknown as Response
}

describe('useInbox', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
    vi.stubEnv('VITE_INBOX_POLL_SECONDS', '5')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.useRealTimers()
  })

  it('fetches on mount, polls at the configured interval, and stops after unmount', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => inboxResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const { unmount } = renderHook(() => useInbox())
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('skips the poll request while the document is hidden', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => inboxResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    renderHook(() => useInbox())
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    hiddenSpy.mockRestore()
  })

  it('refreshes immediately when the page becomes visible again', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => inboxResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    renderHook(() => useInbox())
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    hiddenSpy.mockReturnValue(false)
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    hiddenSpy.mockRestore()
  })

  it('signals session expiry and clears the stored session on 401', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ({ ok: false, status: 401, json: async () => ({}) }) as unknown as Response))

    const onExpired = vi.fn(() => clearSession())
    renderHook(() => useInbox(onExpired))

    await waitFor(() => expect(onExpired).toHaveBeenCalledTimes(1))
    expect(loadSession()).toBeNull()
  })

  it('falls back to 30 seconds for an invalid poll interval', () => {
    vi.stubEnv('VITE_INBOX_POLL_SECONDS', 'abc')
    expect(resolveInboxPollIntervalMs()).toBe(30_000)

    vi.stubEnv('VITE_INBOX_POLL_SECONDS', '0')
    expect(resolveInboxPollIntervalMs()).toBe(30_000)
  })
})
