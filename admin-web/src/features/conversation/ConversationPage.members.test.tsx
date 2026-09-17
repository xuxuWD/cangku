import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConversationPage } from './ConversationPage'

const json = (body: unknown, status = 200): Response =>
  ({ ok: status < 400, status, json: async () => body }) as Response

const noContent = (status = 204): Response =>
  ({ ok: true, status, json: async () => { throw new Error('204 无响应体') } }) as unknown as Response

const conversation = {
  conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', mode: 'craft',
  created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-17T09:30:00Z',
}

// 覆盖四种发言者回溯：本人 / 成员命中 / 存量 NULL（发起人）/ 名单里查不到（不编造）。
const messages = [
  { message_id: 'msg-1', conversation_id: 'conv-1', role: 'user', content: '我发的', sender_id: 'admin', stub: false, tool_name: null, tool_call_id: null, created_at: null },
  { message_id: 'msg-2', conversation_id: 'conv-1', role: 'user', content: '成员发的', sender_id: 'u-2', stub: false, tool_name: null, tool_call_id: null, created_at: null },
  { message_id: 'msg-3', conversation_id: 'conv-1', role: 'user', content: '存量消息', sender_id: null, stub: false, tool_name: null, tool_call_id: null, created_at: null },
  { message_id: 'msg-4', conversation_id: 'conv-1', role: 'user', content: '未知发言者', sender_id: 'u-ghost', stub: false, tool_name: null, tool_call_id: null, created_at: null },
  { message_id: 'msg-5', conversation_id: 'conv-1', role: 'assistant', content: '回复', sender_id: null, stub: true, tool_name: null, tool_call_id: null, created_at: null },
]

const ownerItem = {
  member_id: 'admin', display_name: '发起人姓名', role: 'employee', permission: 'owner', is_owner: true,
  added_by: null, created_at: '2026-09-11T02:00:00Z',
}
const memberItem = {
  member_id: 'u-2', display_name: '成员姓名', role: 'employee', permission: 'write', is_owner: false,
  added_by: 'admin', created_at: '2026-09-17T09:00:00Z',
}

interface Call { url: string; method: string; body: string }

function makeFetch(options: { addStatus?: number; addDetail?: string; items?: unknown[]; itemsTotal?: number } = {}) {
  const calls: Call[] = []
  let items = options.items ?? [ownerItem, memberItem]
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (url.includes('/members/u-2') && method === 'DELETE') {
      items = items.filter((item) => (item as { member_id: string }).member_id !== 'u-2')
      return noContent()
    }
    if (url.includes('/conversations/conv-1/members') && method === 'POST') {
      if (options.addStatus && options.addStatus >= 400) return json({ detail: options.addDetail }, options.addStatus)
      const body = JSON.parse(String(init?.body)) as { member_id: string; permission: string }
      items = [...items, {
        member_id: body.member_id, display_name: '新成员姓名', role: 'employee', permission: body.permission,
        is_owner: false, added_by: 'admin', created_at: '2026-09-17T10:00:00Z',
      }]
      return json({ conversation_id: 'conv-1', member_id: body.member_id, permission: body.permission }, 201)
    }
    if (url.includes('/conversations/conv-1/members')) {
      return json({ items, total: options.itemsTotal ?? items.length, limit: 200, offset: 0 })
    }
    if (url.includes('/conversations/conv-1/stream')) {
      const body = new ReadableStream<Uint8Array>({ start(controller) { controller.close() } })
      return { ok: true, status: 200, body, headers: new Headers() } as unknown as Response
    }
    if (url.includes('/conversations/')) {
      return json({ ...conversation, messages, messages_total: messages.length, messages_limit: 50, messages_offset: 0 })
    }
    return json({ items: [conversation], total: 1, limit: 20, offset: 0 })
  })
  return { fetchMock, calls }
}

afterEach(() => vi.unstubAllGlobals())

describe('ConversationPage（P2c-6 会话协作）', () => {
  it('消息气泡按 sender_id 回溯发言者：本人 ⇒「我」、成员 ⇒ 姓名、NULL ⇒「发起人」、查不到 ⇒「会话成员」', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    // 断言限定在**消息气泡**内（参与者区块也会出现同一个姓名，不能混为一谈）。
    const bubble = (text: string) => {
      const node = screen.getByText(text)
      return within(node.closest('article') as HTMLElement)
    }
    expect(await screen.findByText('我发的')).toBeInTheDocument()
    expect(bubble('我发的').getByText('我')).toBeInTheDocument()
    expect(bubble('成员发的').getByText('成员姓名')).toBeInTheDocument()
    expect(bubble('存量消息').getByText('发起人')).toBeInTheDocument()
    expect(bubble('未知发言者').getByText('会话成员')).toBeInTheDocument()
    expect(bubble('回复').getByText('数字员工')).toBeInTheDocument()  // 助手消息仍按角色显示
    // 参与者名单要真的取过（发言者回溯依赖它，不凭猜测）。
    await waitFor(() => expect(calls.some((call) => call.url.includes('/conversations/conv-1/members'))).toBe(true))
  })

  it('参与者区块：发起人列首位并标「发起人」、成员显示权限档，附「最近活动」（会话 updated_at，非实时）', async () => {
    const { fetchMock } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    const section = await screen.findByLabelText('参与者与分享')
    expect(section).toHaveTextContent('发起人姓名')
    expect(section).toHaveTextContent('发起人')
    expect(section).toHaveTextContent('成员姓名')
    expect(section).toHaveTextContent('可发言')
    expect(section).toHaveTextContent('最近活动：')
    expect(section).toHaveTextContent('不做实时在线态')
  })

  it('添加成员：提交账号 + 权限档，成功后刷新名单并提示；已读不可撤回如实告知', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByLabelText('参与者与分享')

    await userEvent.type(screen.getByLabelText('成员账号'), 'u-9')
    await userEvent.selectOptions(screen.getByLabelText('成员权限'), 'write')
    await userEvent.click(screen.getByRole('button', { name: '添加成员' }))

    await waitFor(() => {
      const call = calls.find((item) => item.url.includes('/members') && item.method === 'POST')
      expect(call).toBeTruthy()
      expect(JSON.parse(call?.body ?? '{}')).toEqual({ member_id: 'u-9', permission: 'write' })
    })
    expect(await screen.findByText('新成员姓名')).toBeInTheDocument()
    expect(await screen.findByText(/已添加成员/)).toBeInTheDocument()
    expect(screen.getByText(/已读内容不可撤回/)).toBeInTheDocument()
  })

  it('添加成员被拒（422）⇒ 显示服务端原因，名单不变（不做乐观更新）', async () => {
    const { fetchMock } = makeFetch({ addStatus: 422, addDetail: '成员账号不存在，或不在本租户 / 未审批' })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByLabelText('参与者与分享')

    await userEvent.type(screen.getByLabelText('成员账号'), 'u-unknown')
    await userEvent.click(screen.getByRole('button', { name: '添加成员' }))

    expect(await screen.findByText('成员账号不存在，或不在本租户 / 未审批')).toBeInTheDocument()
    expect(screen.queryByText('新成员姓名')).toBeNull()
  })

  it('参与者超过一页 ⇒ 如实显示命中总数与已显示条数（不静默截断）', async () => {
    const { fetchMock } = makeFetch({ itemsTotal: 3 })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    const section = await screen.findByLabelText('参与者与分享')
    expect(section).toHaveTextContent('3 人（已显示前 2 人）')
  })

  it('撤销成员：DELETE 后从名单移除并如实告知「已读不可撤回」', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    const section = await screen.findByLabelText('参与者与分享')
    expect(section).toHaveTextContent('成员姓名')

    await userEvent.click(screen.getByRole('button', { name: '撤销 成员姓名' }))

    await waitFor(() => expect(calls.some((call) => call.url.includes('/members/u-2') && call.method === 'DELETE')).toBe(true))
    await waitFor(() => expect(screen.queryByText('成员姓名')).toBeNull())
    expect(await screen.findByText(/已撤销成员/)).toBeInTheDocument()
  })
})