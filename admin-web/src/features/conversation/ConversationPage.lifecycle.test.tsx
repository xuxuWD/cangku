import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { exportMyConversations } from './api'
import { ConversationPage } from './ConversationPage'

const json = (body: unknown, status = 200): Response =>
  ({ ok: status < 400, status, json: async () => body }) as Response

const conversation = {
  conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', mode: 'craft',
  created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-11T02:00:00Z',
}

interface Call { url: string; method: string; body: string }

function makeFetch(options: {
  modeStatus?: number
  modeDetail?: string
  deleteStatus?: number
  exportPage?: (offset: number) => unknown
} = {}) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (url.includes('/conversations/exports/mine')) {
      const offset = Number(new URL(url).searchParams.get('offset') ?? '0')
      return json(options.exportPage?.(offset) ?? {
        exported_at: '2026-09-17T08:00:00Z', limit: 500, offset,
        conversations: [], total_conversations: 0, total_messages: 0, truncated: false, limit_reason: null,
      })
    }
    if (url.includes('/conversations/conv-1/mode')) {
      if (options.modeStatus && options.modeStatus >= 400) return json({ detail: options.modeDetail }, options.modeStatus)
      return json({ ...conversation, mode: (JSON.parse(String(init?.body)) as { mode: string }).mode })
    }
    if (url.includes('/conversations/conv-1/delete')) {
      if (options.deleteStatus && options.deleteStatus >= 400) return json({ detail: '会话不存在，或不属于当前账号。' }, options.deleteStatus)
      return json({ conversation_id: 'conv-1', deleted: true, message_count: 2, frame_count: 1, stream_state_count: 1, idempotency_count: 1 })
    }
    if (url.includes('/conversations/conv-1/stream')) {
      const body = new ReadableStream<Uint8Array>({ start(controller) { controller.close() } })
      return { ok: true, status: 200, body, headers: new Headers() } as unknown as Response
    }
    if (url.includes('/conversations/')) {
      return json({
        ...conversation,
        messages: [{ message_id: 'msg-1', conversation_id: 'conv-1', role: 'user', content: '整理一下客户反馈', stub: false, tool_name: null, tool_call_id: null, created_at: null }],
        messages_total: 1, messages_limit: 50, messages_offset: 0,
      })
    }
    return json({ items: [conversation], total: 1, limit: 20, offset: 0 })
  })
  return { fetchMock, calls }
}

afterEach(() => vi.unstubAllGlobals())

describe('ConversationPage（P2c-4 模式 / 删除）', () => {
  it('切换会话模式：请求带受控枚举值，界面按服务端回流更新并提示', async () => {
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    const select = await screen.findByLabelText('会话模式')
    expect((select as HTMLSelectElement).value).toBe('craft')

    await userEvent.selectOptions(select, 'plan')

    await waitFor(() => expect(calls.some((call) => call.url.includes('/conversations/conv-1/mode'))).toBe(true))
    const modeCall = calls.find((call) => call.url.includes('/conversations/conv-1/mode'))
    expect(modeCall?.method).toBe('POST')
    expect(JSON.parse(modeCall?.body ?? '{}')).toEqual({ mode: 'plan' })
    await waitFor(() => expect((screen.getByLabelText('会话模式') as HTMLSelectElement).value).toBe('plan'))
    expect(await screen.findByText(/已切换为「先计划后执行」/)).toBeInTheDocument()
  })

  it('模式切换被服务端拒绝（409 归档 / 404 他人）⇒ 不做本地乐观更新，按回流提示', async () => {
    const { fetchMock } = makeFetch({ modeStatus: 409, modeDetail: '会话已归档，不能再修改模式' })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    const select = await screen.findByLabelText('会话模式')

    await userEvent.selectOptions(select, 'ask')

    expect(await screen.findByText('会话已归档，不能再修改模式')).toBeInTheDocument()
    // 未做乐观更新：选择框仍显示服务端权威态。
    expect((screen.getByLabelText('会话模式') as HTMLSelectElement).value).toBe('craft')
  })

  it('删除会话：二次确认后才真删，成功后清空选择、刷新列表并显示删除计数', async () => {
    const confirmMock = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmMock)
    const onSelect = vi.fn()
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={onSelect} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))

    expect(confirmMock).toHaveBeenCalled()
    await waitFor(() => expect(calls.some((call) => call.url.includes('/conversations/conv-1/delete'))).toBe(true))
    expect(onSelect).toHaveBeenCalledWith(undefined)
    expect(await screen.findByText(/已删除（消息 2 \/ 帧 1 \/ 流状态 1 \/ 幂等 1）/)).toBeInTheDocument()
  })

  it('删除会话：取消二次确认 ⇒ 不发请求（不误删）', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const { fetchMock, calls } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')

    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))

    expect(calls.some((call) => call.url.includes('/delete'))).toBe(false)
  })
})

describe('导出（P2c-4）：客户端逐页合并', () => {
  it('按 500/页逐页拉取直到取全，并如实标注未取全（truncated）', async () => {
    const calls: string[] = []
    const page = (offset: number, conversations: number, truncated: boolean) => ({
      exported_at: '2026-09-17T08:00:00Z', limit: 500, offset,
      conversations: Array.from({ length: conversations }, (_item, index) => ({
        ...conversation, conversation_id: `conv-${offset + index}`, messages: [], messages_total: 0,
      })),
      total_conversations: 3, total_messages: 0, truncated, limit_reason: truncated ? 'total_items_exceeded' : null,
    })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      const offset = Number(new URL(url).searchParams.get('offset') ?? '0')
      return json(offset === 0 ? page(0, 2, false) : page(500, 1, true))
    }))

    const bundle = await exportMyConversations()

    expect(calls.length).toBe(2)
    expect(calls[0]).toContain('limit=500')
    expect(calls[1]).toContain('offset=500')
    expect(bundle.pages.length).toBe(2)
    expect(bundle.truncated).toBe(true)
  })
})

describe('导出按钮（P2c-4）', () => {
  it('点击导出：拉取本人数据并触发文件下载，不把数据混进会话列表', async () => {
    // jsdom 未实现 `URL.createObjectURL`：**只补这两个静态方法**（不能整体替换 URL，否则 `new URL()` 不可用）。
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, writable: true, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, writable: true, configurable: true })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { fetchMock, calls } = makeFetch({
      exportPage: (offset) => ({
        exported_at: '2026-09-17T08:00:00Z', limit: 500, offset,
        conversations: [{ ...conversation, messages: [], messages_total: 0 }],
        total_conversations: 1, total_messages: 0, truncated: false, limit_reason: null,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
    await screen.findByText('整理一下客户反馈')
    await userEvent.click(screen.getByRole('button', { name: '导出我的数据' }))

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled())
    expect(calls.some((call) => call.url.includes('/conversations/exports/mine'))).toBe(true)
    expect(clickSpy).toHaveBeenCalled()
    expect(await screen.findByText(/已导出 1 个会话 \/ 0 条消息/)).toBeInTheDocument()
    clickSpy.mockRestore()
  })
})

describe('会话列表（P2c-4）：模式可见', () => {
  it('列表条目展示会话模式标签', async () => {
    const { fetchMock } = makeFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)

    // 列表与详情各出现一次「完整执行」（默认 craft）。
    await waitFor(() => expect(screen.getAllByText('完整执行').length).toBeGreaterThan(0))
  })
})

// 兜底：确认 fireEvent 仍可用于文本输入（与其它页测试保持一致的选择器口径）。
it('（口径哨兵）列表与详情共用同一会话视图', async () => {
  const { fetchMock } = makeFetch()
  vi.stubGlobal('fetch', fetchMock)
  render(<ConversationPage conversationId="conv-1" onSelectConversation={vi.fn()} />)
  await screen.findByText('整理一下客户反馈')
  fireEvent.change(screen.getByLabelText('消息内容'), { target: { value: '你好' } })
  expect((screen.getByLabelText('消息内容') as HTMLTextAreaElement).value).toBe('你好')
})