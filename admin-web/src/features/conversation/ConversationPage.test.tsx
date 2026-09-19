import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConversationListProvider } from './listStore'
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
  detailMessages?: unknown[]
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
        messages: options.detailMessages ?? [message(), message({ message_id: 'msg-a', role: 'assistant', content: '（P1 桩回复）已收到你的消息。', stub: true })],
        messages_total: (options.detailMessages ?? [null, null]).length,
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

  it('states the capability notice in business language and loads the list exactly once through the provider', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(
      <ConversationListProvider>
        <ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />
      </ConversationListProvider>,
    )

    // UI v2：「能力说明」只在**本会话出现过占位回复**时渲染；详情里 mock 的助手消息 stub=true。
    expect(await screen.findByText('能力说明')).toBeInTheDocument()
    // 能力边界以业务语言给出（开发态含「开发态」，生产态含「尚未接入真实模型」）。
    expect(screen.getByText(/开发态|尚未接入真实模型/)).toBeInTheDocument()
    expect(screen.queryByText('P1 桩回复')).not.toBeInTheDocument()
    // 列表由 Provider 拉一次，页面**不重复拉** —— 这是"单一可信来源"（真源 §2.17.3）的可测证据。
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('/conversations?limit=20&offset=0'))).toBe(true),
    )
    expect(calls.filter((call) => call.url.includes('/conversations?limit=20&offset=0'))).toHaveLength(1)
  })

  it('opens the conversation given by the URL and marks the assistant stub reply', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    expect(await screen.findByText('整理一下客户反馈')).toBeInTheDocument()
    expect(screen.getByText('占位回复', { selector: '.badge--warn' })).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/conversations/conv-1?limit=50&offset=0'))).toBe(true)
  })

  it('shows which tool a user turn invoked from the message tool_name field, next to the redacted body', async () => {
    const { fetchMock } = makeFetch({
      detailMessages: [
        message({ tool_name: 'fs.write', content: '[工具调用·脱敏] tool_key=fs.write params=[content,path] digest=deadbeef' }),
        message({ message_id: 'msg-a', role: 'assistant', content: '工具已执行完成。', stub: false }),
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    // 用户气泡：正文是脱敏摘要（无参数值），调用的工具名单独按 tool_name 展示。
    expect(await screen.findByText('[工具调用·脱敏] tool_key=fs.write params=[content,path] digest=deadbeef')).toBeInTheDocument()
    expect(document.querySelector('.msg--me .msg__meta .kbd')?.textContent).toBe('fs.write')
  })

  it('renders a user turn without tool_name (legacy message) and shows no tool label', async () => {
    const { fetchMock } = makeFetch({
      detailMessages: [message({ tool_name: null, content: '[消息·脱敏] chars=12 digest=abcd1234' })],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    expect(await screen.findByText('[消息·脱敏] chars=12 digest=abcd1234')).toBeInTheDocument()
    expect(document.querySelector('.msg--me .msg__meta .kbd')).toBeNull()
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
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)
    const onSelectConversation = vi.fn()

    render(<ConversationPage onSelectConversation={onSelectConversation} />)
    await screen.findByRole('heading', { name: '选择一个会话查看消息' })

    await userEvent.click(screen.getByRole('button', { name: '新建对话' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST' && call.url.endsWith('/conversations'))).toBe(true))
    expect(onSelectConversation).toHaveBeenCalledWith('conv-9')
  })

  it('shows the fixed Chinese permission message on 403 without a retry', async () => {
    const { fetchMock } = makeFetch({ listStatus: 403 })
    vi.stubGlobal('fetch', fetchMock)

    // 403 来自会话列表（列表读取被拒 = 整个对话入口不可用）⇒ 用 Provider 复现真实装配。
    render(
      <ConversationListProvider>
        <ConversationPage onSelectConversation={vi.fn()} />
      </ConversationListProvider>,
    )

    expect(await screen.findByText('无法使用对话')).toBeInTheDocument()
    expect(screen.getByText('当前岗位不能使用对话入口')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
    // 403 时整个对话入口不可用：空态与「新建对话」都不渲染（无法开始新会话）。
    expect(screen.queryByRole('button', { name: '新建对话' })).not.toBeInTheDocument()
  })
})
