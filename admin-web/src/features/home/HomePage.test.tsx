import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomePage } from './HomePage'

const json = (body: unknown, status = 200): Response => ({ ok: status < 400, status, json: async () => body }) as Response
const failure = (status: number): Response => ({ ok: false, status, json: async () => ({}) }) as Response

const AGENT = { agent_key: 'agent-ops', name: '运营助理', description: '', role_key: 'ops_lead', status: 'active', created_by: 'admin', created_at: null, updated_at: null }

interface Call { url: string; init?: RequestInit }

function stub(handler: (url: string) => Response) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    return handler(url)
  }))
  return calls
}

// 默认假服务端：员工目录可用、暂无会话、建会话成功、发消息成功。
function baseRoute(url: string): Response {
  if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
  if (url.includes('/conversations?')) return json({ items: [], total: 0, limit: 4, offset: 0 })
  if (url.includes('/conversations/') && url.includes('/messages')) return json({ message_id: 'msg-1', conversation_id: 'conv-1', stub: true, reply: {} }, 201)
  if (url.endsWith('/conversations')) return json({ conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', created_at: null, updated_at: null }, 201)
  return json({ id: 'task-1', title: '整理客户反馈', status: 'queued', risk_level: 'low' })
}

describe('HomePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('turns the first message into a conversation and opens it', async () => {
    const calls = stub(baseRoute)
    const onOpenConversation = vi.fn()
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={onOpenConversation} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.type(screen.getByLabelText('想对数字员工说的话'), '整理客户反馈')
    await user.click(screen.getByRole('button', { name: '开始对话' }))

    await waitFor(() => expect(onOpenConversation).toHaveBeenCalledWith('conv-1'))

    const created = calls.find((call) => call.init?.method === 'POST' && String(call.url).endsWith('/conversations'))
    expect(JSON.parse(String(created?.init?.body))).toMatchObject({ agent_key: 'agent-ops', title: '整理客户反馈' })

    const sent = calls.find((call) => String(call.url).includes('/conversations/conv-1/messages'))
    expect(sent?.init?.method).toBe('POST')
    expect(JSON.parse(String(sent?.init?.body))).toEqual({ content: '整理客户反馈' })

    // 先建会话、再发消息：顺序不能倒过来（会话 id 来自第一步的响应）。
    const createdIndex = calls.findIndex((call) => call.init?.method === 'POST' && String(call.url).endsWith('/conversations'))
    const sentIndex = calls.findIndex((call) => String(call.url).includes('/conversations/conv-1/messages'))
    expect(createdIndex).toBeGreaterThanOrEqual(0)
    expect(sentIndex).toBeGreaterThan(createdIndex)
  })

  it('keeps task creation as a secondary entry and reports pending approval', async () => {
    const calls = stub((url) => (url.endsWith('/tasks') ? json({ id: 'task-9', title: '接入新渠道', status: 'pending_approval', risk_level: 'high' }) : baseRoute(url)))
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={vi.fn()} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.click(screen.getByRole('button', { name: '或直接建任务' }))
    await user.type(screen.getByLabelText('任务描述'), '接入新渠道')
    await user.selectOptions(screen.getByLabelText('风险等级'), 'high')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('任务已创建并提交审批：task-9', { selector: '.toast span' })).toBeInTheDocument()

    const posted = calls.find((call) => String(call.url).endsWith('/tasks'))
    expect(JSON.parse(String(posted?.init?.body))).toMatchObject({
      title: '接入新渠道',
      employee_key: 'agent-ops',
      risk_level: 'high',
      budget: 0,
    })
  })

  it('cannot start a conversation without a message', async () => {
    stub(baseRoute)
    render(<HomePage onOpenConversation={vi.fn()} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    expect(screen.getByRole('button', { name: '开始对话' })).toBeDisabled()
  })

  it('points at the directory when no digital employee is enabled', async () => {
    stub((url) => (url.includes('/workforce/agents') ? json({ items: [{ ...AGENT, status: 'disabled' }], total: 1, limit: 50, offset: 0 }) : baseRoute(url)))
    const onNavigate = vi.fn()
    render(<HomePage onOpenConversation={vi.fn()} onNavigate={onNavigate} />)

    expect(await screen.findByText('还没有启用中的数字员工')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: '去创建' }))
    expect(onNavigate).toHaveBeenCalledWith('workforceSettings')
  })

  it('shows a retryable error when the employee list fails', async () => {
    stub((url) => (url.includes('/workforce/agents') ? failure(500) : baseRoute(url)))
    render(<HomePage onOpenConversation={vi.fn()} />)

    expect(await screen.findByText('数字员工读取失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
  })

  it('surfaces a rejected conversation creation without navigating or inventing a success', async () => {
    stub((url) => (url.endsWith('/conversations') ? failure(403) : baseRoute(url)))
    const onOpenConversation = vi.fn()
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={onOpenConversation} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.type(screen.getByLabelText('想对数字员工说的话'), '整理客户反馈')
    await user.click(screen.getByRole('button', { name: '开始对话' }))

    expect(await screen.findByText('会话创建失败')).toBeInTheDocument()
    expect(onOpenConversation).not.toHaveBeenCalled()
  })

  it('opens a recent conversation', async () => {
    stub((url) => (url.includes('/conversations?')
      ? json({ items: [{ conversation_id: 'conv-7', agent_key: 'agent-ops', title: '数字员工如何提升交付效率', status: 'active', created_at: null, updated_at: '2026-09-11T02:00:00Z' }], total: 1, limit: 4, offset: 0 })
      : baseRoute(url)))
    const onOpenConversation = vi.fn()
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={onOpenConversation} />)

    await user.click(await screen.findByRole('button', { name: /数字员工如何提升交付效率/ }))
    expect(onOpenConversation).toHaveBeenCalledWith('conv-7')
  })

  it('shows the empty state when there is no conversation yet', async () => {
    stub(baseRoute)
    render(<HomePage onOpenConversation={vi.fn()} />)

    await waitFor(() => expect(screen.getByText('还没有会话')).toBeInTheDocument())
  })
})
