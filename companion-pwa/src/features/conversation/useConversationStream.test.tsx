import { renderHook, waitFor } from '@testing-library/react'
import { useConversationStream } from './useConversationStream'

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
  // 缺省带 `X-Stream-Run-Id`（模拟「该会话已有 run」）；`runId: null` 表示服务端无 run。
  const headers = new Headers(options.runId === null ? {} : { 'X-Stream-Run-Id': options.runId ?? 'run-1' })
  return { ok: true, status: 200, body, headers } as unknown as Response
}

const frame = (seq: number, kind: string, isTerminal = false) =>
  `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, payload: { status: 'ok' }, is_terminal: isTerminal })}\n\n`

function headerOf(init: RequestInit | undefined, name: string): string | undefined {
  const headers = (init?.headers ?? {}) as Record<string, string>
  return headers[name]
}

describe('useConversationStream', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('读取帧、忽略心跳、终态关流并回调一次', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([': hb\n\n', frame(1, 'tool.call'), frame(2, 'run.completed', true)])),
    )
    const onTerminal = vi.fn()

    const { result } = renderHook(() =>
      useConversationStream({ conversationId: 'conv-1', enabled: true, onTerminal }),
    )

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.frames.map((item) => item.kind)).toEqual(['tool.call', 'run.completed'])
    expect(result.current.lastSeq).toBe(2)
    expect(onTerminal).toHaveBeenCalledTimes(1)
  })

  it('重连以 Last-Event-ID 真增量续播（首连不带，续播带已收最大 seq）', async () => {
    const fetchMock = vi.fn()
    // 第一次：服务端关流但未见终态（例如连接寿命到点）⇒ 必须续播而不是从头重放。
    fetchMock.mockResolvedValueOnce(sseResponse([frame(5, 'step.started')]))
    fetchMock.mockResolvedValueOnce(sseResponse([frame(6, 'run.completed', true)]))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useConversationStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 5000 })
    expect(String(fetchMock.mock.calls[1][0])).toContain('/conversations/conv-1/stream')
    expect(headerOf(fetchMock.mock.calls[1][1] as RequestInit, 'Last-Event-ID')).toBe('5')
    expect(headerOf(fetchMock.mock.calls[0][1] as RequestInit, 'Last-Event-ID')).toBeUndefined()
    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.frames.map((item) => item.seq)).toEqual([5, 6])
  })

  it('跨块多字节字符不破帧（中文按字节切开仍能解析）', async () => {
    const encoder = new TextEncoder()
    const textWithChinese = `id: 1\nevent: message.assistant\ndata: ${JSON.stringify({ seq: 1, kind: 'message.assistant', payload: { excerpt: '中文跨块内容' }, is_terminal: true })}\n\n`
    const raw = encoder.encode(textWithChinese)
    // 切点选在某个多字节字符的续字节上（0b10xxxxxx），确保真的把一个字符劈成两半。
    const cut = raw.findIndex((byte, index) => index > 0 && (byte & 0xc0) === 0x80)
    expect(cut).toBeGreaterThan(0)
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(raw.slice(0, cut))
        controller.enqueue(raw.slice(cut))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      body,
      headers: new Headers({ 'X-Stream-Run-Id': 'run-1' }),
    }) as unknown as Response))

    const { result } = renderHook(() => useConversationStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.frames.map((item) => item.seq)).toEqual([1])
    expect(result.current.frames[0]?.payload.excerpt).toBe('中文跨块内容')
  })

  it('401 ⇒ 停连并触发 onSessionExpired（不重连）', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }) as Response)
    vi.stubGlobal('fetch', fetchMock)
    const onSessionExpired = vi.fn()

    const { result } = renderHook(() =>
      useConversationStream({ conversationId: 'conv-1', enabled: true, onSessionExpired }),
    )

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onSessionExpired).toHaveBeenCalledTimes(1)
  })

  it('连接建立时无 run（无响应头）⇒ 关流 + noData，不挂空连接', async () => {
    const fetchMock = vi.fn(async () => sseResponse([], { runId: null }))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useConversationStream({ conversationId: 'conv-1', enabled: true }))

    await waitFor(() => expect(result.current.status).toBe('closed'))
    expect(result.current.noData).toBe(true)
    expect(result.current.frames).toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('切走（enabled=false）⇒ 断开连接且不再发起请求', async () => {
    const fetchMock = vi.fn(async () => sseResponse([': hb\n\n'], { keepOpen: true }))
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useConversationStream({ conversationId: 'conv-1', enabled }),
      { initialProps: { enabled: true } },
    )

    await waitFor(() => expect(result.current.status).toBe('streaming'))
    rerender({ enabled: false })

    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})