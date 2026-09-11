import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkforcePage } from './WorkforcePage'
import type { WorkforceRosterItem } from './types'

const operator: WorkforceRosterItem = { key: 'content-operator', role_knowledge_base_ids: ['company-general', 'editorial'], agent_knowledge_base_ids: [], task_count: 5 }
const writer: WorkforceRosterItem = { key: 'content-writer', role_knowledge_base_ids: [], agent_knowledge_base_ids: ['style-guide'], task_count: 0 }

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

// 外壳的通知角标会请求 /inbox，统一在 mock 里兜底，避免干扰用例断言。
// 路径用精确匹配（而非子串）：接口路径写错时必须让用例变红。
const ROSTER_PATH = '/workforce/roster'

function isRosterUrl(url: string): boolean {
  try {
    return new URL(url).pathname.endsWith(ROSTER_PATH)
  } catch {
    return false
  }
}

function makeFetch(handler: (url: string) => Response) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    return handler(url)
  })
}

function rosterUrls(fetchMock: ReturnType<typeof makeFetch>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0])).filter(isRosterUrl)
}

describe('WorkforcePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders identifiers with their knowledge scopes and task counts', async () => {
    const fetchMock = makeFetch(() => json({ items: [operator, writer], total: 2 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforcePage />)

    expect(await screen.findByText('content-operator')).toBeInTheDocument()
    expect(screen.getByText('content-writer')).toBeInTheDocument()
    expect(screen.getByText('company-general')).toBeInTheDocument()
    expect(screen.getByText('style-guide')).toBeInTheDocument()
    // 岗位未绑定与数字员工未绑定各出现一次。
    expect(screen.getAllByText('未绑定')).toHaveLength(2)
    expect(screen.getByText('5', { selector: 'td' })).toBeInTheDocument()
    expect(screen.getByText('0', { selector: 'td' })).toBeInTheDocument()
    expect(screen.getByText('2 项')).toBeInTheDocument()
    // 只读口径必须写在页面上（不做增删改）。
    expect(screen.getByText(/只读视图/)).toBeInTheDocument()
    // 请求打到只读清单接口。
    expect(rosterUrls(fetchMock)).toHaveLength(1)
  })

  it('no longer renders the hardcoded sidebar summary', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [operator], total: 1 })))

    render(<WorkforcePage />)
    await screen.findByText('content-operator')

    expect(screen.queryByText('本月授权概况')).not.toBeInTheDocument()
    expect(screen.queryByText(/已配置 18 个岗位/)).not.toBeInTheDocument()
  })

  it('reloads the roster when refresh is clicked', async () => {
    const fetchMock = makeFetch(() => json({ items: [operator], total: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforcePage />)
    await screen.findByText('content-operator')

    await userEvent.click(screen.getByRole('button', { name: '刷新' }))

    await waitFor(() => expect(rosterUrls(fetchMock)).toHaveLength(2))
  })

  it('shows the empty state when there is nothing recorded', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0 })))

    render(<WorkforcePage />)

    expect(await screen.findByText('暂无岗位或数字员工记录')).toBeInTheDocument()
  })

  it('shows an error and retries the same request', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      attempts += 1
      if (attempts === 1) return json({}, 500)
      return json({ items: [writer], total: 1 })
    }))

    render(<WorkforcePage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('岗位与数字员工加载失败')
    expect(screen.getByText('岗位与数字员工服务暂时不可用，请检查网络后重新尝试。')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('content-writer')).toBeInTheDocument()
  })

  it('shows a fixed permission message for 403 without offering a retry', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ detail: '只有超级管理员可以查看岗位与数字员工清单' }, 403)))

    render(<WorkforcePage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('当前账号没有查看岗位与数字员工的权限。')
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })
})
