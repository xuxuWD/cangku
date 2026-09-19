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
  if (url.includes('/inbox')) return json({ items: [], unread_count: 0 })
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

    await screen.findByRole('heading', { name: /今天让数字员工做点什么/ })
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

    await screen.findByRole('heading', { name: /今天让数字员工做点什么/ })
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

  it('offers the critical risk level added in migration 025 and posts it verbatim', async () => {
    const calls = stub((url) =>
      url.endsWith('/tasks')
        ? json({ id: 'task-10', title: '删库演练', status: 'pending_approval', risk_level: 'critical' })
        : baseRoute(url)
    )
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={vi.fn()} />)

    await screen.findByRole('heading', { name: /今天让数字员工做点什么/ })
    await user.click(screen.getByRole('button', { name: '或直接建任务' }))
    await user.type(screen.getByLabelText('任务描述'), '删库演练')
    await user.selectOptions(screen.getByLabelText('风险等级'), 'critical')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    await waitFor(() => {
      const posted = calls.find((call) => String(call.url).endsWith('/tasks'))
      expect(JSON.parse(String(posted?.init?.body))).toMatchObject({ risk_level: 'critical' })
    })
  })

  it('cannot start a conversation without a message', async () => {
    stub(baseRoute)
    render(<HomePage onOpenConversation={vi.fn()} />)

    await screen.findByRole('heading', { name: /今天让数字员工做点什么/ })
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

    await screen.findByRole('heading', { name: /今天让数字员工做点什么/ })
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

  // S5：待我审批指标卡与「等你拍板」列表同源（同一个聚合端点）；有落点的行可直达，
  // 没有处理入口的类型只给如实说明（不给按钮）。
  it('surfaces pending approvals from the aggregate endpoint and jumps to the actionable row', async () => {
    const onOpenRun = vi.fn()
    stub((url) => {
      if (url.includes('/approvals/pending')) {
        return json({
          items: [
            { kind: 'run_approval', target_id: 'a-1', title: '整理选题', requested_by: 'u-1', created_at: '2026-09-18T00:00:00+00:00', detail: { run_id: 'run-7', approval_id: 'a-1', step_id: 's-1', tool: 'search' } },
            { kind: 'plan_proposal', target_id: 'p-1', title: '三步计划', requested_by: 'u-2', created_at: '2026-09-18T00:00:00+00:00', detail: { step_count: 3 } },
          ],
          counts: { task_approval: 0, plan_proposal: 1, account_registration: 0, run_approval: 1, total: 2 },
        })
      }
      return baseRoute(url)
    })
    const user = userEvent.setup()
    render(<HomePage onOpenConversation={vi.fn()} onOpenRun={onOpenRun} />)

    // 指标卡数值取服务端 counts.total
    const metric = await screen.findByRole('button', { name: /待我审批/ })
    expect(metric).toHaveTextContent('2')
    expect(metric).toHaveTextContent('任务 / 计划 / 运行内 / 账号注册')

    // 列表按类型标注 + 有落点的一行给真实按钮
    expect(screen.getByText('待我审批 2 项')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '打开运行去审批' }))
    expect(onOpenRun).toHaveBeenCalledWith('run-7')

    // 没有处理入口的类型：不给按钮、只给如实说明
    expect(screen.getByText('计划提案的处理入口尚未交付：现在只能看到它，交付后可直接处理。')).toBeInTheDocument()

    // 指标卡点开 = 焦点落到第一条可操作按钮（键盘用户可继续回车直达）
    await user.click(metric)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '打开运行去审批' }))
  })
})
