import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, vi } from 'vitest'
import { AppShell } from './AppShell'
import { navigateShell, shellRoute } from './shellRouter'
import { ADMIN_SETTINGS_ENTRIES, NAV_ITEMS, adminSettingsKeysForRole, navItemsForRole } from './navigation'
import { TOKEN_STORAGE_KEY } from './session'
import { renderWithProviders, signInAs } from '../test/renderWithProviders'

beforeEach(() => {
  // ⚠️ **URL 是全局状态，且 jsdom 的 `location` 在同一文件内跨用例累积**（`pushState` 不会自动重置）。
  // 换壳成 URL 路由之后，不重置会让用例**互相影响、结果随执行顺序变**
  // （2026-09-23 侦察时实测：同一批用例两次跑出 3 红 / 5 红两种结果）。
  // ⇒ 每条用例都从"干净地址栏"起跑。
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  // 本文件里有用例替换了全局 fetch（登出路径）：无论成败都必须还原，避免污染其它用例。
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
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
  it('导航定义：侧栏对所有角色都是 9 项（B3 §7 收敛后 ≤10），开发辅助入口不计入业务导航', () => {
    // 2026-09-23 两轮改动：
    //  ① 合并移植「通知」「协同动态」进基座（依据 D-050⑤「合并为一份，基座重组」）；
    //  ② **B3 §7 侧栏收敛**：管理类三项（数字员工管理 / 权限配置 / 用量与费用）**收进设置弹窗**
    //     ⇒ 侧栏对**所有角色**都是 8 项（目标 ≤10）。**页面未删、功能未减**（可逆收敛）。
    // **本断言是随这两次有意调整的，不是测试腐化。**
    expect(navItemsForRole('employee')).toHaveLength(9)
    expect(navItemsForRole('super_admin')).toHaveLength(9)
    // 「组件样品」入口是**构建期**决定的：测试模式（MODE=test）下它根本不在表里。
    expect(NAV_ITEMS.some((item) => item.key === 'components-playground')).toBe(false)
    // 第 8 轮起「Skill & MCP」、第 10 轮起「审计日志」对四个业务角色开放（矩阵 §3）；
    // 「通知」按登录身份自限（服务端强制），五个角色都有本人通知 ⇒ 全员可见；
    // 「协同动态」契约载明普通员工看本人有权限的任务子集 ⇒ 全员可见。
    const businessKeys = ['conversation', 'my-workbench', 'inbox', 'my-agents', 'knowledge', 'dynamics', 'skills-mcp', 'team', 'audit-log']
    expect(navItemsForRole('employee').map((item) => item.key)).toEqual(businessKeys)
    // 第 6 轮起角色由服务端下发（共 5 个）：任何一个角色都得至少取到一项，
    // 否则壳里 `visibleItems[0]` 落空会整页崩掉。
    for (const role of ['department_lead', 'ceo'] as const) {
      expect(navItemsForRole(role).map((item) => item.key)).toEqual(businessKeys)
    }
    // `customer_admin` 在技能域与审计域一律 ❌ ⇒ 两个入口都不显示（页面另有整页无权限态兜底）
    expect(navItemsForRole('customer_admin').map((item) => item.key)).toEqual([
      'conversation',
      'my-workbench',
      'inbox',
      'my-agents',
      'knowledge',
      'dynamics',
      'team',
    ])
    // 收敛的**可逆性证据**（B3 §13.2 R5 / 验收 A8）：三项管理入口没丢，只是换了到达方式
    expect(ADMIN_SETTINGS_ENTRIES.map((entry) => entry.key)).toEqual(['agent-admin', 'permissions', 'billing'])
    expect(adminSettingsKeysForRole('super_admin')).toEqual(['agent-admin', 'permissions', 'billing'])
    // 员工档在设置弹窗里**没有**可到达的管理项 —— 不摆点了必被拒绝的入口
    expect(adminSettingsKeysForRole('employee')).toEqual([])
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

  it('员工角色渲染 9 个导航项（2026-09-23 起新增「对话」「通知」「协同动态」）', () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    const items = menuItems()
    expect(items).toHaveLength(9)
    expect(items.map((item) => item.textContent)).toEqual([
      '对话',
      '我的工作台',
      '通知',
      '我的数字员工',
      '知识库',
      '协同动态',
      'Skill & MCP',
      '团队协作',
      '审计日志',
    ])
    // 「用量与费用」只对 super_admin / customer_admin 可见 ⇒ 员工档不出现（不留点了必 403 的假入口）
    expect(items.map((item) => item.textContent)).not.toContain('用量与费用')
  })

  it('管理员渲染 9 个导航项（管理类已收进设置弹窗 —— B3 §7）', () => {
    signInAs('super_admin')
    renderWithProviders(<AppShell />)
    const items = menuItems()
    expect(items).toHaveLength(9)
    expect(items.map((item) => item.textContent)).toEqual([
      '对话',
      '我的工作台',
      '通知',
      '我的数字员工',
      '知识库',
      '协同动态',
      'Skill & MCP',
      '团队协作',
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

  it('URL 指向当前角色不可见的页时，自动回落到可见页（而不是白屏）', async () => {
    // ⚠️ 2026-09-23 改：侧栏收敛后**没有任何角色的侧栏项是"独有"的了**
    // （管理类三项对非管理员不可见，但它们已不在侧栏、而在设置弹窗里）。
    // 所以这个用例改从 **URL 直达**一个非管理员可见的页来验回落 —— 这更贴近真实路径：
    // 收到一条「权限配置」的分享链接、但自己没有那个权限。
    signInAs('super_admin')
    window.history.replaceState(null, '', '?view=permissions')
    renderWithProviders(<AppShell />)
    expect(pageTitle()).toHaveTextContent('权限配置')

    // 第 6 轮起角色切换只能来自服务端（重登）；这里直接改写会话，验证壳的回落逻辑没坏。
    act(() => signInAs('employee'))
    expect(menuItems()).toHaveLength(9)
    expect(pageTitle()).toHaveTextContent('我的工作台')
    // 回落是**界面行为**：URL 保留原样，不把"无权"写回成"看起来有权"
    expect(window.location.search).toBe('?view=permissions')
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

  /* ================= B3 §4「对话常驻」的四条要求 + 验收 A2 / A4 ================= */

  it('§4 要求①：切走只 hidden / display:none，**对话宿主不卸载**（同一个 DOM 节点）', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    // 默认落地页是「我的工作台」⇒ 先显式进对话页
    await userEvent.click(screen.getByRole('menuitem', { name: /对话/ }))
    const slot = screen.getByTestId('conversation-slot')
    expect(slot.getAttribute('data-visible')).toBe('true')

    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))

    const after = screen.getByTestId('conversation-slot')
    expect(after).toBe(slot) // ← 同一个节点 ⇒ 没被卸载（SSE 与滚动位置因此不丢）
    expect(after.getAttribute('data-visible')).toBe('false')
    expect(after.hasAttribute('hidden')).toBe(true)
    expect(after.style.display).toBe('none')
    // 槽上留了 `view-slot` 标记 ⇒ `useSlotVisible` 能找到它并据此**主动断流**
    expect(slot.classList.contains('view-slot')).toBe(true)
  })

  it('验收 A2：切走再切回，宿主仍是**同一个节点**且恢复可见', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /对话/ }))
    const slot = screen.getByTestId('conversation-slot')

    await userEvent.click(screen.getByRole('menuitem', { name: /通知/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: /对话/ }))

    const back = screen.getByTestId('conversation-slot')
    expect(back).toBe(slot)
    expect(back.getAttribute('data-visible')).toBe('true')
    expect(back.hasAttribute('hidden')).toBe(false)
  })

  it('§4 要求③ + 验收 A4：快速连切 20 次不错乱，宿主始终同一节点、epoch 单调', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /对话/ }))
    const slot = screen.getByTestId('conversation-slot')
    const epochOf = () => Number(screen.getByTestId('conversation-slot').getAttribute('data-epoch'))
    const first = epochOf()

    // ⚠️ 用**直接驱动路由**而不是点菜单：这里要验的是"快速切路由时界面不错乱"，
    // 而 20 次 `userEvent.click` 在 AntD 菜单上要十几秒（会撞测试超时），
    // 且点的慢反而不构成"快速连切"。同步驱动路由正是规格 §4 说的那个场景。
    for (let i = 0; i < 20; i += 1) {
      act(() => {
        navigateShell(shellRoute(i % 2 === 0 ? 'knowledge' : 'conversation'))
      })
    }

    // 第 20 次（i=19，奇数）落在「对话」⇒ 应可见；且始终是同一个节点
    const end = screen.getByTestId('conversation-slot')
    expect(end).toBe(slot)
    expect(end.getAttribute('data-visible')).toBe('true')
    expect(window.location.search).toBe('?view=conversation')
    // epoch 单调递增 ⇒ 任何延后副作用都能靠它判过期
    expect(epochOf()).toBeGreaterThan(first)
  })

  it('§2 互斥：对话与其他页**不会同时可见**', async () => {
    signInAs('employee')
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByRole('menuitem', { name: /对话/ }))
    expect(screen.getByTestId('conversation-slot').getAttribute('data-visible')).toBe('true')
    expect(screen.queryByTestId('main-surface')).toBeNull()

    await userEvent.click(screen.getByRole('menuitem', { name: /知识库/ }))
    expect(screen.getByTestId('conversation-slot').getAttribute('data-visible')).toBe('false')
    expect(screen.getByTestId('main-surface')).not.toBeNull()
  })
})
