import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConversationPage } from './ConversationPage'

const json = (body: unknown, status = 200): Response => ({ ok: status < 400, status, json: async () => body }) as Response

function conversation(overrides: Record<string, unknown> = {}) {
  return { conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-11T02:00:00Z', ...overrides }
}

function message(overrides: Record<string, unknown> = {}) {
  return { message_id: 'msg-1', conversation_id: 'conv-1', role: 'user', content: '整理一下客户反馈', stub: false, tool_name: null, tool_call_id: null, created_at: '2026-09-11T02:00:00Z', ...overrides }
}

interface Options {
  listStatus?: number
  detailStatus?: number
  sendStatus?: number
  sendDetail?: string
  archived?: boolean
  emptyList?: boolean
}

interface Call { url: string; method: string; body: string }

function makeFetch(options: Options = {}) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })

    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (url.includes('/messages')) {
      if (options.sendStatus && options.sendStatus >= 400) return json({ detail: options.sendDetail }, options.sendStatus)
      return json({
        message_id: 'msg-2',
        conversation_id: 'conv-1',
        stub: true,
        reply: message({ message_id: 'msg-2', role: 'assistant', content: '（P1 桩回复）已收到你的消息。', stub: true }),
      }, 201)
    }
    if (url.includes('/archive')) return json(conversation({ status: 'archived' }))
    if (method === 'POST' && url.includes('/conversations')) return json(conversation({ conversation_id: 'conv-9', title: '' }), 201)

    if (url.includes('/conversations/')) {
      if (options.detailStatus && options.detailStatus >= 400) return json({ detail: '会话不存在' }, options.detailStatus)
      return json({
        ...conversation(options.archived ? { status: 'archived' } : {}),
        messages: [message(), message({ message_id: 'msg-a', role: 'assistant', content: '（P1 桩回复）已收到你的消息。', stub: true })],
        messages_total: 2,
        messages_limit: 50,
        messages_offset: 0,
      })
    }

    if (options.listStatus && options.listStatus >= 400) return json({ detail: '当前岗位不能使用对话入口' }, options.listStatus)
    if (options.emptyList) return json({ items: [], total: 0, limit: 20, offset: 0 })
    return json({ items: [conversation()], total: 1, limit: 20, offset: 0 })
  })
  return { fetchMock, calls }
}

describe('ConversationPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists conversations with the contract pagination fields and states the P1 stub up front', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage onSelectConversation={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: '对话' })).toBeInTheDocument()
    expect(await screen.findByText('整理客户反馈')).toBeInTheDocument()
    expect(screen.getByText('P1 桩回复')).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/conversations?limit=20&offset=0'))).toBe(true)
  })

  it('opens the conversation given by the URL and marks the assistant stub reply', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    expect(await screen.findByText('整理一下客户反馈')).toBeInTheDocument()
    expect(screen.getByText('桩回复', { selector: '.status-badge' })).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/conversations/conv-1?limit=50&offset=0'))).toBe(true)
  })

  it('selects a conversation from the list', async () => {
    const { fetchMock } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)
    const onSelectConversation = vi.fn()

    render(<ConversationPage onSelectConversation={onSelectConversation} />)
    await screen.findByText('整理客户反馈')

    await userEvent.click(screen.getByText('整理客户反馈'))

    expect(onSelectConversation).toHaveBeenCalledWith('conv-1')
  })

  it('disables the input and explains why on an archived conversation instead of letting the 409 happen', async () => {
    const { fetchMock } = makeFetch({ archived: true })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    await screen.findByText('整理一下客户反馈')
    expect(screen.getByLabelText('消息内容')).toBeDisabled()
    expect(screen.getByRole('button', { name: '发送消息' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '归档' })).toBeDisabled()
    expect(screen.getByText('会话已归档', { selector: 'strong' })).toBeInTheDocument()
  })

  it('sends a message, waits for the server and shows the reply the backend returned', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.type(screen.getByLabelText('消息内容'), '再补一条')
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    const posted = calls.find((call) => call.method === 'POST' && call.url.includes('/messages'))
    expect(posted && JSON.parse(posted.body)).toEqual({ content: '再补一条' })
    expect(await screen.findByText('（P1 桩回复）已收到你的消息。')).toBeInTheDocument()
  })

  it('surfaces a 409 without pretending the message was accepted', async () => {
    const { fetchMock } = makeFetch({ sendStatus: 409, sendDetail: '会话已归档，不能再追加消息' })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.type(screen.getByLabelText('消息内容'), '再补一条')
    await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

    expect(await screen.findByText('消息发送失败')).toBeInTheDocument()
    expect(screen.getByText('会话已归档，不能再追加消息')).toBeInTheDocument()
  })

  it('archives the conversation from the server response', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.click(screen.getByRole('button', { name: '归档' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.url.includes('/archive'))).toBe(true))
    expect(await screen.findByLabelText('消息内容')).toBeDisabled()
  })

  it('creates a new conversation and opens it', async () => {
    const { fetchMock, calls } = makeFetch({ emptyList: true })
    vi.stubGlobal('fetch', fetchMock)
    const onSelectConversation = vi.fn()

    render(<ConversationPage onSelectConversation={onSelectConversation} />)
    await screen.findByText('还没有会话')

    await userEvent.click(screen.getByRole('button', { name: '新建会话' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.url.endsWith('/conversations'))).toBe(true))
    expect(onSelectConversation).toHaveBeenCalledWith('conv-9')
  })

  it('shows the fixed Chinese permission message on 403 without a retry', async () => {
    const { fetchMock } = makeFetch({ listStatus: 403 })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage onSelectConversation={vi.fn()} />)

    expect(await screen.findByText('当前岗位不能使用对话入口')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建会话' })).toBeDisabled()
  })

  it('offers a retry when the list fails with a retryable error', async () => {
    const { fetchMock } = makeFetch({ listStatus: 500 })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage onSelectConversation={vi.fn()} />)

    expect(await screen.findByText('会话列表加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
  })
})
