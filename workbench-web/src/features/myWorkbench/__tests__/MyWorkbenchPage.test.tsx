import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MyWorkbenchPage } from '../MyWorkbenchPage'
import { AppShell } from '../../../app/AppShell'
import { SAMPLE_DATA_BADGE, setServiceMode } from '../services/myWorkbenchService'
import { useSession } from '../../../app/session'

describe('MyWorkbenchPage', () => {
  beforeEach(() => {
    useSession.setState({ role: 'employee' })
  })

  afterEach(() => {
    setServiceMode('mock')
  })

  it('四块齐备，且有统一的"示例数据（未接后端）"标识（页面 + 两块样例卡片）', async () => {
    render(<MyWorkbenchPage />)

    expect(screen.getByRole('heading', { level: 2, name: '我的工作台' })).toBeInTheDocument()
    for (const title of ['待办', '日程', '最近使用', '快捷入口']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    // 页面顶部 Alert + 待办卡片 + 最近使用卡片
    expect(screen.getAllByText(SAMPLE_DATA_BADGE).length).toBeGreaterThanOrEqual(3)

    expect(await screen.findByText('待审批：整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('示例会话：季度内容排期')).toBeInTheDocument()
  })

  it('日程块：文案含"尚未接入"，且**卡片内没有任何日期/条目**', async () => {
    render(<MyWorkbenchPage />)

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
    render(<MyWorkbenchPage />)

    // 首屏同步渲染时四块都处于加载态
    expect(screen.getAllByText('正在加载，请稍候…').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('待办列表加载失败，请稍后重试。')).not.toBeInTheDocument()

    await screen.findByText('待审批：整理本周选题')
  })

  it('mode=http：取数抛错时四块进入 error 态，而不是假装空', async () => {
    setServiceMode('http')
    render(<MyWorkbenchPage />)

    expect(await screen.findByText('待办列表加载失败，请稍后重试。')).toBeInTheDocument()
    expect(screen.getByText('最近使用加载失败，请稍后重试。')).toBeInTheDocument()
    expect(screen.getByText('快捷入口加载失败，请稍后重试。')).toBeInTheDocument()

    // 不静默显示空态、也不显示样例数据（"假装空"就是不报错、给一个空列表）
    expect(screen.queryByText('当前没有待办（待审批与通知都为空）。')).not.toBeInTheDocument()
    expect(screen.queryByText('暂无最近使用记录。')).not.toBeInTheDocument()
    expect(screen.queryByText('暂无可用的快捷入口。')).not.toBeInTheDocument()
    expect(screen.queryByText('待审批：整理本周选题')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('员工的管理类快捷入口禁用且有原因（不静默隐藏）', async () => {
    render(<MyWorkbenchPage />)

    const disabled = await screen.findByRole('button', { name: '数字员工配置' })
    expect(disabled).toBeDisabled()
    expect(screen.getByText(/需要「权限配置」权限/)).toBeInTheDocument()
  })

  it('壳里选中"我的工作台"即渲染本页（导航可到达）', async () => {
    render(<AppShell />)

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