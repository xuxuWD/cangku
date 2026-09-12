import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const json = (body: unknown): Response => ({ ok: true, json: async () => body }) as Response

function stubApi() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (path.includes('/workforce/agents')) return json({ items: [{ agent_key: 'agent-ops', name: '运营助理', description: '', role_key: 'content-operator', status: 'active', created_by: 'admin', created_at: null, updated_at: null }], total: 1, limit: 50, offset: 0 })
    if (path.includes('/content-tasks/')) return json({ task_id: 'task-1', run_id: 'run-1', status: 'reviewing', revision: 1, topic: '整理本周选题', sources: [], knowledge_references: [], draft: { draft_id: 'draft-1', title: '整理本周选题', summary: '摘要', body_markdown: '正文', image_suggestions: [], citations: [], template_version: 'mock-content-v1' } })
    if (path.includes('/content-tasks')) return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    if (path.includes('/workforce/roles')) return json({ items: [{ role_key: 'content-operator', name: '自媒体运营岗', description: '', status: 'active' }], total: 1, limit: 200, offset: 0 })
    if (path.includes('/workforce/candidates')) return json({ roles: [], agents: [] })
    if (path.includes('/conversations?')) return json({ items: [], total: 0, limit: 4, offset: 0 })
    if (path.includes('/commercial/usage')) return json({ tenant_id: 'demo-tenant', units: 12, cost_cents: 340 })
    return json(path.includes('/audits') ? [] : { binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: ['company-general'] })
  }))
}

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
    window.localStorage.clear()
    stubApi()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the home entry point by default', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: '数字员工，我帮你' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始对话' })).toBeInTheDocument()
  })

  it('navigates to the content workbench from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('内容工作台', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=workbench')
    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
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
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('知识权限管理', { selector: '.nav-item' }))

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
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('员工与岗位', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=workforce')
    await waitFor(() => expect(screen.getByRole('heading', { name: '员工与岗位' })).toBeInTheDocument())
  })

  it('navigates to the workforce settings page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('数字员工设置', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=workforceSettings')
    await waitFor(() => expect(screen.getByRole('heading', { name: '数字员工设置' })).toBeInTheDocument())
  })

  it('navigates to the usage and billing page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('用量与费用', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=billing')
    await waitFor(() => expect(screen.getByRole('heading', { name: '用量与费用' })).toBeInTheDocument())
  })

  it('navigates to the conversation page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    await user.click(screen.getByText('对话', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=conversation')
    await waitFor(() => expect(screen.getByRole('heading', { name: '对话' })).toBeInTheDocument())
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
    expect(screen.getByText('桩回复', { selector: '.status-badge' })).toBeInTheDocument()
  })

  it('falls back to the home page for an unknown view', async () => {
    window.history.replaceState({}, '', '/?view=unknown')

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '数字员工，我帮你' })).toBeInTheDocument())
  })

  it('opens the content workbench when only a task id is present', async () => {
    window.history.replaceState({}, '', '/?task=task-1')

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
  })

  it('updates the rendered view when the browser history changes', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    window.history.pushState({}, '', '/?view=knowledge')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())

    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '数字员工，我帮你' })).toBeInTheDocument())
  })

  it('switches the theme from the sidebar and persists the choice', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: '数字员工，我帮你' })

    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: '深色' }))

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('workbench.theme')).toBe('dark')
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: '浅色' }))

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

    expect(await screen.findByRole('heading', { name: '整理本周选题' })).toBeInTheDocument()
    expect(screen.getByText('运行概览')).toBeInTheDocument()
  })
})
