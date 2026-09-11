import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      return { ok: true, json: async () => path.includes('/audits') ? [] : { binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: ['company-general'] } } as Response
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the Chinese content workbench entry point', () => {
    render(<App />)
    return waitFor(() => {
      expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument()
      expect(screen.getByText('素材输入')).toBeInTheDocument()
      expect(screen.getByText('草稿预览')).toBeInTheDocument()
    })
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

    await user.click(screen.getByText('知识权限管理', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=knowledge')
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())
  })

  it('falls back to the content workbench for an unknown view', async () => {
    window.history.replaceState({}, '', '/?view=unknown')

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
  })

  it('updates the rendered view when the browser history changes', async () => {
    render(<App />)

    window.history.pushState({}, '', '/?view=knowledge')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())

    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
  })

  it('renders the run detail page for the run view', async () => {
    window.history.replaceState({}, '', '/?view=run&run=run-1')
    const json = (body: unknown): Response => ({ ok: true, json: async () => body }) as Response
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
    expect(screen.getByText('运行详情')).toBeInTheDocument()
  })
})
