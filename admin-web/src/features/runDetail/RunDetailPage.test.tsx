import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RunDetailPage } from './RunDetailPage'

const metrics = { run_id: 'run-1', task_id: 'task-1', proposal_id: null, runtime_key: 'mock', status: 'running', step_count: 3, completed_step_count: 1, tool_calls: 2, successful_tools: 1, knowledge_hits: 0, latency_ms: 1200, started_at: '2026-09-11T02:00:00Z', finished_at: null, finish_reason: null }

function makeTask(createdBy: string) {
  return { id: 'task-1', tenant_id: 'demo-tenant', project_id: null, created_by: createdBy, employee_key: 'content-operator', title: '整理本周选题', risk_level: 'low', budget: 100, idempotency_key: 'k-1', status: 'running', audit_count: 1 }
}

const events = [
  { cursor: 'run-1:1', run_id: 'run-1', sequence: 1, event_type: 'plan.created', payload: { status: 'pending_review' } },
  { cursor: 'run-1:2', run_id: 'run-1', sequence: 2, event_type: 'tool.call', payload: { step_id: 's-1', tool: 'search' } },
]

const approvals = [{ approval_id: 'a-1', step_id: 's-1', tool: 'search', status: 'pending' }]

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

interface Overrides {
  metrics?: () => Response
  task?: () => Response
  events?: () => Response
  approvals?: () => Response
  decision?: () => Response
}

function createFetch(createdBy = 'someone-else', overrides: Overrides = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/inbox?')) return jsonResponse({ items: [], unread_count: 0 })
    if (init?.method === 'POST' && url.includes('/approval')) return overrides.decision ? overrides.decision() : jsonResponse({ run_id: 'run-1', approval_id: 'a-1', status: 'approved', run_status: 'running' })
    if (url.includes('/runs/run-1/metrics')) return overrides.metrics ? overrides.metrics() : jsonResponse(metrics)
    if (url.includes('/runs/run-1/events')) return overrides.events ? overrides.events() : jsonResponse(events)
    if (url.includes('/runs/run-1/approvals')) return overrides.approvals ? overrides.approvals() : jsonResponse({ items: approvals })
    if (url.includes('/tasks/task-1')) return overrides.task ? overrides.task() : jsonResponse(makeTask(createdBy))
    return jsonResponse({})
  })
}

describe('RunDetailPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads and displays metrics, approvals and events', async () => {
    vi.stubGlobal('fetch', createFetch())

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(screen.getByText('1200 ms')).toBeInTheDocument()
    expect(screen.getByText('运行中', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('步骤 s-1 / 工具 search')).toBeInTheDocument()
    expect(screen.getByText('待审批', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('#1 计划已创建')).toBeInTheDocument()
    expect(screen.getByText('#2 工具调用')).toBeInTheDocument()
  })

  it('hides the decision buttons and explains when the viewer is the initiator', async () => {
    vi.stubGlobal('fetch', createFetch('admin'))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('发起人不能审批自己发起的运行')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '通过' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '驳回' })).not.toBeInTheDocument()
  })

  it('keeps the buttons for non-initiators and reloads after a decision', async () => {
    const fetchMock = createFetch('someone-else')
    vi.stubGlobal('fetch', fetchMock)

    render(<RunDetailPage runId="run-1" />)

    await screen.findByText('步骤 s-1 / 工具 search')
    const approvalsCalls = () => fetchMock.mock.calls.filter((call) => String(call[0]).includes('/runs/run-1/approvals') && !(call[1] as RequestInit | undefined)?.method).length
    expect(approvalsCalls()).toBe(1)

    await userEvent.click(screen.getByRole('button', { name: '通过' }))

    expect(await screen.findByText('已通过', { selector: '.toast span' })).toBeInTheDocument()
    await waitFor(() => expect(approvalsCalls()).toBeGreaterThanOrEqual(2))
  })

  it('shows the backend detail when a decision is denied', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { decision: () => jsonResponse({ detail: '发起人不能审批自己发起的运行' }, 403) }))

    render(<RunDetailPage runId="run-1" />)

    await screen.findByText('步骤 s-1 / 工具 search')
    await userEvent.click(screen.getByRole('button', { name: '通过' }))

    expect(await screen.findByText('发起人不能审批自己发起的运行', { selector: '.toast span' })).toBeInTheDocument()
  })

  it('keeps metrics and approvals when the events region fails', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { events: () => jsonResponse({}, 500) }))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(screen.getByText('步骤 s-1 / 工具 search')).toBeInTheDocument()
    expect(await screen.findByText('事件加载失败')).toBeInTheDocument()
  })

  it('shows the empty states for approvals and events', async () => {
    vi.stubGlobal('fetch', createFetch('someone-else', { approvals: () => jsonResponse({ items: [] }), events: () => jsonResponse([]) }))

    render(<RunDetailPage runId="run-1" />)

    expect(await screen.findByText('该运行没有审批项')).toBeInTheDocument()
    expect(screen.getByText('暂无事件')).toBeInTheDocument()
  })
})
