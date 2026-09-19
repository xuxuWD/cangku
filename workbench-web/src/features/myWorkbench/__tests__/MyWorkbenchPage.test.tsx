import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MyWorkbenchPage } from '../MyWorkbenchPage'
import { AppShell } from '../../../app/AppShell'
import { SAMPLE_DATA_BADGE, setServiceMode } from '../services/myWorkbenchService'
import { TOKEN_STORAGE_KEY } from '../../../app/session'
import { renderWithProviders, signInAs, signOutForTest } from '../../../test/renderWithProviders'

/**
 * 最小 `fetch` 桩：只实现请求层用到的三样（`status` / `ok` / `text`），不发真实网络请求。
 * 返回它收到的 `(url, init)`，供"请求路径与参数逐字正确"的断言使用。
 */
function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return calls
}

const INBOX_ITEM = {
  inbox_id: 'inbox-0001',
  kind: 'task.approved',
  title: '任务已通过：整理客户反馈',
  target_type: 'task',
  target_id: 'task-0002',
  target_conversation_id: null,
  target_approval_id: null,
  created_at: '2026-09-18T17:05:00+08:00',
  read_at: null,
}

const APPROVAL_ITEM = {
  kind: 'task_approval',
  target_id: 'approval-0001',
  title: '待审批：整理本周选题',
  requested_by: null,
  created_at: '2026-09-19T09:20:00+08:00',
  detail: {},
}

describe('MyWorkbenchPage', () => {
  beforeEach(() => {
    signInAs('employee')
  })

  afterEach(() => {
    setServiceMode('mock')
    vi.unstubAllGlobals()
    signOutForTest()
  })

  it('四块齐备，且有统一的"示例数据（未接后端）"标识（页面 + 两块样例卡片）', async () => {
    renderWithProviders(<MyWorkbenchPage />)

    expect(screen.getByRole('heading', { level: 2, name: '我的工作台' })).toBeInTheDocument()
    for (const title of ['待办', '日程', '最近使用', '快捷入口']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }

    expect(await screen.findByText('待审批：整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('示例会话：季度内容排期')).toBeInTheDocument()
    // 页面顶部 Alert + 待办卡片 + 最近使用卡片（取数落地后才可能出现）
    expect((await screen.findAllByText(SAMPLE_DATA_BADGE)).length).toBeGreaterThanOrEqual(3)
  })

  it('日程块：文案含"尚未接入"，且**卡片内没有任何日期/条目**', async () => {
    renderWithProviders(<MyWorkbenchPage />)

    // 先等日程块取数落地，避免在加载态上做断言（加载态本来就没有"尚未接入"）
    await screen.findByText(/后端暂无日程实体/)
    const card = screen.getByText('日程').closest('.ant-pro-card') as HTMLElement
    expect(within(card).getByText(/尚未接入/)).toBeInTheDocument()
    expect(within(card).getByText(/后端暂无日程实体/)).toBeInTheDocument()
    expect(within(card).queryByText(/\d{4}-\d{2}-\d{2}/)).not.toBeInTheDocument()
    expect(within(card).queryByText(/\d{1,2}:\d{2}/)).not.toBeInTheDocument()

    // 待办/最近使用确实有时间（证明上面的"日程无日期"不是因为整页没有时间）
    expect(await screen.findByText('2026-09-19 09:20')).toBeInTheDocument()
  })

  it('加载中不显示失败文案：加载态用统一加载文案', async () => {
    renderWithProviders(<MyWorkbenchPage />)

    // 首屏同步渲染时四块都处于加载态
    expect(screen.getAllByText('正在加载，请稍候…').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('待办列表加载失败，请稍后重试。')).not.toBeInTheDocument()

    await screen.findByText('待审批：整理本周选题')
  })

  it('http 模式：待办来自真接口（未读通知 + 待审批），请求路径与参数逐字正确', async () => {
    setServiceMode('http')
    const calls = stubFetch({
      '/api/v1/inbox': { body: { items: [INBOX_ITEM], unread_count: 1 } },
      '/api/v1/approvals/pending': { body: { items: [APPROVAL_ITEM], counts: { task_approval: 1 } } },
    })

    renderWithProviders(<MyWorkbenchPage />)

    expect(await screen.findByText('待审批：整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('任务已通过：整理客户反馈')).toBeInTheDocument()
    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/inbox?unread_only=true&limit=50',
      '/api/v1/approvals/pending?limit=50',
    ])
    // 真实数据不得被标成样例：页面上不出现"示例数据（未接后端）"
    expect(screen.queryByText(SAMPLE_DATA_BADGE)).not.toBeInTheDocument()
  })

  it('http 模式：最近使用 / 日程如实显示"未接入"，不是"加载失败"、也不是空列表', async () => {
    setServiceMode('http')
    stubFetch({
      '/api/v1/inbox': { body: { items: [], unread_count: 0 } },
      '/api/v1/approvals/pending': { body: { items: [], counts: {} } },
    })

    renderWithProviders(<MyWorkbenchPage />)

    const recentCard = (await screen.findByText(/最近使用尚未接入/)).closest('.ant-pro-card') as HTMLElement
    expect(within(recentCard).getByText(/最近使用尚未接入/)).toBeInTheDocument()
    expect(within(recentCard).queryByText('最近使用加载失败，请稍后重试。')).not.toBeInTheDocument()
    expect(within(recentCard).queryByText('暂无最近使用记录。')).not.toBeInTheDocument()

    const scheduleCard = screen.getByText('日程').closest('.ant-pro-card') as HTMLElement
    expect(within(scheduleCard).getByText(/后端暂无日程实体/)).toBeInTheDocument()
    // 待办真的为空时给的是空态文案（与"未接入"明确区分）
    expect(await screen.findByText('当前没有待办（待审批与未读通知都为空）。')).toBeInTheDocument()
  })

  it('标记已读：调真端点 POST /api/v1/inbox/{id}/read；审批类待办按钮禁用并说明原因', async () => {
    setServiceMode('http')
    const calls = stubFetch({
      '/api/v1/inbox': { body: { items: [INBOX_ITEM], unread_count: 1 } },
      '/api/v1/approvals/pending': { body: { items: [APPROVAL_ITEM], counts: {} } },
    })

    renderWithProviders(<MyWorkbenchPage />)
    await screen.findByText('任务已通过：整理客户反馈')

    // 审批类待办没有"已读"概念：禁用 + 给原因（不静默隐藏按钮）
    const approvalRow = screen.getByText('待审批：整理本周选题').closest('tr') as HTMLElement
    const approvalButton = within(approvalRow).getByRole('button', { name: /标记已读/ })
    expect(approvalButton).toBeDisabled()
    expect(approvalButton).toHaveAttribute('title', '审批类待办没有"已读"状态')

    const notificationRow = screen.getByText('任务已通过：整理客户反馈').closest('tr') as HTMLElement
    await userEvent.click(within(notificationRow).getByRole('button', { name: /标记已读/ }))

    expect(await screen.findByText('已标记为已读。')).toBeInTheDocument()
    const readCall = calls.find((call) => call.url.includes('/read'))
    expect(readCall?.url).toBe('/api/v1/inbox/inbox-0001/read')
    expect(readCall?.init.method).toBe('POST')
    // 已读后按同一口径重新取数（未读通知口径变了，不本地"猜"结果）
    expect(calls.filter((call) => call.url.startsWith('/api/v1/inbox?')).length).toBeGreaterThanOrEqual(2)
  })

  it('401：清本地令牌并回到登录页（不假装还能用）', async () => {
    setServiceMode('http')
    stubFetch({
      '/api/v1/inbox': { status: 401, body: { detail: '未认证' } },
      '/api/v1/approvals/pending': { status: 401, body: { detail: '未认证' } },
    })
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('test-token')

    renderWithProviders(<AppShell />)

    expect(await screen.findByText('账号（手机号）')).toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('网络失败：进入 error 态并给"服务不可达"文案，不假装空', async () => {
    setServiceMode('http')
    vi.stubGlobal(
      'fetch',
      (async () => {
        throw new TypeError('Failed to fetch')
      }) as unknown as typeof fetch,
    )

    renderWithProviders(<MyWorkbenchPage />)

    expect(await screen.findByText('服务不可达：请检查网络后重试。')).toBeInTheDocument()
    expect(screen.queryByText('当前没有待办（待审批与未读通知都为空）。')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('员工的管理类快捷入口禁用且有原因（不静默隐藏）', async () => {
    renderWithProviders(<MyWorkbenchPage />)

    const disabled = await screen.findByRole('button', { name: '数字员工配置' })
    expect(disabled).toBeDisabled()
    expect(screen.getByText(/需要「权限配置」权限/)).toBeInTheDocument()
  })

  it('壳里选中"我的工作台"即渲染本页（导航可到达）', async () => {
    renderWithProviders(<AppShell />)

    expect(screen.getByRole('heading', { level: 1, name: '我的工作台' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '我的工作台' })).toBeInTheDocument()
    expect(await screen.findByText('待审批：整理本周选题')).toBeInTheDocument()

    // 切走再切回，本页仍然可渲染
    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))
    expect(screen.queryByText(SAMPLE_DATA_BADGE)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('menuitem', { name: /我的工作台/ }))
    expect(await screen.findByText('待审批：整理本周选题')).toBeInTheDocument()
  })
})