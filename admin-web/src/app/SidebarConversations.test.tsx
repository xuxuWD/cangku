import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConversationListProvider } from '../features/conversation/listStore'
import { SidebarConversations } from './SidebarConversations'

const json = (body: unknown, status = 200): Response =>
  ({ ok: status < 400, status, json: async () => body }) as Response

function conversation(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: 'conv-1',
    agent_key: 'agent-ops',
    title: '整理客户反馈',
    status: 'active',
    mode: 'craft',
    created_at: '2026-09-11T02:00:00Z',
    updated_at: '2026-09-11T02:00:00Z',
    ...overrides,
  }
}

/** 左栏会话列表的所有行为都经由 Provider（真源 §2.17.3）⇒ 这里按真实装配渲染。 */
function stubList(body: unknown, status = 200) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      return json(body, status)
    }),
  )
  return { calls }
}

function renderSidebar(
  props: { activeConversationId?: string; onSelectConversation?: (conversationId: string) => void } = {},
) {
  return render(
    <ConversationListProvider>
      <SidebarConversations {...props} />
    </ConversationListProvider>,
  )
}

describe('SidebarConversations', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the contract pagination fields, each row status and mode label', async () => {
    const { calls } = stubList({ items: [conversation()], total: 1, limit: 20, offset: 0 })
    renderSidebar()

    expect(await screen.findByText('整理客户反馈')).toBeInTheDocument()
    expect(document.querySelector('.conversations__count')?.textContent).toBe('共 1 条')
    expect(screen.getByText('进行中', { selector: '.badge' })).toBeInTheDocument()
    expect(screen.getByText('完整执行', { selector: '.conv__meta span' })).toBeInTheDocument()
    expect(calls.some((url) => url.includes('/conversations?limit=20&offset=0'))).toBe(true)
  })

  it('marks the conversation that is currently open', async () => {
    stubList({ items: [conversation()], total: 1, limit: 20, offset: 0 })
    renderSidebar({ activeConversationId: 'conv-1' })

    const row = await screen.findByText('整理客户反馈')
    expect(row.closest('.conv')).toHaveAttribute('aria-current', 'true')
  })

  it('selects a conversation on click', async () => {
    stubList({ items: [conversation()], total: 1, limit: 20, offset: 0 })
    const onSelectConversation = vi.fn()
    renderSidebar({ onSelectConversation })

    await userEvent.click(await screen.findByText('整理客户反馈'))

    expect(onSelectConversation).toHaveBeenCalledWith('conv-1')
  })

  it('selects a conversation with the keyboard', async () => {
    stubList({ items: [conversation()], total: 1, limit: 20, offset: 0 })
    const onSelectConversation = vi.fn()
    renderSidebar({ onSelectConversation })

    const row = (await screen.findByText('整理客户反馈')).closest('.conv') as HTMLElement
    row.focus()
    await userEvent.keyboard('{Enter}')

    expect(onSelectConversation).toHaveBeenCalledWith('conv-1')
  })

  it('shows an empty state that points at the new-conversation button', async () => {
    stubList({ items: [], total: 0, limit: 20, offset: 0 })
    renderSidebar()

    expect(await screen.findByText('还没有会话')).toBeInTheDocument()
    expect(screen.getByText('点上面的「新建对话」开始。')).toBeInTheDocument()
  })

  it('offers a retry when the list fails with a retryable error', async () => {
    stubList({ detail: '服务暂时不可用' }, 500)
    renderSidebar()

    expect(await screen.findByText('对话服务暂时不可用，请检查网络后重新尝试。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
  })

  it('switches the status filter and reloads from the first page', async () => {
    const { calls } = stubList({ items: [conversation()], total: 1, limit: 20, offset: 0 })
    renderSidebar()
    await screen.findByText('整理客户反馈')

    await userEvent.click(screen.getByRole('tab', { name: '已归档' }))

    await waitFor(() => expect(calls.some((url) => url.includes('status=archived'))).toBe(true))
    expect(calls.some((url) => url.includes('status=archived&limit=20&offset=0'))).toBe(true)
  })
})
