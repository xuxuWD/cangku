/**
 * 「通知（收件箱）」页面用例（阶段 1 合并移植）。
 *
 * 覆盖口径：
 *  - 样例模式与「已接入真实数据」**互斥**显示，不含糊；
 *  - 列表渲染：标题 / 类型标签 / 未读·已读状态；
 *  - 「未读」是**纯前端筛选**：切档后已读行消失，**不发新请求**；
 *  - **两种空态必须分开**："筛选没命中" ≠ "一条通知都没有"（文案不同，不得混用）；
 *  - 写侧：标已读走服务端，成功后**重新取数**（以服务端回读为准，不拼乐观结果）；
 *  - 目标落点分**两档**且都要说清：右栏能看摘要（2026-09-23 换壳后可用了）、完整页面仍未合并；
 *  - 四态：`403` ⇒ 无权限态，且文案与"加载失败"不同。
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { InboxPage } from '../InboxPage'
import { resetMockInbox, setServiceMode } from '../services/inboxService'
import { resetShellStore, useShellStore } from '../../../app/shellStore'

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
  return { calls }
}

const ITEM = (over: Partial<Record<string, unknown>> = {}) => ({
  inbox_id: 'inbox-1',
  kind: 'task.approved',
  title: '任务「Q3 内容排期」已通过审批',
  target_type: 'task',
  target_id: 'task-1',
  target_conversation_id: null,
  target_approval_id: null,
  created_at: '2026-09-23T02:10:00Z',
  read_at: null,
  ...over,
})

const UNREAD = ITEM()
// 标题**刻意**与类型标签（`INBOX_KIND_LABELS` 的「注册申请已通过」）不同字，
// 否则用例里 `getByText` 会同时命中标题单元格与类型单元格（阶段 1 首轮用例踩过）。
const READ = ITEM({
  inbox_id: 'inbox-2',
  kind: 'account.registration.approved',
  title: '你的账号开通申请已通过审核',
  target_type: null,
  target_id: null,
  read_at: '2026-09-21T15:00:00Z',
})

describe('通知页', () => {
  beforeEach(() => {
    resetMockInbox()
  })

  afterEach(() => {
    setServiceMode('mock')
    resetMockInbox()
    vi.unstubAllGlobals()
  })

  it('已接入真实数据时显示真实数据说明，且不出现「示例数据」标识', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD], unread_count: 1 } } })

    renderWithProviders(<InboxPage />)

    expect(await screen.findByText('已接入真实数据')).toBeInTheDocument()
    expect(screen.queryByText('示例数据（未接后端）')).not.toBeInTheDocument()
  })

  it('样例模式显示「示例数据（未接后端）」标识，且不发请求', async () => {
    setServiceMode('mock')
    const { calls } = stubFetch({ '/api/v1/inbox': { body: { items: [], unread_count: 0 } } })

    renderWithProviders(<InboxPage />)

    expect(await screen.findByText('示例数据（未接后端）')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('渲染通知标题与类型标签', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD, READ], unread_count: 1 } } })

    renderWithProviders(<InboxPage />)

    expect(await screen.findByText('任务「Q3 内容排期」已通过审批')).toBeInTheDocument()
    expect(screen.getByText('任务已通过')).toBeInTheDocument()
    expect(screen.getByText('注册申请已通过')).toBeInTheDocument()
  })

  it('目标落点**两档都要说清**：右栏能看摘要、完整页面仍未合并（2026-09-23 换壳后）', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD], unread_count: 1 } } })

    renderWithProviders(<InboxPage />)

    // ① 如实说明"完整页面还不行"
    expect(
      await screen.findByText('可在右栏看到「任务详情」的简要信息；该对象的**完整页面**尚未合并进本工作台。'),
    ).toBeInTheDocument()
    // ② 同时给出**可达的那一档**（右栏）—— 不是"完全打不开"
    expect(screen.getByRole('button', { name: '在右栏查看' })).toBeInTheDocument()
  })

  it('点「在右栏查看」⇒ 把对象上报给壳，并把 `?object=` 写进 URL（可分享）', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD], unread_count: 1 } } })
    const user = userEvent.setup()
    window.history.replaceState(null, '', '?view=inbox')
    resetShellStore()

    renderWithProviders(<InboxPage />)
    await screen.findByText('任务「Q3 内容排期」已通过审批')
    await user.click(screen.getByRole('button', { name: '在右栏查看' }))

    // 对象进了壳的状态树（右栏据此渲染）
    expect(useShellStore.getState().objects['task-1'].title).toBe('任务「Q3 内容排期」已通过审批')
    // 且写进了 URL ⇒ 可分享 / 可刷新
    expect(window.location.search).toContain('object=task-1')
    expect(window.location.search).toContain('objectType=task')
  })

  it('无目标的通知不产生多余的落点说明', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/inbox': { body: { items: [READ], unread_count: 0 } } })

    renderWithProviders(<InboxPage />)

    await screen.findByText('注册申请已通过')
    expect(screen.queryByText(/尚未合并进本工作台/)).not.toBeInTheDocument()
  })

  describe('「全部 / 未读」筛选', () => {
    it('切到「未读」后已读行消失，且**不发新请求**（纯前端筛选）', async () => {
      setServiceMode('http')
      const { calls } = stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD, READ], unread_count: 1 } } })
      // AntD `Segmented` 把原生 input 设为 `pointer-events: none`（真点击落在外层 label 上），
      // 故关掉 user-event 的指针检查，否则点击会被判为不可交互。
      const user = userEvent.setup({ pointerEventsCheck: 0 })

      renderWithProviders(<InboxPage />)
      await screen.findByText('你的账号开通申请已通过审核')
      const before = calls.length

      await user.click(screen.getByRole('radio', { name: '未读' }))

      await waitFor(() => {
        expect(screen.queryByText('你的账号开通申请已通过审核')).not.toBeInTheDocument()
      })
      expect(screen.getByText('任务「Q3 内容排期」已通过审批')).toBeInTheDocument()
      expect(calls).toHaveLength(before)
    })

    it('筛选没命中 ⇒ 说"都已读"，**不得**说成"还没有通知"', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { body: { items: [READ], unread_count: 0 } } })
      const user = userEvent.setup({ pointerEventsCheck: 0 })

      renderWithProviders(<InboxPage />)
      await screen.findByText('你的账号开通申请已通过审核')

      await user.click(screen.getByRole('radio', { name: '未读' }))

      expect(await screen.findByText('当前列表里的通知都已读，切回「全部」可以查看历史通知。')).toBeInTheDocument()
      expect(screen.queryByText('还没有通知。')).not.toBeInTheDocument()
    })

    it('一条通知都没有 ⇒ 说"还没有通知"', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { body: { items: [], unread_count: 0 } } })

      renderWithProviders(<InboxPage />)

      expect(await screen.findByText('还没有通知。')).toBeInTheDocument()
    })
  })

  describe('写侧', () => {
    it('「标为已读」发出 POST 到 /read 并重新取数', async () => {
      setServiceMode('http')
      const { calls } = stubFetch({
        '/api/v1/inbox/': { body: { ...UNREAD, read_at: '2026-09-23T03:00:00Z' } },
        '/api/v1/inbox?': { body: { items: [UNREAD], unread_count: 1 } },
      })
      const user = userEvent.setup()

      renderWithProviders(<InboxPage />)
      await screen.findByText('任务「Q3 内容排期」已通过审批')

      await user.click(screen.getByRole('button', { name: '标为已读' }))

      await waitFor(() => {
        const posted = calls.filter((call) => call.init.method === 'POST')
        expect(posted).toHaveLength(1)
        expect(posted[0].url).toBe('/api/v1/inbox/inbox-1/read')
      })
      // 成功后重新取数（以服务端回读为准）
      await waitFor(() => {
        expect(calls.filter((call) => call.init.method === 'GET').length).toBeGreaterThanOrEqual(2)
      })
    })

    it('「全部标记已读」发出 POST 到 /read-all', async () => {
      setServiceMode('http')
      const { calls } = stubFetch({
        '/api/v1/inbox/read-all': { body: { updated: 1 } },
        '/api/v1/inbox?': { body: { items: [UNREAD], unread_count: 1 } },
      })
      const user = userEvent.setup()

      renderWithProviders(<InboxPage />)
      await screen.findByText('任务「Q3 内容排期」已通过审批')

      await user.click(screen.getByRole('button', { name: /全部标记已读/ }))

      await waitFor(() => {
        expect(calls.some((call) => call.url === '/api/v1/inbox/read-all' && call.init.method === 'POST')).toBe(true)
      })
    })

    it('未读为 0 时「全部标记已读」禁用（不做无效写）', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { body: { items: [READ], unread_count: 0 } } })

      renderWithProviders(<InboxPage />)
      await screen.findByText('你的账号开通申请已通过审核')

      expect(screen.getByRole('button', { name: /全部标记已读/ })).toBeDisabled()
    })
  })

  describe('四态', () => {
    it('403 ⇒ 无权限态，文案与"加载失败"不同', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { status: 403, body: { detail: '无权限' } } })

      renderWithProviders(<InboxPage />)

      expect(await screen.findByText('当前账号没有查看通知的权限。')).toBeInTheDocument()
      expect(screen.queryByText('通知加载失败，请稍后重试。')).not.toBeInTheDocument()
    })

    it('503 ⇒ 加载失败态，且提供重试', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { status: 503 } })

      renderWithProviders(<InboxPage />)

      expect(await screen.findByText('通知加载失败，请稍后重试。')).toBeInTheDocument()
      // AntD 会在按钮可及名里给两个汉字之间插空白 ⇒ 用宽松匹配（与基座组件用例同口径）
      expect(screen.getAllByRole('button', { name: /重\s*试/ }).length).toBeGreaterThan(0)
    })

    it('加载失败**不得**显示成"还没有通知"', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/inbox': { status: 500 } })

      renderWithProviders(<InboxPage />)

      await screen.findByText('通知加载失败，请稍后重试。')
      expect(screen.queryByText('还没有通知。')).not.toBeInTheDocument()
    })
  })

  it('未读计数来自服务端返回的 unread_count（不按本页行数推算）', async () => {
    setServiceMode('http')
    // 本页只有 1 行，但服务端说全租户有 7 条未读 ⇒ 界面必须显示 7
    stubFetch({ '/api/v1/inbox': { body: { items: [UNREAD], unread_count: 7 } } })

    renderWithProviders(<InboxPage />)

    await screen.findByText('任务「Q3 内容排期」已通过审批')
    // 用工具栏那句唯一文案断言（`getByText('未读')` 会同时命中指标卡标签、
    // 筛选档位与行内状态标签三个位置，属脆断言）
    expect(screen.getByText('未读通知 7 条')).toBeInTheDocument()
  })
})
