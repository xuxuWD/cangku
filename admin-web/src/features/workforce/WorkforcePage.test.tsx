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
    // S5：员工页横幅与首页指标卡同源 ⇒ 本页也会请求「待我审批」聚合；
    // 默认给空待办（不影响清单用例），需要验证横幅的用例再单独覆写这一支。
    if (url.includes('/approvals/pending')) {
      return json({ items: [], counts: { task_approval: 0, plan_proposal: 0, account_registration: 0, run_approval: 0, total: 0 } })
    }
    return handler(url)
  })
}

function rosterUrls(fetchMock: ReturnType<typeof makeFetch>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0])).filter(isRosterUrl)
}

// 统计条按「标签 → 所在 .metric 卡片」定位，避免同名数字串到别处。
function metric(label: string): HTMLElement {
  return screen.getByText(label).parentElement as HTMLElement
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
    // 统计条：项数取服务端 `total`；两个「已绑定」按本页数据现算（operator 有岗位范围、writer 有数字员工范围）。
    expect(metric('名册项数')).toHaveTextContent('2')
    expect(metric('已绑定岗位知识范围')).toHaveTextContent('1')
    expect(metric('已绑定数字员工知识范围')).toHaveTextContent('1')
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

  it('offers real actions from the empty state', async () => {
    const onNavigate = vi.fn()
    const fetchMock = makeFetch(() => json({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforcePage onNavigate={onNavigate} />)
    await screen.findByText('暂无岗位或数字员工记录')

    const settings = screen.getAllByRole('button', { name: '数字员工设置' })
    await userEvent.click(settings[settings.length - 1])

    expect(onNavigate).toHaveBeenCalledWith('workforceSettings')

    await userEvent.click(screen.getAllByRole('button', { name: '刷新' })[0])
    await waitFor(() => expect(rosterUrls(fetchMock)).toHaveLength(2))
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

  // S5：横幅与工作台首页指标卡**同源**（同一个聚合端点）；有落点的待办可直接打开。
  it('shows the 待我审批 banner from the aggregate endpoint and opens the run item', async () => {
    const onOpenRun = vi.fn()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
      if (url.includes('/approvals/pending')) {
        return json({
          items: [
            { kind: 'run_approval', target_id: 'a-1', title: '整理选题', requested_by: 'u-1', created_at: '2026-09-18T00:00:00+00:00', detail: { run_id: 'run-7', approval_id: 'a-1' } },
            { kind: 'plan_proposal', target_id: 'p-1', title: '三步计划', requested_by: 'u-2', created_at: '2026-09-18T00:00:00+00:00', detail: { step_count: 3 } },
          ],
          counts: { task_approval: 0, plan_proposal: 1, account_registration: 0, run_approval: 1, total: 2 },
        })
      }
      return json({ items: [operator], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforcePage onOpenRun={onOpenRun} />)

    const banner = await screen.findByRole('region', { name: '待我审批' })
    expect(banner).toHaveTextContent('2 项')
    expect(banner).toHaveTextContent('运行内审批')
    // 有落点的一项给真实按钮，点击直达运行详情。
    await userEvent.click(screen.getByRole('button', { name: '打开运行去审批' }))
    expect(onOpenRun).toHaveBeenCalledWith('run-7')
    // 没有处理入口的类型**不给按钮**、只给如实说明（不假装可点）。
    expect(screen.queryByRole('button', { name: /计划提案/ })).not.toBeInTheDocument()
    expect(banner).toHaveTextContent('计划提案的处理入口尚未交付')
  })
})
