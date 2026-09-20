import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, vi } from 'vitest'
import { AppShell } from './AppShell'
import { NAV_ITEMS, navItemsForRole } from './navigation'
import { TOKEN_STORAGE_KEY } from './session'
import { renderWithProviders, signInAs } from '../test/renderWithProviders'

afterEach(() => {
  // 本文件里有用例替换了全局 fetch（登出路径）：无论成败都必须还原，避免污染其它用例。
  vi.unstubAllGlobals()
})

/** 当前页标题（页面里唯一的 h1）。 */
function pageTitle(): HTMLElement {
  return screen.getByRole('heading', { level: 1 })
}

/** 侧栏导航项（AntD Menu 平铺，无子菜单）。 */
function menuItems(): HTMLElement[] {
  return within(screen.getByRole('menu')).getAllByRole('menuitem')
}

describe('AppShell（第 1 轮应用壳）', () => {
  it('导航定义本身是既定的 5 + 3 结构，开发辅助入口不计入业务导航', () => {
    expect(navItemsForRole('employee')).toHaveLength(5)
    expect(navItemsForRole('super_admin')).toHaveLength(8)
    // 「组件样品」入口是**构建期**决定的：测试模式（MODE=test）下它根本不在表里。
    expect(NAV_ITEMS.some((item) => item.key === 'components-playground')).toBe(false)
    // 第 8 轮起「Skill & MCP」对四个业务角色开放（矩阵 §3「技能：提交」含 employee ✅）
    expect(navItemsForRole('employee').map((item) => item.key)).toEqual([
      'my-workbench',
      'my-agents',
      'knowledge',
      'skills-mcp',
      'team',
    ])
    // 第 6 轮起角色由服务端下发（共 5 个）：任何一个角色都得至少取到一项，
    // 否则壳里 `visibleItems[0]` 落空会整页崩掉。
    for (const role of ['department_lead', 'ceo'] as const) {
      expect(navItemsForRole(role).map((item) => item.key)).toEqual([
        'my-workbench',
        'my-agents',
        'knowledge',
        'skills-mcp',
        'team',
      ])
    }
    // `customer_admin` 在技能域一律 ❌ ⇒ 入口不显示（页面另有整页无权限态兜底）
    expect(navItemsForRole('customer_admin').map((item) => item.key)).toEqual([
      'my-workbench',
      'my-agents',
      'knowledge',
      'team',
    ])
  })

  it('开发辅助入口（组件样品）只在开发模式出现；出现时可懒加载出样品页', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
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

  it('员工角色渲染 5 个导航项（第 8 轮起含 Skill & MCP）', () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    const items = menuItems()
    expect(items).toHaveLength(5)
    expect(items.map((item) => item.textContent)).toEqual([
      '我的工作台',
      '我的数字员工',
      '知识库',
      'Skill & MCP',
      '团队协作',
    ])
  })

  it('管理员渲染 8 个导航项（角色自适应，含 3 个管理员专有项）', () => {
    signInAs('super_admin')
    renderWithProviders(<AppShell />)
    const items = menuItems()
    expect(items).toHaveLength(8)
    expect(items.map((item) => item.textContent)).toEqual([
      '我的工作台',
      '我的数字员工',
      '知识库',
      'Skill & MCP',
      '团队协作',
      '数字员工管理',
      '权限配置',
      '审计日志',
    ])
  })

  it('顶栏与侧栏都存在，且文案正确', () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    expect(screen.getByLabelText('主导航')).toBeInTheDocument()
    expect(screen.getByText('公司数字员工工作台')).toBeInTheDocument()
    // 顶栏显示**角色名**（后端登录响应没有展示名字段，不编造姓名），并提供退出登录
    expect(screen.getByText('员工')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeInTheDocument()
    expect(pageTitle()).toHaveTextContent('我的工作台')
  })

  it('点击导航能切换页面标题与页面内容', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))
    expect(pageTitle()).toHaveTextContent('知识库')
    // 第 7 轮起「知识库」是真实页面（占位页已被替换）；2026-09-19 起按矩阵 §3 分视图：
    // 员工可「登记 + 本人角色检索」，治理三块只给原因（不请求数据，见 KnowledgePage 用例）。
    expect(await screen.findByRole('heading', { level: 3, name: '知识检索' })).toBeInTheDocument()
    expect(screen.queryByText('「知识库」尚未接入（第 4 轮实现）。')).not.toBeInTheDocument()
  })

  it('切回员工角色后，管理员专有页面自动回落到可见页面', async () => {
    signInAs('super_admin')
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /审计日志/ }))
    expect(pageTitle()).toHaveTextContent('审计日志')

    // 第 6 轮起角色切换只能来自服务端（重登）；这里直接改写会话，验证壳的回落逻辑没坏。
    act(() => signInAs('employee'))
    expect(menuItems()).toHaveLength(5)
    expect(pageTitle()).toHaveTextContent('我的工作台')
  })

  it('退出登录（服务端撤销成功）：回到登录页，且不显示任何警告', async () => {
    signInAs('employee')
    // 只用到 `status === 204` 一个字段（请求层对 204 直接返回，不读响应体）
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ status: 204, ok: true, text: async () => '' } as unknown as Response),
    )
    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('button', { name: '退出登录' }))

    expect(await screen.findByText('账号（手机号）')).toBeInTheDocument()
    expect(screen.queryByText(/服务端会话撤销失败/)).not.toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('退出登录（服务端撤销失败）：仍清本地，且警告必须显示在**登录页**上（真机走查发现的原缺陷：它渲染在已登录分支里，用户永远看不到）', async () => {
    signInAs('employee')
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('network down')))
    renderWithProviders(<AppShell />)

    await userEvent.click(screen.getByRole('button', { name: '退出登录' }))

    // 本地照清（不假装"还登录着"）；但服务端那头可能仍然有效 ⇒ 必须**看得见**地告知
    expect(await screen.findByText('账号（手机号）')).toBeInTheDocument()
    expect(await screen.findByText(/服务端会话撤销失败/)).toBeInTheDocument()
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
})