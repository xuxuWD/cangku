import { act, renderHook, waitFor } from '@testing-library/react'
import { useRunStream } from './useRunStream'

function sseResponse(chunks: string[], options: { keepOpen?: boolean } = {}): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      if (!options.keepOpen) controller.close()
    },
  })
  return { ok: true, status: 200, body } as unknown as Response
}

const frame = (seq: number, kind: string, isTerminal = false) =>
  `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, payload: { status: 'ok' }, is_terminal: isTerminal })}\n\n`

function headerOf(init: RequestInit | undefined, name: string): string | undefined {
  const headers = (init?.headers ?? {}) as Record<string, string>
  return headers[name]
}

describe('useRunStream', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads frames, ignores heartbeats and closes on the terminal frame (then calls onTerminal once)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([': hb\n\n', frame(1, 'tool.call'), frame(2, 'run.completed', true)])))
    const onTerminal = vi.fn()

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true, onTerminal }))

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.frames.map((item) => item.kind)).toEqual(['tool.call', 'run.completed'])
    expect(result.current.lastSeq).toBe(2)
    expect(onTerminal).toHaveBeenCalledTimes(1)
  })

  it('reconnects with Last-Event-ID = 已收最大 seq (真增量续播)', async () => {
    const fetchMock = vi.fn()
    // 第一次：服务端关流但未见终态（例如连接寿命到点）⇒ 必须续播而不是从头重放
    fetchMock.mockResolvedValueOnce(sseResponse([frame(5, 'step.started')]))
    fetchMock.mockResolvedValueOnce(sseResponse([frame(6, 'run.completed', true)]))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 5000 })
    expect(String(fetchMock.mock.calls[1][0])).toContain('/conversations/conv-1/stream')
    expect(headerOf(fetchMock.mock.calls[1][1] as RequestInit, 'Last-Event-ID')).toBe('5')
    expect(headerOf(fetchMock.mock.calls[0][1] as RequestInit, 'Last-Event-ID')).toBeUndefined()
    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.frames.map((item) => item.seq)).toEqual([5, 6])
  })

  it('stops on a fatal status (401) without reconnecting', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response)
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aborts the connection when the view is left (切走即断)', async () => {
    let captured: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      captured = init?.signal ?? undefined
      return sseResponse([frame(1, 'step.started')], { keepOpen: true })
    }))

    const { rerender } = renderHook(
      (props: { enabled: boolean }) => useRunStream({ conversationId: 'conv-1', enabled: props.enabled }),
      { initialProps: { enabled: true } },
    )

    await waitFor(() => expect(captured).toBeDefined())
    expect(captured?.aborted).toBe(false)

    await act(async () => {
      rerender({ enabled: false })
    })
    expect(captured?.aborted).toBe(true)
  })

  it('does not open a connection when disabled', async () => {
    const fetchMock = vi.fn(async () => sseResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: false }))
    await act(async () => {})
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.status).toBe('idle')
  })
})