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

    // 页内不再有 h1（标题由顶栏承担），改为断言主区与副标题，列表事实照旧。
    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByText(/展示当前账号有权限查看的任务动态/)).toBeInTheDocument()
    expect(screen.getByText('排队中', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText(/content-operator/)).toBeInTheDocument()
  })

  it('shows an empty state when there are no dynamics', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByText('暂无协同动态')).toBeInTheDocument()
    // 空态给的是真实动作（重新拉取），不是死胡同。
    expect(screen.getAllByRole('button', { name: '刷新' }).length).toBeGreaterThan(0)
  })

  it('shows an error when the dynamics request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('协同动态加载失败')
    // 真故障可重试。
    expect(screen.getByRole('button', { name: '重新尝试' })).toBeInTheDocument()
  })

  it('shows a fixed permission message for 403 without a retry', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403 }) as Response))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    expect(await screen.findByText(/当前账号没有查看协同动态的权限/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })

  it('retries and reloads the list after a server error', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      attempts += 1
      if (attempts === 1) return { ok: false, status: 500 } as Response
      return { ok: true, json: async () => [sample] } as Response
    }))

    render(<CollaborationDynamicsPage onOpenTask={vi.fn()} />)

    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('整理本周选题')).toBeInTheDocument()
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