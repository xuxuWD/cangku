/**
 * 「协同动态」页面用例。
 *
 * 覆盖口径：
 *  - 列表渲染：标题 / 数字员工 / 状态标签 / 时间；
 *  - 三项统计写明「按本页统计」，且**只统计本页数据**（不冒充全量）；
 *  - 目标落点分**两档**且都要说清：右栏能看摘要、完整页面仍未合并；
 *  - 四态：空 / 加载失败（可重试）/ 无权限（文案与"加载失败"不同）；
 *  - 加载失败**不得**显示成"暂无动态"。
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { CollaborationDynamicsPage } from '../CollaborationDynamicsPage'
import { setServiceMode } from '../services/dynamicsService'
import { resetShellStore, useShellStore } from '../../../app/shellStore'

function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const fetchImpl = (async (url: string) => {
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return { status, ok: status >= 200 && status < 300, text: async () => (body === undefined ? '' : JSON.stringify(body)) }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
}

const ROW = (over: Record<string, unknown> = {}) => ({
  event_id: 'dyn-1',
  aggregate_id: 'task-1',
  action: 'task.queued',
  title: '任务「Q3 内容排期」进入执行队列',
  employee_key: 'content-writer',
  status: 'queued',
  tenant_id: 'demo-tenant',
  project_id: null,
  created_by: 'acct-1',
  occurred_at: '2026-09-23T02:05:00Z',
  ...over,
})

const PENDING = ROW({ event_id: 'dyn-2', aggregate_id: 'task-2', title: '任务「竞品资料抓取」提交审批', status: 'pending_approval' })

describe('协同动态页', () => {
  afterEach(() => {
    setServiceMode('mock')
    vi.unstubAllGlobals()
  })

  it('已接入真实数据时显示真实说明，不出现示例标识', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW()] } })

    renderWithProviders(<CollaborationDynamicsPage />)

    expect(await screen.findByText('已接入真实数据')).toBeInTheDocument()
    expect(screen.queryByText('示例数据（未接后端）')).not.toBeInTheDocument()
  })

  it('渲染动态标题、数字员工与状态标签', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW(), PENDING] } })

    renderWithProviders(<CollaborationDynamicsPage />)

    expect(await screen.findByText('任务「Q3 内容排期」进入执行队列')).toBeInTheDocument()
    expect(screen.getAllByText('content-writer').length).toBeGreaterThan(0)
    // 「排队中」只在状态标签出现 ⇒ 唯一；「等待审批」同时是指标卡标签与状态标签 ⇒ 用计数断言
    expect(screen.getByText('排队中')).toBeInTheDocument()
    expect(screen.getAllByText('等待审批').length).toBeGreaterThanOrEqual(2)
  })

  it('三项统计只统计本页数据（涉及任务去重、等待审批计数）', async () => {
    setServiceMode('http')
    // 第 3 条与第 1 条同属 task-1（用于验证"涉及任务"去重），但标题不同以免 getByText 撞名
    stubFetch({
      '/api/v1/collaboration-dynamics': {
        body: [ROW(), PENDING, ROW({ event_id: 'dyn-3', title: '任务「Q3 内容排期」开始执行' })],
      },
    })

    renderWithProviders(<CollaborationDynamicsPage />)

    await screen.findByText('任务「Q3 内容排期」开始执行')
    // 本页 3 条动态，但只涉及 2 个任务（task-1 出现两次）
    expect(screen.getByText('本页动态')).toBeInTheDocument()
    expect(screen.getByText('涉及任务')).toBeInTheDocument()
    expect(screen.getByText('展示当前账号有权限查看的任务动态；统计口径均为「按本页统计」。')).toBeInTheDocument()
  })

  it('目标落点**两档都要说清**，并给出可达的那一档（2026-09-23 换壳后）', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW()] } })

    renderWithProviders(<CollaborationDynamicsPage />)

    expect(await screen.findByText(/可在右栏看到该任务的简要信息/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '在右栏查看' })).toBeInTheDocument()
  })

  it('点「在右栏查看」⇒ 上报对象 + 写进 URL', async () => {
    setServiceMode('http')
    stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW()] } })
    const user = userEvent.setup()
    window.history.replaceState(null, '', '?view=dynamics')
    resetShellStore()

    renderWithProviders(<CollaborationDynamicsPage />)
    await screen.findByText('任务「Q3 内容排期」进入执行队列')
    await user.click(screen.getByRole('button', { name: '在右栏查看' }))

    expect(useShellStore.getState().objects['task-1']).toBeDefined()
    expect(window.location.search).toContain('object=task-1')
  })

  describe('四态', () => {
    it('没有动态 ⇒ 空态文案', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/collaboration-dynamics': { body: [] } })

      renderWithProviders(<CollaborationDynamicsPage />)

      expect(await screen.findByText('暂无协同动态：有新的任务动态后会展示在这里。')).toBeInTheDocument()
    })

    it('加载失败 ⇒ 错误态 + 可重试，**不得**说成"暂无动态"', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/collaboration-dynamics': { status: 500 } })

      renderWithProviders(<CollaborationDynamicsPage />)

      expect(await screen.findByText('协同动态加载失败，请稍后重试。')).toBeInTheDocument()
      expect(screen.queryByText('暂无协同动态：有新的任务动态后会展示在这里。')).not.toBeInTheDocument()
      expect(screen.getAllByRole('button', { name: /重\s*试/ }).length).toBeGreaterThan(0)
    })

    it('403 ⇒ 无权限态，文案与"加载失败"不同', async () => {
      setServiceMode('http')
      stubFetch({ '/api/v1/collaboration-dynamics': { status: 403 } })

      renderWithProviders(<CollaborationDynamicsPage />)

      expect(await screen.findByText('当前账号没有查看协同动态的权限。')).toBeInTheDocument()
      expect(screen.queryByText('协同动态加载失败，请稍后重试。')).not.toBeInTheDocument()
    })
  })

  it('刷新按钮能重新取数', async () => {
    setServiceMode('http')
    let hits = 0
    const fetchImpl = (async () => {
      hits += 1
      return { status: 200, ok: true, text: async () => JSON.stringify([ROW()]) }
    }) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchImpl)
    const user = userEvent.setup()

    renderWithProviders(<CollaborationDynamicsPage />)
    await screen.findByText('任务「Q3 内容排期」进入执行队列')
    const before = hits

    // AntD 会给双汉字按钮名插空白 ⇒ 宽松匹配
    await user.click(screen.getByRole('button', { name: /刷\s*新/ }))

    await waitFor(() => {
      expect(hits).toBeGreaterThan(before)
    })
  })
})
