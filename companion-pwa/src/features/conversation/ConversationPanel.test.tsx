import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { saveSession, type Session } from '../../app/session'
import { ConversationPanel } from './ConversationPanel'
import type { Conversation, ConversationDetail } from './types'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'employee',
  expiresAt: Date.now() + 100_000,
}

const conversation: Conversation = {
  conversation_id: 'conv-1',
  agent_key: null,
  title: '示例会话',
  status: 'active',
  mode: 'craft',
  created_at: '2026-09-17T00:00:00Z',
  updated_at: '2026-09-17T00:00:00Z',
}

const emptyDetail: ConversationDetail = {
  ...conversation,
  messages: [],
  messages_total: 0,
  messages_limit: 50,
  messages_offset: 0,
}

const filledDetail: ConversationDetail = {
  ...conversation,
  messages: [
    {
      message_id: 'msg-1',
      conversation_id: 'conv-1',
      role: 'user',
      content: '你好',
      stub: false,
      tool_name: null,
      tool_call_id: null,
      created_at: '2026-09-17T00:01:00Z',
    },
    {
      message_id: 'msg-2',
      conversation_id: 'conv-1',
      role: 'assistant',
      content: '你好，数字员工',
      stub: true,
      tool_name: null,
      tool_call_id: null,
      created_at: '2026-09-17T00:01:10Z',
    },
  ],
  messages_total: 2,
  messages_limit: 50,
  messages_offset: 0,
}

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

function fail(status: number, detailText?: string): Response {
  return { ok: false, status, json: async () => (detailText ? { detail: detailText } : {}) } as unknown as Response
}

const frame = (seq: number, kind: string, isTerminal = false) =>
  `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, payload: { status: 'ok' }, is_terminal: isTerminal })}\n\n`

function sse(chunks: string[], options: { runId?: string | null } = {}): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  const headers = new Headers(options.runId === null ? {} : { 'X-Stream-Run-Id': options.runId ?? 'run-1' })
  return { ok: true, status: 200, body, headers } as unknown as Response
}

const listBody = { items: [conversation], total: 1, limit: 20, offset: 0 }

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function headerOf(init: RequestInit | undefined, name: string): string | undefined {
  const headers = (init?.headers ?? {}) as Record<string, string>
  return headers[name]
}

describe('ConversationPanel', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('登录态：请求带 Bearer 令牌；401 ⇒ 触发会话过期回调', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => fail(401))
    vi.stubGlobal('fetch', fetchMock)
    const onSessionExpired = vi.fn()

    render(<ConversationPanel onSessionExpired={onSessionExpired} />)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(headerOf(fetchMock.mock.calls[0]?.[1], 'Authorization')).toBe('Bearer token-abc')
  })

  it('加载态：请求未返回时显示「正在加载会话…」', async () => {
    let resolveList: (response: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveList = resolve })))

    render(<ConversationPanel />)

    expect(screen.getByText('正在加载会话…')).toBeInTheDocument()
    await act(async () => {
      resolveList(ok({ items: [], total: 0, limit: 20, offset: 0 }))
    })
    expect(await screen.findByText('还没有会话')).toBeInTheDocument()
  })

  it('空态：没有会话时如实告知（PWA 不提供新建入口）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ items: [], total: 0, limit: 20, offset: 0 })))

    render(<ConversationPanel />)

    expect(await screen.findByText('还没有会话')).toBeInTheDocument()
    expect(screen.getByText('请先在网页管理台发起对话。')).toBeInTheDocument()
  })

  it('错误态：500 ⇒ 告警 + 重试（重试后恢复列表）', async () => {
    let attempt = 0
    const fetchMock = vi.fn(async () => {
      attempt += 1
      if (attempt === 1) return fail(500)
      return ok(listBody)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ConversationPanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent('对话服务暂时不可用')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('button', { name: /示例会话/ })).toBeInTheDocument()
  })

  it('无权限态：403 ⇒ 显示「无法使用对话」且不给重试', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fail(403, '当前岗位不能使用对话入口')))

    render(<ConversationPanel />)

    expect(await screen.findByText('无法使用对话')).toBeInTheDocument()
    expect(screen.getByText('当前岗位不能使用对话入口')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
  })

  it('列表 → 消息：点会话加载详情并渲染消息与桩标记', async () => {
    const fetchMock = vi.fn<FetchMock>(async (input, init) => {
      const url = String(input)
      if (url.includes('/stream')) return sse([], { runId: null })
      if (url.includes('/conversations/conv-1?')) return ok(filledDetail)
      if (url.includes('/conversations?')) return ok(listBody)
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ConversationPanel />)

    await user.click(await screen.findByRole('button', { name: /示例会话/ }))

    expect(await screen.findByText('你好，数字员工')).toBeInTheDocument()
    expect(screen.getByText('数字员工')).toBeInTheDocument()
    expect(screen.getByText('桩回复')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '示例会话' })).toBeInTheDocument()
  })

  it('发送（纯文本）⇒ POST /messages 不带幂等键，发送后重取详情', async () => {
    let detailCalls = 0
    const fetchMock = vi.fn<FetchMock>(async (input, init) => {
      const url = String(input)
      if (url.includes('/stream')) return sse([], { runId: null })
      if (url.includes('/messages:stream')) return ok({ message_id: 'm-x', conversation_id: 'conv-1', stub: true })
      if (url.includes('/messages')) return ok({ message_id: 'm-2', conversation_id: 'conv-1', stub: true })
      if (url.includes('/conversations/conv-1?')) {
        detailCalls += 1
        return ok(detailCalls === 1 ? emptyDetail : filledDetail)
      }
      if (url.includes('/conversations?')) return ok(listBody)
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ConversationPanel />)

    await user.click(await screen.findByRole('button', { name: /示例会话/ }))
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: '你好' } })
    await user.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input).includes('/conversations/conv-1/messages') && !String(input).includes(':stream') && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    const plainCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes('/conversations/conv-1/messages') && !String(input).includes(':stream') && init?.method === 'POST',
    )
    expect(headerOf(plainCall?.[1], 'Idempotency-Key')).toBeUndefined()
    expect(await screen.findByText('你好，数字员工')).toBeInTheDocument()
  })

  it('发送（结构化）⇒ 带幂等键走 messages:stream，随后读到帧并在折叠条呈现', async () => {
    const structured = '{"tool_key":"fs.read","params":{"path":"/workspace/a.txt"}}'
    const fetchMock = vi.fn<FetchMock>(async (input, init) => {
      const url = String(input)
      if (url.includes('/stream')) return sse([frame(1, 'tool.call'), frame(2, 'run.completed', true)], { runId: 'run-1' })
      if (url.includes('/messages:stream')) {
        return {
          ok: true,
          status: 201,
          json: async () => ({ message_id: 'm-struct', conversation_id: 'conv-1', stub: false, run_id: 'run-1' }),
          headers: new Headers({ 'X-Stream-Run-Id': 'run-1' }),
        } as unknown as Response
      }
      if (url.includes('/messages')) return ok({ message_id: 'm-2', conversation_id: 'conv-1', stub: true })
      if (url.includes('/conversations/conv-1?')) return ok(emptyDetail)
      if (url.includes('/conversations?')) return ok(listBody)
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ConversationPanel />)

    await user.click(await screen.findByRole('button', { name: /示例会话/ }))
    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: structured } })
    expect(screen.getByText('结构化调用：fs.read（按真实执行路径发送）')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '发送' }))

    const streamCall = await waitFor(() => {
      const found = fetchMock.mock.calls.find(([input]) => String(input).includes('/conversations/conv-1/messages:stream'))
      expect(found).toBeTruthy()
      return found
    })
    expect(streamCall?.[1]?.method).toBe('POST')
    expect(headerOf(streamCall?.[1], 'Idempotency-Key')).toBeTruthy()

    expect(await screen.findByText('共 2 条')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '展开' }))
    const log = screen.getByRole('log')
    expect(within(log).getByText('#1')).toBeInTheDocument()
    expect(within(log).getByText('工具调用')).toBeInTheDocument()
    expect(within(log).getByText('运行完成')).toBeInTheDocument()
  })

  it('结构化调用未产生运行 ⇒ 关流并如实告知「本次没有过程流」', async () => {
    const structured = '{"tool_key":"fs.read","params":{}}'
    const fetchMock = vi.fn<FetchMock>(async (input, init) => {
      const url = String(input)
      if (url.includes('/stream')) return sse([], { runId: null })
      if (url.includes('/messages:stream')) return ok({ message_id: 'm-stub', conversation_id: 'conv-1', stub: true })
      if (url.includes('/messages')) return ok({ message_id: 'm-2', conversation_id: 'conv-1', stub: true })
      if (url.includes('/conversations/conv-1?')) return ok(emptyDetail)
      if (url.includes('/conversations?')) return ok(listBody)
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ConversationPanel />)

    await user.click(await screen.findByRole('button', { name: /示例会话/ }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/conversations/conv-1/stream'))).toBe(true))
    const streamCallsBefore = fetchMock.mock.calls.filter(([input]) => String(input).includes('/conversations/conv-1/stream')).length

    fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: structured } })
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('本次没有过程流')).toBeInTheDocument()
    const streamCallsAfter = fetchMock.mock.calls.filter(([input]) => String(input).includes('/conversations/conv-1/stream')).length
    expect(streamCallsAfter).toBe(streamCallsBefore)
  })
})