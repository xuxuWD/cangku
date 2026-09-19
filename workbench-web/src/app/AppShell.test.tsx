import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from './AppShell'
import { NAV_ITEMS, navItemsForRole } from './navigation'
import { useSession } from './session'

/** 当前页标题（页面里唯一的 h1）。 */
function pageTitle(): HTMLElement {
  return screen.getByRole('heading', { level: 1 })
}

/** 侧栏导航项（AntD Menu 平铺，无子菜单）。 */
function menuItems(): HTMLElement[] {
  return within(screen.getByRole('menu')).getAllByRole('menuitem')
}

describe('AppShell（第 1 轮应用壳）', () => {
  beforeEach(() => {
    useSession.setState({ role: 'employee' })
  })

  it('导航定义本身是既定的 4 + 4 结构，开发辅助入口不计入业务导航', () => {
    expect(navItemsForRole('employee')).toHaveLength(4)
    expect(navItemsForRole('super_admin')).toHaveLength(8)
    // 「组件样品」入口是**构建期**决定的：测试模式（MODE=test）下它根本不在表里。
    expect(NAV_ITEMS.some((item) => item.key === 'components-playground')).toBe(false)
    expect(navItemsForRole('employee').map((item) => item.key)).toEqual([
      'my-workbench',
      'my-agents',
      'knowledge',
      'team',
    ])
  })

  it('开发辅助入口（组件样品）只在开发模式出现；出现时可懒加载出样品页', async () => {
    render(<AppShell />)
    const devEntry = navItemsForRole('employee').some((item) => item.key === 'components-playground')

    if (!devEntry) {
      // 测试 / 生产模式：入口与页面都不该出现（生产产物里连代码都没有，见构建后的 grep 验收）
      expect(screen.queryByRole('menuitem', { name: /组件样品/ })).not.toBeInTheDocument()
      return
    }

    // 开发模式：入口可见，点进去能动态加载出样品页（React.lazy），且样品页内容确实渲染
    await userEvent.click(screen.getByRole('menuitem', { name: /组件样品/ }))
    expect(await screen.findByRole('heading', { level: 2, name: '组件样品（仅开发可见）' })).toBeInTheDocument()
    expect(await screen.findByText('StatCard：数值与状态保真')).toBeInTheDocument()
  })

  it('员工角色只渲染 4 个导航项', () => {
    render(<AppShell />)
    const items = menuItems()
    expect(items).toHaveLength(4)
    expect(items.map((item) => item.textContent)).toEqual(['我的工作台', '我的数字员工', '知识库', '团队协作'])
  })

  it('管理员渲染 8 个导航项（角色自适应，含 4 个管理员专有项）', async () => {
    render(<AppShell />)
    await userEvent.click(screen.getByText('超级管理员'))
    const items = menuItems()
    expect(items).toHaveLength(8)
    expect(items.map((item) => item.textContent)).toEqual([
      '我的工作台',
      '我的数字员工',
      '知识库',
      '团队协作',
      '数字员工管理',
      '权限配置',
      'Skill & MCP',
      '审计日志',
    ])
  })

  it('顶栏与侧栏都存在，且文案正确', () => {
    render(<AppShell />)
    expect(screen.getByLabelText('主导航')).toBeInTheDocument()
    expect(screen.getByText('公司数字员工工作台')).toBeInTheDocument()
    expect(screen.getByText('角色（演示）')).toBeInTheDocument()
    expect(screen.getByText('员工')).toBeInTheDocument()
    expect(screen.getByText('超级管理员')).toBeInTheDocument()
    expect(pageTitle()).toHaveTextContent('我的工作台')
  })

  it('点击导航能切换页面标题与页面内容', async () => {
    render(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))
    expect(pageTitle()).toHaveTextContent('知识库')
    // 占位页如实说明"未接入"，不假装有数据。
    expect(screen.getByText('「知识库」尚未接入（第 4 轮实现）。')).toBeInTheDocument()
  })

  it('切回员工角色后，管理员专有页面自动回落到可见页面', async () => {
    render(<AppShell />)
    await userEvent.click(screen.getByText('超级管理员'))
    await userEvent.click(screen.getByRole('menuitem', { name: /审计日志/ }))
    expect(pageTitle()).toHaveTextContent('审计日志')

    await userEvent.click(screen.getByText('员工'))
    expect(menuItems()).toHaveLength(4)
    expect(pageTitle()).toHaveTextContent('我的工作台')
  })
})