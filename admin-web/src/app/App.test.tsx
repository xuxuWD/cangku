import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const json = (body: unknown): Response => ({ ok: true, json: async () => body }) as Response

function stubApi() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const method = init?.method ?? 'GET'
    // 左栏「新建对话」（真源 §2.17.1）走的就是这条写路径。
    if (method === 'POST' && path.endsWith('/conversations')) {
      return json({ conversation_id: 'conv-9', agent_key: 'agent-ops', title: '', status: 'active', mode: 'craft', created_at: null, updated_at: null })
    }
    if (path.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (path.includes('/workforce/agents')) return json({ items: [{ agent_key: 'agent-ops', name: '运营助理', description: '', role_key: 'content-operator', status: 'active', created_by: 'admin', created_at: null, updated_at: null }], total: 1, limit: 50, offset: 0 })
    if (path.includes('/content-tasks/')) return json({ task_id: 'task-1', run_id: 'run-1', status: 'reviewing', revision: 1, topic: '整理本周选题', sources: [], knowledge_references: [], draft: { draft_id: 'draft-1', title: '整理本周选题', summary: '摘要', body_markdown: '正文', image_suggestions: [], citations: [], template_version: 'mock-content-v1' } })
    if (path.includes('/content-tasks')) return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    if (path.includes('/workforce/roles')) return json({ items: [{ role_key: 'content-operator', name: '自媒体运营岗', description: '', status: 'active' }], total: 1, limit: 200, offset: 0 })
    if (path.includes('/workforce/candidates')) return json({ roles: [], agents: [] })
    // 会话详情（`/conversations/<id>?...`）——必须先于列表判断，且**不能**回落到知识绑定替身，
    // 否则详情形状失真会让 `conversationTitle` 抛错、整棵树被卸载（表现为"找不到任何元素"）。
    if (method === 'GET' && /\/conversations\/[^/?]+(\?|$)/.test(path)) {
      return json({
        conversation_id: 'conv-1',
        agent_key: 'agent-ops',
        title: '整理客户反馈',
        status: 'active',
        mode: 'craft',
        created_at: '2026-09-11T02:00:00Z',
        updated_at: '2026-09-11T02:00:00Z',
        messages: [],
        messages_total: 0,
        messages_limit: 50,
        messages_offset: 0,
      })
    }
    if (path.includes('/conversations?')) return json({ items: [], total: 0, limit: 4, offset: 0 })
    if (path.includes('/commercial/usage')) return json({ tenant_id: 'demo-tenant', units: 12, cost_cents: 340 })
    return json(path.includes('/audits') ? [] : { binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: ['company-general'] })
  }))
}

// UI v2：外壳顶栏用 `span.topbar__title` 作当前视图标题（对话页等已重绘页面不再有同名 h1）。
const topbarTitle = (): string | null | undefined => document.querySelector('.topbar__title')?.textContent

async function waitForView(title: string): Promise<void> {
  await waitFor(() => expect(topbarTitle()).toBe(title))
}

/** UI v2 侧栏是扁平入口 + 「更多」子项，统一通过导航内的按钮名定位。 */
function navButton(name: string): HTMLElement {
  return within(screen.getByRole('navigation', { name: '主导航' })).getByRole('button', { name })
}

function sidebarEl(): HTMLElement {
  return document.querySelector('.sidebar') as HTMLElement
}

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
    window.localStorage.clear()
    // 首访引导已看过（否则每个用例都要先关一次浮层）；「只出现一次」由专门用例验证。
    window.localStorage.setItem('workbench.onboarding.seen', '1')
    stubApi()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('opens the conversation page by default and renders the flat sidebar', async () => {
    render(<App />)

    // P2c-1：对话是主轴（默认视图）
    await waitForView('对话')
    expect(screen.getByText('选择一个会话查看消息')).toBeInTheDocument()

    // UI v2 §3.2 侧栏：品牌 + 常驻主操作 + 扁平入口
    expect(screen.getByText('公司数字员工工作台', { selector: '.brand__name' })).toBeInTheDocument()
    expect(within(sidebarEl()).getByRole('button', { name: '新建对话' })).toBeInTheDocument()
    for (const label of ['工作台', '对话', '任务', '员工', '知识']) {
      expect(navButton(label)).toBeInTheDocument()
    }
    // 「更多」默认折叠
    expect(navButton('更多')).toHaveAttribute('aria-expanded', 'false')

    // 原「首页」归档为「工作台」，入口保留且可用
    expect(navButton('工作台')).toBeInTheDocument()
  })

  // UI v2 §3.2 取代旧口径：侧栏不再有分组折叠；「更多」是一个内存态开合的子清单，
  // 全部次级入口一次点击可达（展开后点一条即到）。旧的分组折叠持久化（workbench.sidebar.sections）不再适用。
  it('expands the 更多 submenu and reaches the secondary entries in one click', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    const more = navButton('更多')
    expect(more).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelector('.nav-sub')?.classList.contains('is-open')).toBe(false)

    await user.click(more)
    expect(more).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelector('.nav-sub')?.classList.contains('is-open')).toBe(true)
    for (const label of ['协同动态', '通知', '安全与审计', '用量与费用', '客户', '商机', '报价', '合同', '进度概览']) {
      expect(navButton(label)).toBeInTheDocument()
    }

    // 点一条即到对应页面（≤1 次点击），并回收子清单。
    await user.click(navButton('通知'))
    expect(window.location.search).toBe('?view=inbox')

    // 再点「更多」可以收起（折叠态不再显示子项）。
    await user.click(navButton('更多'))
    expect(navButton('更多')).toHaveAttribute('aria-expanded', 'false')
  })

  it('creates a conversation from the sidebar and opens it', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(within(sidebarEl()).getByRole('button', { name: '新建对话' }))

    await waitFor(() => expect(window.location.search).toContain('conversation=conv-9'))
  })

  it('keeps the open conversation when the 对话 entry is clicked again (IA-03)', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/?view=conversation&conversation=conv-1')
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('对话'))

    // 点当前模块入口不得丢掉已打开的会话（批 1 审计 IA-03）。
    expect(window.location.search).toContain('conversation=conv-1')
  })

  it('opens the page guide with ? and closes it with Escape; shortcuts and the version live in settings', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.keyboard('?')

    // UI v2：`?` 打开的是**当前页**的使用指南抽屉。
    const drawer = await screen.findByRole('dialog', { name: '对话 · 使用指南' })
    expect(within(drawer).getByText('⏱ 30 秒上手')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '对话 · 使用指南' })).not.toBeInTheDocument()

    // 快捷键表与版本号已从弹层移到设置页「帮助与反馈」。
    await user.click(screen.getByRole('button', { name: '设置' }))
    await waitForView('设置')
    await user.click(screen.getByRole('button', { name: '帮助与反馈' }))

    expect(screen.getByText('快捷键')).toBeInTheDocument()
    expect(screen.getByText('Enter')).toBeInTheDocument()
    expect(screen.getByText(/^版本 /)).toBeInTheDocument()
  })

  it('使用指南抽屉：进入即聚焦、Tab 不跑到遮罩后、Esc 后焦点回到入口（验收标准 5）', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    const trigger = screen.getByRole('button', { name: '使用指南' })
    await user.click(trigger)

    const drawer = await screen.findByRole('dialog', { name: '对话 · 使用指南' })
    // ① 打开即把焦点移入抽屉（否则键盘/读屏用户仍停在遮罩后的页面上）
    expect(drawer.contains(document.activeElement)).toBe(true)

    // ② Tab 在抽屉内循环：从最后一个可聚焦元素再 Tab 回到第一个
    const buttons = Array.from(drawer.querySelectorAll('button'))
    buttons[buttons.length - 1].focus()
    await user.tab()
    expect(document.activeElement).toBe(buttons[0])

    // ③ 关闭后焦点归位到打开它的按钮
    await user.keyboard('{Escape}')
    expect(document.activeElement).toBe(trigger)
  })

  it('opens the page guide from the topbar entry', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(screen.getByRole('button', { name: '使用指南' }))

    expect(await screen.findByRole('dialog', { name: '对话 · 使用指南' })).toBeInTheDocument()
  })

  it('shows the onboarding only on the first visit', async () => {
    window.localStorage.removeItem('workbench.onboarding.seen')
    const user = userEvent.setup()
    const first = render(<App />)

    const dialog = await screen.findByRole('dialog', { name: '欢迎使用' })
    // 模态语义 + 焦点移入（与使用指南抽屉同一套规则）。
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog.contains(document.activeElement)).toBe(true)
    await user.click(within(dialog).getByRole('button', { name: '知道了' }))

    expect(screen.queryByRole('dialog', { name: '欢迎使用' })).not.toBeInTheDocument()
    expect(window.localStorage.getItem('workbench.onboarding.seen')).toBe('1')

    // 再次打开不再打扰（关闭一次即记住）。
    first.unmount()
    render(<App />)
    await waitForView('对话')
    expect(screen.queryByRole('dialog', { name: '欢迎使用' })).not.toBeInTheDocument()
  })

  it('keeps navigation reachable on a narrow viewport (窄屏侧栏收进抽屉也不能变成死路)', async () => {
    // 窄屏（≤720px）下侧栏收进抽屉：顶栏按钮负责开合，导航项必须仍在 DOM 里且可打开。
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('720px'),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    window.localStorage.clear() // 首次访问

    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    expect(document.querySelectorAll('.nav-item').length).toBeGreaterThan(0)

    const toggle = screen.getByRole('button', { name: '打开或收起侧栏' })
    await user.click(toggle)
    expect(document.querySelector('.app')?.className).toContain('is-drawer-open')
  })

  it('navigates to the content workbench from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('任务'))

    expect(window.location.search).toBe('?view=workbench')
    // 合并后「任务」页签 = 原内容工作台（锚点：内容主题输入框）
    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())
  })

  // M2 合并：`?view=history` 保留为别名，落到「任务」页的历史草稿页签（老深链不破）。
  it('maps the legacy history deep link to the tasks history tab', async () => {
    window.history.replaceState({}, '', '/?view=history')
    render(<App />)

    await waitFor(() => expect(screen.getByRole('tab', { name: '历史草稿' })).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByLabelText('状态筛选')).toBeInTheDocument()
    expect(screen.queryByLabelText('内容主题')).not.toBeInTheDocument()
  })

  it('switches between the tasks tabs and reflects it in the URL', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('任务'))
    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())

    await user.click(screen.getByRole('tab', { name: '历史草稿' }))
    expect(window.location.search).toBe('?view=workbench&tab=history')
    await waitFor(() => expect(screen.getByLabelText('状态筛选')).toBeInTheDocument())

    await user.click(screen.getByRole('tab', { name: '任务' }))
    expect(window.location.search).toBe('?view=workbench')
    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())
  })

  it('renders the knowledge access page for the knowledge view', async () => {
    window.history.replaceState({}, '', '/?view=knowledge')

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument()
      expect(screen.getByText('可以使用的知识库')).toBeInTheDocument()
    })
  })

  it('navigates to the knowledge access page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('知识'))

    expect(window.location.search).toBe('?view=knowledge')
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())
  })

  it('renders the workforce roster page and drops the hardcoded sidebar summary', async () => {
    window.history.replaceState({}, '', '/?view=workforce')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/workforce/roster')) return json({ items: [{ key: 'content-operator', role_knowledge_base_ids: ['company-general'], agent_knowledge_base_ids: [], task_count: 2 }], total: 1 })
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      return json({})
    }))

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '员工与岗位' })).toBeInTheDocument())
    expect(await screen.findByText('content-operator')).toBeInTheDocument()
    expect(screen.queryByText('本月授权概况')).not.toBeInTheDocument()
    expect(screen.queryByText(/已配置 18 个岗位/)).not.toBeInTheDocument()
  })

  it('navigates to the workforce roster page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('员工'))

    expect(window.location.search).toBe('?view=workforce')
    await waitFor(() => expect(screen.getByRole('heading', { name: '员工与岗位' })).toBeInTheDocument())
  })

  // UI v2 §3.2：数字员工设置不再单列侧栏入口，改为「员工」页内进入（T4 配置页），
  // 深链 `?view=workforceSettings` 仍然可用（批 1 G-01 不得破坏）。
  it('reaches the workforce settings page from the workforce page and by deep link', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('员工'))
    expect(window.location.search).toBe('?view=workforce')
    await waitFor(() => expect(screen.getByRole('heading', { name: '员工与岗位' })).toBeInTheDocument())

    // 页头动作区里的入口（空态里还有一个同名按钮，故按区域定位）
    const actions = document.querySelector('.t3__actions') as HTMLElement
    await user.click(within(actions).getByRole('button', { name: '数字员工设置' }))
    expect(window.location.search).toBe('?view=workforceSettings')
    // M3：该页已重绘 ⇒ 顶栏标题即唯一的 h1（页面内不再重复标题）。
    await waitForView('数字员工设置')
    expect(screen.queryByRole('heading', { name: '数字员工设置', level: 2 })).toBeNull()

    // 深链直开同样可达（刷新后仍在该页）。
    window.history.replaceState({}, '', '/?view=workforceSettings')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitForView('数字员工设置')
  })

  it('navigates to the usage and billing page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('更多'))
    await user.click(navButton('用量与费用'))

    expect(window.location.search).toBe('?view=billing')
    await waitFor(() => expect(screen.getByRole('heading', { name: '用量与费用' })).toBeInTheDocument())
  })

  it('navigates to the CRM accounts page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      if (url.includes('/crm/accounts?')) return json({ items: [], total: 0, limit: 50, offset: 0 })
      return json({})
    }))

    await user.click(navButton('更多'))
    await user.click(navButton('客户'))

    expect(window.location.search).toBe('?view=crmAccounts')
    await waitFor(() => expect(screen.getByRole('heading', { name: '客户' })).toBeInTheDocument())
    expect(await screen.findByText('暂无客户')).toBeInTheDocument()
  })

  // S3：运行详情可携带来源会话 ⇒ 页面给「回到会话」退路；不带来源时**不渲染假按钮**。
  it('keeps the origin conversation on the run detail and offers a way back', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/?view=run&run=run-1&conversation=conv-1')
    render(<App />)

    // M3：该页已重绘 ⇒ 顶栏标题即唯一的 h1；「回到会话」退路在页内面包屑行。
    await waitForView('运行详情')
    const crumbs = document.querySelector('.crumbs') as HTMLElement
    expect(within(crumbs).getByRole('button', { name: '← 回到会话' })).toBeInTheDocument()
    expect(within(crumbs).getByText('对话 / 运行详情')).toBeInTheDocument()

    await user.click(within(crumbs).getByRole('button', { name: '← 回到会话' }))
    expect(window.location.search).toBe('?view=conversation&conversation=conv-1')
  })

  it('does not render a back-to-conversation button when the run has no origin conversation', async () => {
    window.history.replaceState({}, '', '/?view=run&run=run-2')
    render(<App />)

    await waitForView('运行详情')
    expect(document.querySelector('.crumbs')).toBeNull()
  })

  it('navigates to the conversation page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('对话'))

    expect(window.location.search).toBe('?view=conversation')
    await waitForView('对话')
  })

  it('opens the conversation named in the URL and keeps it after a reload', async () => {
    window.history.replaceState({}, '', '/?view=conversation&conversation=conv-1')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      if (url.includes('/conversations/conv-1')) return json({
        conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', created_at: null, updated_at: null,
        messages: [{ message_id: 'msg-1', conversation_id: 'conv-1', role: 'assistant', content: '（P1 桩回复）已收到你的消息。', stub: true, tool_name: null, tool_call_id: null, created_at: null }],
        messages_total: 1, messages_limit: 50, messages_offset: 0,
      })
      return json({ items: [{ conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', created_at: null, updated_at: null }], total: 1, limit: 20, offset: 0 })
    }))

    render(<App />)

    expect(window.location.search).toBe('?view=conversation&conversation=conv-1')
    expect(await screen.findByText('（P1 桩回复）已收到你的消息。')).toBeInTheDocument()
    expect(screen.getByText('占位回复', { selector: '.badge--warn' })).toBeInTheDocument()
  })

  it('falls back to the conversation page for an unknown view', async () => {
    window.history.replaceState({}, '', '/?view=unknown')

    render(<App />)

    await waitForView('对话')
  })

  // S1 第三款：通知点开 ⇒ 带会话与**该条审批**进入对话页（URL 可刷新、可分享）。
  it('opens the conversation with the approval deep link from a notification', async () => {
    const user = userEvent.setup()
    const rejected = {
      inbox_id: 'i-7', kind: 'run.approval_rejected', title: '你的任务运行被审批驳回',
      target_type: 'run', target_id: 'run-9', target_conversation_id: 'conv-1', target_approval_id: 'ap-1',
      created_at: '2026-09-11T02:00:00Z', read_at: '2026-09-11T03:00:00Z',
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes('/inbox?')) return json({ items: [rejected], unread_count: 0 })
      if (/\/conversations\/[^/?]+(\?|$)/.test(path)) {
        return json({
          conversation_id: 'conv-1', agent_key: 'agent-ops', title: '整理客户反馈', status: 'active', mode: 'craft',
          created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-11T02:00:00Z',
          messages: [], messages_total: 0, messages_limit: 50, messages_offset: 0,
        })
      }
      if (path.includes('/conversations?')) return json({ items: [], total: 0, limit: 20, offset: 0 })
      return json({ items: [], unread_count: 0 })
    }))

    window.history.replaceState({}, '', '/?view=inbox')
    render(<App />)
    await waitForView('通知')

    await user.click(await screen.findByRole('button', { name: '打开该会话的审批' }))

    // 落点由 App 统一拼装：会话 + 审批标识都进 URL（页面只负责定位，不改数据来源）。
    expect(window.location.search).toBe('?view=conversation&conversation=conv-1&approval=ap-1')
    await waitForView('对话')

    // 再点左栏「对话」时**只保留会话**：瞬态聚焦参数不留在 URL 上（避免刷新后反复高亮）。
    await user.click(navButton('对话'))
    expect(window.location.search).toBe('?view=conversation&conversation=conv-1')
  })

  // 常驻外壳（D19）：槽不卸载，但 URL 换视图后 route 里就没有会话/运行号了。
// 下面两条守护由此产生的两类真实缺陷（文案以「不丢上下文」与「不发空号请求」为准）。
  it('keeps the open conversation after jumping to another view and back', async () => {
    window.history.replaceState({}, '', '/?view=conversation&conversation=conv-1')
    stubApi()
    render(<App />)
    await waitForView('对话')
    expect(await screen.findByText('整理客户反馈')).toBeInTheDocument()

    // 应用内跳到别的视图（等同于运行详情里点「打开任务」/ 通知点开任务）
    window.history.pushState({}, '', '/?task=task-1')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitForView('任务')

    // 回来时仍在同一个会话（真源 §5：会话上下文不丢），且 URL 与页面口径一致
    fireEvent.click(navButton('对话'))
    expect(window.location.search).toBe('?view=conversation&conversation=conv-1')
    expect(await screen.findByText('整理客户反馈')).toBeInTheDocument()
  })

  it('never refetches with an empty run id after leaving the run detail', async () => {
    window.history.replaceState({}, '', '/?view=run&run=run-1')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      if (url.includes('/runs/run-1/metrics')) return json({
        run_id: 'run-1', task_id: 'task-1', proposal_id: null, runtime_key: 'mock', status: 'completed',
        step_count: 1, completed_step_count: 1, tool_calls: 1, successful_tools: 1, knowledge_hits: 0,
        latency_ms: 10, started_at: null, finished_at: null, finish_reason: 'run_completed',
      })
      if (url.includes('/runs/run-1/')) return json({ run_id: 'run-1', items: [] })
      if (url.includes('/tasks/task-1')) return json({ id: 'task-1', tenant_id: 'demo-tenant', project_id: null, created_by: 'admin', employee_key: 'content-writer', title: '整理本周选题', risk_level: 'low', budget: 0, idempotency_key: 'k', status: 'completed', audit_count: 0 })
      return json({ items: [], total: 0, limit: 20, offset: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await waitForView('运行详情')

    // 跳到另一个**不带运行号**的视图（通知页）——运行详情槽仍挂载（D19），但不能拿空号去打接口。
    window.history.pushState({}, '', '/?view=inbox')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitForView('通知')
    await new Promise((resolve) => setTimeout(resolve, 300))

    // 判定依据：槽虽仍挂载，但不得用**空运行号**去打 `/runs//metrics` 一类的接口（原先会打 4 个 404）。
    const emptyRunCalls = fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes('/runs//'))
    expect(emptyRunCalls).toEqual([])
  })

  it('opens the content workbench when only a task id is present', async () => {
    window.history.replaceState({}, '', '/?task=task-1')

    render(<App />)

    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())
  })

  it('updates the rendered view when the browser history changes', async () => {
    render(<App />)
    await waitForView('对话')

    window.history.pushState({}, '', '/?view=knowledge')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())

    // 「工作台」有显式入口（?view=home），不再依赖空查询串
    window.history.pushState({}, '', '/?view=home')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: /今天让数字员工做点什么/ })).toBeInTheDocument())

    // 空查询串 = 默认视图（对话）
    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitForView('对话')
  })

  it('switches the theme from the sidebar and persists the choice', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    // 默认跟随系统（测试环境无 matchMedia ⇒ 浅色）：底部按钮提示切到深色。
    await user.click(screen.getByRole('button', { name: '切换到深色外观' }))

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('workbench.theme')).toBe('dark')

    await user.click(screen.getByRole('button', { name: '切换到浅色外观' }))

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('workbench.theme')).toBe('light')
  })

  it('renders the run detail page for the run view', async () => {
    window.history.replaceState({}, '', '/?view=run&run=run-1')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      if (url.includes('/runs/run-1/metrics')) return json({ run_id: 'run-1', task_id: 'task-1', proposal_id: null, runtime_key: 'mock', status: 'running', step_count: 2, completed_step_count: 1, tool_calls: 1, successful_tools: 1, knowledge_hits: 0, latency_ms: 500, started_at: '2026-09-11T02:00:00Z', finished_at: null, finish_reason: null })
      if (url.includes('/runs/run-1/events')) return json([])
      if (url.includes('/runs/run-1/approvals')) return json({ items: [] })
      if (url.includes('/tasks/task-1')) return json({ id: 'task-1', tenant_id: 'demo-tenant', project_id: null, created_by: 'someone-else', employee_key: 'content-operator', title: '整理本周选题', risk_level: 'low', budget: 100, idempotency_key: 'k-1', status: 'running', audit_count: 1 })
      return json({})
    }))

    render(<App />)

    await waitForView('运行详情')
    // 任务标题不再是页内 h1（T4：顶栏标题唯一），而是「运行信息」里的任务名。
    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('运行信息')).toBeInTheDocument()
    expect(screen.getByText('交付')).toBeInTheDocument()
    expect(screen.getByText('事件时间线')).toBeInTheDocument()
  })

  // ---------------------------------------------------------------- 常驻外壳（D19）

  it('keeps the home draft after navigating away and back', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    // 「工作台」（原首页）不再是默认视图，先进去再输入
    await user.click(navButton('工作台'))
    await waitFor(() => expect(screen.getByRole('heading', { name: /今天让数字员工做点什么/ })).toBeInTheDocument())

    await user.type(screen.getByLabelText('想对数字员工说的话'), '整理本周客户反馈')
    await user.click(navButton('任务'))
    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())

    await user.click(navButton('工作台'))

    // 切页不再卸载已访问视图 → 草稿必须还在（这正是 D19 的目的）
    expect(await screen.findByLabelText('想对数字员工说的话')).toHaveValue('整理本周客户反馈')
  })

  it('keeps visited views mounted and only toggles visibility', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    await user.click(navButton('任务'))
    await waitFor(() => expect(screen.getByLabelText('内容主题')).toBeInTheDocument())
    await user.click(navButton('工作台'))
    await waitFor(() => expect(screen.getByRole('heading', { name: /今天让数字员工做点什么/ })).toBeInTheDocument())

    // 访问过的视图仍在 DOM 里（只是 hidden），当前视图不隐藏
    const hiddenTexts = Array.from(document.querySelectorAll('.view-slot[hidden]')).map((node) => node.textContent ?? '')
    expect(hiddenTexts.some((text) => text.includes('提交主题和素材'))).toBe(true)
    expect(document.querySelectorAll('.view-slot:not([hidden])')).toHaveLength(1)
  })

  it('does not mount views that were never visited', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      return json({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await waitForView('对话')

    const requested = () => fetchMock.mock.calls.map(([input]) => String(input))
    // 未访问过的视图不挂载、也就不发请求（否则启动瞬间会打出十几个页面的并发请求）
    expect(requested().some((url) => url.includes('/workforce/roster'))).toBe(false)
    expect(requested().some((url) => url.includes('/audits'))).toBe(false)

    await user.click(navButton('员工'))

    await waitFor(() =>
      expect(requested().some((url) => url.includes('/workforce/roster'))).toBe(true)
    )
  })
})