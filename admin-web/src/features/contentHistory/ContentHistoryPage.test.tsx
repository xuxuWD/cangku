import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ContentHistoryPage } from './ContentHistoryPage'

describe('ContentHistoryPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists summaries and reloads when the status filter changes', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      requests.push(path)
      const failed = path.includes('status=failed')
      return {
        ok: true,
        json: async () => ({
          items: failed ? [{ task_id: 'task-2', topic: '失败选题', status: 'failed', created_by: 'employee', created_at: '2026-09-07T12:00:00Z', updated_at: '2026-09-07T12:04:00Z', run_id: 'run-2' }] : [{ task_id: 'task-1', topic: '企业知识库', status: 'reviewing', created_by: 'employee', created_at: '2026-09-07T11:00:00Z', updated_at: '2026-09-07T11:04:00Z', run_id: 'run-1' }],
          page: 1,
          page_size: 20,
          total: 1,
          has_next: false,
        }),
      } as Response
    }))

    render(<ContentHistoryPage onOpenTask={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: '历史草稿' })).toBeInTheDocument()
    expect(screen.getByText('企业知识库')).toBeInTheDocument()
    expect(screen.getByText('待自检', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('共 1 条')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('状态筛选'), 'failed')
    await waitFor(() => expect(requests.some((path) => path.includes('status=failed'))).toBe(true))
    expect(await screen.findByText('失败选题')).toBeInTheDocument()
    expect(screen.getByText('重新生成')).toBeInTheDocument()
  })

  it('shows an error when the history request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 }) as Response))
    render(<ContentHistoryPage onOpenTask={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('历史草稿加载失败')
  })
})
