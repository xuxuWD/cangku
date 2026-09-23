import { act, renderHook, waitFor } from '@testing-library/react'
import { useRunStream } from '../useRunStream'

function sseResponse(
  chunks: string[],
  options: { keepOpen?: boolean; runId?: string | null } = {},
): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      if (!options.keepOpen) controller.close()
    },
  })
  // 缺省带 `X-Stream-Run-Id`（模拟「该会话已有 run」）；`runId: null` 表示服务端无 run（P2c-2 只增头）。
  const headers = new Headers(options.runId === null ? {} : { 'X-Stream-Run-Id': options.runId ?? 'run-1' })
  return { ok: true, status: 200, body, headers } as unknown as Response
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
    // ⚠️ 桩必须实现 `text()`：基座请求层在 `!ok` 时会**读响应体**再构造错误，
    // 缺 `text()` 会抛成"网络失败"（status 0）从而被当成可重试 —— 真浏览器的 401 一定有体。
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => '',
      json: async () => ({}),
    }) as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('历史会话：run id 取自读端响应头 X-Stream-Run-Id（只增；供概览与审批使用）', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame(1, 'run.completed', true)))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      body,
      headers: new Headers({ 'X-Stream-Run-Id': 'run-history' }),
    }) as unknown as Response))

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.runId).toBe('run-history'))
    expect(result.current.status).toBe('closed')
  })

  it('连接建立时无 run、帧内 run_id 出现（只增）⇒ 之后解析出当前 run', async () => {
    const lateRun = `id: 1\nevent: tool.call\ndata: ${JSON.stringify({ run_id: 'run-late', seq: 1, kind: 'tool.call', payload: {}, is_terminal: true })}\n\n`
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([lateRun])))

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.runId).toBe('run-late'))
  })

  it('显式 runId 优先于响应头（本次发送的 run 不被覆盖）', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame(1, 'run.completed', true)))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      body,
      headers: new Headers({ 'X-Stream-Run-Id': 'run-from-header' }),
    }) as unknown as Response))

    const { result } = renderHook(() =>
      useRunStream({ conversationId: 'conv-1', runId: 'run-explicit', enabled: true }),
    )

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.runId).toBe('run-explicit')
  })

  it('连接建立时无 run（无响应头）⇒ 关流并如实告知「无可用过程数据」（不空等）', async () => {
    const body = new ReadableStream<Uint8Array>({ start() { /* 挂起：不发帧也不关闭 */ } })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      body,
      headers: new Headers(),
    }) as unknown as Response))

    const { result } = renderHook(() => useRunStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.noData).toBe(true)
  })

  it('发送进行中（awaitRun）⇒ 缺 run 不关流，继续等新 run 出现（边执行边看）', async () => {
    const lateRun = `id: 1\nevent: tool.call\ndata: ${JSON.stringify({ run_id: 'run-live', seq: 1, kind: 'tool.call', payload: {}, is_terminal: true })}\n\n`
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        setTimeout(() => {
          controller.enqueue(encoder.encode(lateRun))
          controller.close()
        }, 20)
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      body,
      headers: new Headers(),
    }) as unknown as Response))

    const { result } = renderHook(() =>
      useRunStream({ conversationId: 'conv-1', enabled: true, awaitRun: true }),
    )

    await waitFor(() => expect(result.current.runId).toBe('run-live'))
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