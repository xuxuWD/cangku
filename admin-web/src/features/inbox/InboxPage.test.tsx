import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InboxPage } from './InboxPage'
import type { InboxItem } from './types'

const unreadItem: InboxItem = { inbox_id: 'i-1', kind: 'task.approved', title: '整理本周选题已通过', target_type: 'task', target_id: 'task-1', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: null }
const readItem: InboxItem = { inbox_id: 'i-2', kind: 'run.failed', title: '发布任务运行失败', target_type: 'run', target_id: 'run-9', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-10T02:00:00Z', read_at: '2026-09-10T03:00:00Z' }

function json(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

describe('InboxPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders notifications and the unread count', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem, readItem], unread_count: 1 })
    }))

    render(<InboxPage />)

    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
    expect(screen.getByText('发布任务运行失败')).toBeInTheDocument()
    expect(screen.getByText('未读通知 1 条')).toBeInTheDocument()
  })

  it('shows the empty state when there are no notifications', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], unread_count: 0 })))

    render(<InboxPage />)

    expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  })

  it('shows a retryable error and reloads the list', async () => {
    let listAttempts = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      listAttempts += 1
      if (listAttempts === 1) return { ok: false, status: 500 } as Response
      return json({ items: [unreadItem], unread_count: 1 })
    }))

    render(<InboxPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('通知加载失败')
    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))
    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
  })

  it('marks a single notification as read when clicked', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/inbox/i-1/read')) return json({ ...unreadItem, read_at: '2026-09-11T05:00:00Z' })
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)

    await screen.findByText('整理本周选题已通过')
    await userEvent.click(screen.getByRole('button', { name: '标为已读' }))

    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/inbox/i-1/read') && (call[1] as RequestInit)?.method === 'POST')).toBe(true))
    expect(await screen.findByText('已读', { selector: 'span.status-badge' })).toBeInTheDocument()
  })

  it('marks all notifications as read', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/inbox/read-all')) return json({ updated: 1 })
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)

    await screen.findByText('整理本周选题已通过')
    await userEvent.click(screen.getByRole('button', { name: '全部标记已读' }))

    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/inbox/read-all') && (call[1] as RequestInit)?.method === 'POST')).toBe(true))
    expect(await screen.findByText('未读通知 0 条')).toBeInTheDocument()
  })

  it('opens the run detail for a run notification', async () => {
    const onOpenRun = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [readItem], unread_count: 0 })
    }))

    render(<InboxPage onOpenRun={onOpenRun} />)

    await screen.findByText('发布任务运行失败')
    await userEvent.click(screen.getByRole('button', { name: '打开运行详情' }))

    expect(onOpenRun).toHaveBeenCalledWith('run-9')
  })

  // S3：发布转人工接管的 target_id 是**来源任务 id**（后端口径），因此落到任务页。
  it('opens the source task for a publication notification and marks it read', async () => {
    const onOpenTask = vi.fn()
    const publication: InboxItem = { inbox_id: 'i-3', kind: 'publication.manual_takeover', title: '发布需要人工接管', target_type: 'publication', target_id: 'task-77', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: null }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/inbox/i-3/read')) return json({ ...publication, read_at: '2026-09-11T06:00:00Z' })
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [publication], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage onOpenTask={onOpenTask} />)

    await screen.findByText('发布需要人工接管')
    await userEvent.click(screen.getByRole('button', { name: '打开来源任务' }))

    expect(onOpenTask).toHaveBeenCalledWith('task-77')
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/inbox/i-3/read'))).toBe(true))
  })

  // S3：CRM 两类落到各自的列表页（列表页当前不支持按单据高亮，如实落到页面）。
  it('routes crm notifications to their list pages', async () => {
    const onNavigate = vi.fn()
    const contract: InboxItem = { inbox_id: 'i-4', kind: 'crm.renewal.window', title: '合同进入续约窗口', target_type: 'crm_contract', target_id: 'c-1', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z' }
    const activity: InboxItem = { inbox_id: 'i-5', kind: 'crm.activity.due', title: '跟进任务到期', target_type: 'crm_activity', target_id: 'act-1', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [contract, activity], unread_count: 0 })
    }))

    render(<InboxPage onNavigate={onNavigate} />)

    await userEvent.click(await screen.findByRole('button', { name: '打开合同页' }))
    expect(onNavigate).toHaveBeenCalledWith('crmContracts')
    await userEvent.click(screen.getByRole('button', { name: '打开进度概览' }))
    expect(onNavigate).toHaveBeenCalledWith('crmProgress')
  })

  // S3：没有处理入口的类型**不给按钮**、行内如实说明——不假装可点（点了没反应不算通过）。
  it('explains honestly for target types without a page instead of pretending to open', async () => {
    const onOpenTask = vi.fn()
    const proposal: InboxItem = { inbox_id: 'i-6', kind: 'plan.rejected', title: '三步计划被驳回', target_type: 'plan_proposal', target_id: 'p-1', target_conversation_id: null, target_approval_id: null, created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [proposal], unread_count: 0 })
    }))

    render(<InboxPage onOpenTask={onOpenTask} />)

    await screen.findByText('三步计划被驳回')
    const row = screen.getByText('三步计划被驳回').closest('article') as HTMLElement
    expect(row).toHaveTextContent('计划提案的处理入口尚未交付：现在只能看到它，标记已读即可。')
    // 行内**没有**任何可点操作（不假装可点）；页面级的「全部标记已读」不算。
    expect(within(row).queryByRole('button')).toBeNull()
    expect(onOpenTask).not.toHaveBeenCalled()
  })

  // T3：切到「未读」只筛已加载的 items（read_at === null），**不改变任何服务端语义**。
  it('filters to unread rows in the client without another server request', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 1 })
      return json({ items: [unreadItem, readItem], unread_count: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)

    expect(await screen.findByText('整理本周选题已通过')).toBeInTheDocument()
    expect(screen.getByText('发布任务运行失败')).toBeInTheDocument()
    const listRequests = () => fetchMock.mock.calls.filter((call) => String(call[0]).includes('unread_only=false')).length

    await userEvent.click(screen.getByRole('tab', { name: '未读' }))

    expect(screen.getByRole('tab', { name: '未读' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('整理本周选题已通过')).toBeInTheDocument()
    expect(screen.queryByText('发布任务运行失败')).toBeNull()
    expect(listRequests()).toBe(1)
  })

  it('shows the unread empty state when the loaded list has nothing unread', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [readItem], unread_count: 0 })
    }))

    render(<InboxPage />)

    await screen.findByText('发布任务运行失败')
    await userEvent.click(screen.getByRole('tab', { name: '未读' }))

    expect(screen.getByText('没有未读通知')).toBeInTheDocument()
  })

  // 403 = 无权限：固定文案，不给重试（重试也还是 403）。
  it('shows a fixed permission message for 403 without a retry', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403 } as Response)))

    render(<InboxPage />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('暂时无法查看通知')
    expect(alert).toHaveTextContent('当前账号没有查看通知的权限。')
    expect(within(alert).queryByRole('button')).toBeNull()
  })

  // S1 第三款：带会话上文的通知直达「该会话的该条卡」（审批标识一并交给页面聚焦）。
  it('opens the conversation card when the notification carries conversation context', async () => {
    const onOpenConversation = vi.fn()
    const onOpenRun = vi.fn()
    const rejected: InboxItem = { inbox_id: 'i-7', kind: 'run.approval_rejected', title: '你的任务运行被审批驳回', target_type: 'run', target_id: 'run-9', target_conversation_id: 'conv-1', target_approval_id: 'ap-1', created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [rejected], unread_count: 0 })
    }))

    render(<InboxPage onOpenConversation={onOpenConversation} onOpenRun={onOpenRun} />)

    await screen.findByText('你的任务运行被审批驳回')
    await userEvent.click(screen.getByRole('button', { name: '打开该会话的审批' }))

    expect(onOpenConversation).toHaveBeenCalledWith('conv-1', 'ap-1')
    expect(onOpenRun).not.toHaveBeenCalled()
  })

  // 无会话上文（存量通知 / 非对话触发的运行）⇒ 仍按既有落点打开运行详情，不被新入口劫持。
  it('falls back to the run detail when a run notification has no conversation context', async () => {
    const onOpenConversation = vi.fn()
    const onOpenRun = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('limit=1')) return json({ items: [], unread_count: 0 })
      return json({ items: [readItem], unread_count: 0 })
    }))

    render(<InboxPage onOpenConversation={onOpenConversation} onOpenRun={onOpenRun} />)

    await screen.findByText('发布任务运行失败')
    await userEvent.click(screen.getByRole('button', { name: '打开运行详情' }))

    expect(onOpenRun).toHaveBeenCalledWith('run-9')
    expect(onOpenConversation).not.toHaveBeenCalled()
  })
})
