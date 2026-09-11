import { act, renderHook } from '@testing-library/react'
import { saveSession, type Session } from '../../app/session'
import { usePendingApprovals } from './usePendingApprovals'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'ceo',
  expiresAt: Date.now() + 100_000,
}

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function pendingResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({ items: [], counts: { task_approval: 0, plan_proposal: 0, account_registration: 0, total: 0 } }),
  } as unknown as Response
}

describe('usePendingApprovals', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
    vi.stubEnv('VITE_APPROVAL_POLL_SECONDS', '5')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.useRealTimers()
  })

  it('fetches on mount, polls at the configured interval, and stops after unmount', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => pendingResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const { unmount } = renderHook(() => usePendingApprovals())
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
    const fetchMock = vi.fn<FetchMock>(async () => pendingResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    renderHook(() => usePendingApprovals())
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
    const fetchMock = vi.fn<FetchMock>(async () => pendingResponse())
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    renderHook(() => usePendingApprovals())
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
})
