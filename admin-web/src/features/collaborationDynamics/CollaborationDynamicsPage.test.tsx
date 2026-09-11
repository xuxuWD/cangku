import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CollaborationDynamicsPage } from './CollaborationDynamicsPage'

const sample = {
  event_id: 'evt-1',
  aggregate_id: 'task-1',
  action: 'task.created',
  title: '整理本周选题',
  employee_key: 'content-operator',
  status: 'queued',
  tenant_id: 't-1',
  project_id: 'proj-1',
  created_by: 'employee',
  occurred_at: '2026-09-07T11:00:00Z',
}

describe('CollaborationDynamicsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists collaboration dynamics with status and employee', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [sample] }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: '协同动态' })).toBeInTheDocument()
    expect(screen.getByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('排队中', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText(/content-operator/)).toBeInTheDocument()
  })

  it('shows an empty state when there are no dynamics', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByText('暂无协同动态')).toBeInTheDocument()
  })

  it('shows an error when the dynamics request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('协同动态加载失败')
  })

  it('opens the related task when 查看任务 is clicked', async () => {
    const onOpenTask = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [sample] }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={onOpenTask} />)

    await screen.findByText('整理本周选题')
    await userEvent.click(screen.getByRole('button', { name: '查看任务' }))

    expect(onOpenTask).toHaveBeenCalledWith('task-1')
  })
})
