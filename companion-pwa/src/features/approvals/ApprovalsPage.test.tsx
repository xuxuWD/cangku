import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { saveSession, type Session } from '../../app/session'
import { ApprovalsPage } from './ApprovalsPage'
import type { PendingApproval } from './types'

const session: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'super_admin',
  expiresAt: Date.now() + 100_000,
}

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const zeroCounts = { task_approval: 0, plan_proposal: 0, account_registration: 0, run_approval: 0, total: 0 }

const taskItem: PendingApproval = {
  kind: 'task_approval',
  target_id: 'task-1',
  title: '待审批任务',
  requested_by: 'u-1',
  created_at: '2026-01-01T00:00:00Z',
  detail: { risk_level: 'high', employee_key: 'content-operator' },
}

function ok(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

describe('ApprovalsPage', () => {
  beforeEach(() => {
    localStorage.clear()
    saveSession(session)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders pending items and posts the approval to the task endpoint', async () => {
    const fetchMock = vi.fn<FetchMock>(async (input) => {
      const url = String(input)
      if (url.includes('/approvals/pending')) return ok({ items: [taskItem], counts: { ...zeroCounts, task_approval: 1, total: 1 } })
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ApprovalsPage />)

    expect(await screen.findByText('待审批任务')).toBeInTheDocument()
    expect(screen.getByText('任务审批')).toBeInTheDocument()
    expect(screen.getByText('请求人：u-1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '通过' }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/tasks/task-1/approve') && call[1]?.method === 'POST')).toBe(true)
    )
  })

  it('shows the empty state when there is nothing pending', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ items: [], counts: zeroCounts })))

    render(<ApprovalsPage />)

    expect(await screen.findByText('暂无待办')).toBeInTheDocument()
  })

  it('shows an alert and retries the request', async () => {
    let attempt = 0
    const fetchMock = vi.fn<FetchMock>(async () => {
      attempt += 1
      if (attempt === 1) return { ok: false, status: 500, json: async () => ({ detail: '后端开小差' }) } as unknown as Response
      return ok({ items: [], counts: zeroCounts })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ApprovalsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('后端开小差')
    await user.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('暂无待办')).toBeInTheDocument()
  })

  it('renders different actions per kind: tasks cannot be rejected', async () => {
    const proposal: PendingApproval = { kind: 'plan_proposal', target_id: 'p-1', title: '季度计划提案', requested_by: 'u-2', created_at: '2026-01-02T00:00:00Z', detail: { step_count: 3 } }
    const registration: PendingApproval = { kind: 'account_registration', target_id: 'a-1', title: '138****0001', requested_by: null, created_at: '2026-01-03T00:00:00Z', detail: { position: '内容运营' } }
    vi.stubGlobal(
      'fetch',
      vi.fn<FetchMock>(async () =>
        ok({
          items: [taskItem, proposal, registration],
          counts: { task_approval: 1, plan_proposal: 1, account_registration: 1, run_approval: 0, total: 3 },
        })
      )
    )

    render(<ApprovalsPage />)

    const taskCard = (await screen.findByText('待审批任务')).closest('li') as HTMLElement
    expect(within(taskCard).getByRole('button', { name: '通过' })).toBeInTheDocument()
    expect(within(taskCard).queryByRole('button', { name: '驳回' })).toBeNull()

    const proposalCard = screen.getByText('季度计划提案').closest('li') as HTMLElement
    expect(within(proposalCard).getByRole('button', { name: '通过' })).toBeInTheDocument()
    expect(within(proposalCard).getByRole('button', { name: '驳回' })).toBeInTheDocument()

    const registrationCard = screen.getByText('138****0001').closest('li') as HTMLElement
    expect(within(registrationCard).getByRole('button', { name: '通过' })).toBeInTheDocument()
    expect(within(registrationCard).getByRole('button', { name: '驳回' })).toBeInTheDocument()
    // 只有账号注册需要审批人指定角色。
    expect(within(registrationCard).getByLabelText('分配角色')).toBeInTheDocument()
    expect(within(proposalCard).queryByLabelText('分配角色')).toBeNull()
  })

  it('approves an account registration with the role chosen by the approver', async () => {
    const registration: PendingApproval = { kind: 'account_registration', target_id: 'a-7', title: '138****0007', requested_by: null, created_at: '2026-01-03T00:00:00Z', detail: { position: '内容运营' } }
    const fetchMock = vi.fn<FetchMock>(async (input) => {
      const url = String(input)
      if (url.includes('/approvals/pending')) return ok({ items: [registration], counts: { ...zeroCounts, account_registration: 1, total: 1 } })
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ApprovalsPage />)

    const card = (await screen.findByText('138****0007')).closest('li') as HTMLElement
    expect(within(card).getByLabelText('分配角色')).toHaveValue('employee')

    await user.selectOptions(within(card).getByLabelText('分配角色'), 'ceo')
    await user.click(within(card).getByRole('button', { name: '通过' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((entry) => String(entry[0]).includes('/auth/registrations/a-7/approval'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ role: 'ceo', tenant_id: 'tenant-1' })
    })
  })

  it('renders a run approval card with approve and reject actions and posts to the run decision endpoint', async () => {
    const runItem: PendingApproval = {
      kind: 'run_approval',
      target_id: 'run-9',
      title: '发布内容',
      requested_by: 'u-2',
      created_at: '2026-01-04T00:00:00Z',
      detail: { run_id: 'run-9', approval_id: 's1', step_id: null, tool: null },
    }
    const fetchMock = vi.fn<FetchMock>(async (input) => {
      const url = String(input)
      if (url.includes('/approvals/pending')) return ok({ items: [runItem], counts: { ...zeroCounts, run_approval: 1, total: 1 } })
      return ok({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ApprovalsPage />)

    const card = (await screen.findByText('发布内容')).closest('li') as HTMLElement
    expect(screen.getByText('运行审批')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: '通过' })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: '驳回' })).toBeInTheDocument()
    // 运行审批不需要角色选择器（只有账号注册需要）。
    expect(within(card).queryByLabelText('分配角色')).toBeNull()

    await user.click(within(card).getByRole('button', { name: '通过' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((entry) => String(entry[0]).includes('/runs/run-9/approvals/s1/approval'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ approved: true })
      expect(String(call?.[0])).not.toContain('/auth/registrations/')
    })
  })
})
