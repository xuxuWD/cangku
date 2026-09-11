import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomePage } from './HomePage'

const json = (body: unknown): Response => ({ ok: true, json: async () => body }) as Response
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

describe('HomePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('creates a task from the hero composer', async () => {
    const calls = stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      if (url.includes('/content-tasks')) return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
      return json({ id: 'task-1', title: '整理客户反馈', status: 'queued', risk_level: 'low' })
    })
    const user = userEvent.setup()
    render(<HomePage onOpenTask={() => {}} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.type(screen.getByLabelText('任务描述'), '整理客户反馈')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('任务已创建：task-1', { selector: '.toast span' })).toBeInTheDocument()

    const posted = calls.find((call) => call.url.endsWith('/tasks'))
    expect(posted?.init?.method).toBe('POST')
    expect(JSON.parse(String(posted?.init?.body))).toMatchObject({
      title: '整理客户反馈',
      employee_key: 'agent-ops',
      risk_level: 'low',
      budget: 0,
    })
  })

  it('reports a high-risk task as pending approval', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      if (url.includes('/content-tasks')) return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
      return json({ id: 'task-9', title: '接入新渠道', status: 'pending_approval', risk_level: 'high' })
    })
    const user = userEvent.setup()
    render(<HomePage onOpenTask={() => {}} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.type(screen.getByLabelText('任务描述'), '接入新渠道')
    await user.selectOptions(screen.getByLabelText('风险等级'), 'high')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('任务已创建并提交审批：task-9', { selector: '.toast span' })).toBeInTheDocument()
  })

  it('cannot submit without a description', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    })
    render(<HomePage onOpenTask={() => {}} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    expect(screen.getByRole('button', { name: '创建任务' })).toBeDisabled()
  })

  it('points at the directory when no digital employee is enabled', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [{ ...AGENT, status: 'disabled' }], total: 1, limit: 50, offset: 0 })
      return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    })
    const onNavigate = vi.fn()
    render(<HomePage onOpenTask={() => {}} onNavigate={onNavigate} />)

    expect(await screen.findByText('还没有启用中的数字员工')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: '去创建' }))
    expect(onNavigate).toHaveBeenCalledWith('workforceSettings')
  })

  it('shows a retryable error when the employee list fails', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return failure(500)
      return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    })
    render(<HomePage onOpenTask={() => {}} />)

    expect(await screen.findByText('数字员工读取失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
  })

  it('surfaces a rejected task creation without inventing a success', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      if (url.includes('/content-tasks')) return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
      return failure(403)
    })
    const user = userEvent.setup()
    render(<HomePage onOpenTask={() => {}} />)

    await screen.findByRole('heading', { name: '数字员工，我帮你' })
    await user.type(screen.getByLabelText('任务描述'), '整理客户反馈')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('任务创建失败')).toBeInTheDocument()
    expect(screen.queryByText(/任务已创建/)).not.toBeInTheDocument()
  })

  it('opens a recent draft', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      return json({
        items: [{ task_id: 'task-7', topic: '数字员工如何提升交付效率', status: 'reviewing', run_id: 'run-7', created_by: 'admin', created_at: '2026-09-11T02:00:00Z', updated_at: '2026-09-11T02:00:00Z' }],
        page: 1,
        page_size: 4,
        total: 1,
        has_next: false,
      })
    })
    const onOpenTask = vi.fn()
    const user = userEvent.setup()
    render(<HomePage onOpenTask={onOpenTask} />)

    await user.click(await screen.findByRole('button', { name: /数字员工如何提升交付效率/ }))
    expect(onOpenTask).toHaveBeenCalledWith('task-7')
  })

  it('shows the empty state when there is no draft yet', async () => {
    stub((url) => {
      if (url.includes('/workforce/agents')) return json({ items: [AGENT], total: 1, limit: 50, offset: 0 })
      return json({ items: [], page: 1, page_size: 4, total: 0, has_next: false })
    })
    render(<HomePage onOpenTask={() => {}} />)

    await waitFor(() => expect(screen.getByText('还没有内容草稿')).toBeInTheDocument())
  })
})
