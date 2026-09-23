/**
 * B3 原型 · 三栏壳的**机制**用例
 *
 * 这份用例存在的唯一理由：规格 §4 的四条要求与 §12 的验收项，**必须可测**，
 * 否则"对话常驻"只是一句口号。逐条对应：
 *
 * | 用例 | 对应 |
 * | --- | --- |
 * | 对话宿主切走同节点 | §4 要求①（不卸载）+ 验收 A2 |
 * | 切走时 display:none | §4 要求①|
 * | 快速连切 20 次不错乱 | §4 要求③ + 验收 A4 |
 * | 悬浮助手切换同节点 | 验收 A7（路由切换不卸载） |
 * | URL 直达可复现 | 验收 A5 |
 * | 侧栏业务入口 8 项 | 验收 A1（≤10） |
 * | 右栏展开时对话隐藏但仍在 | §5 逃生口 + 要求① 的交叉 |
 * | 设置弹窗列全管理项 | 验收 A8 + §13.2 R5（收敛可逆） |
 */
import { act, screen, within } from '@testing-library/react'
import { renderWithProviders } from '../../test/renderWithProviders'
import { PrototypeApp } from '../PrototypeApp'
import { navigate, routeFor } from '../router'
import { resetPrototypeStore, usePrototypeStore } from '../store'
import { SETTINGS_ENTRIES } from '../nav'

/** 把地址栏设成某个 query（模拟"地址栏直达"）。 */
function goto(search: string): void {
  window.history.replaceState(null, '', search)
}

describe('B3 三栏壳 · 对话常驻（规格 §4）', () => {
  beforeEach(() => {
    resetPrototypeStore()
    goto('?view=chat')
  })

  it('切走再切回：对话宿主是**同一个 DOM 节点**（没被卸载）—— 要求① / 验收 A2', () => {
    renderWithProviders(<PrototypeApp />)
    const before = screen.getByTestId('conversation-host')

    act(() => navigate(routeFor('todo')))
    const away = screen.getByTestId('conversation-host')
    expect(away).toBe(before) // 同一个节点 ⇒ 没卸载

    act(() => navigate(routeFor('chat')))
    expect(screen.getByTestId('conversation-host')).toBe(before)
  })

  it('切走时只 `display:none`，节点仍在文档里 —— 要求①', () => {
    renderWithProviders(<PrototypeApp />)

    act(() => navigate(routeFor('todo')))

    const host = screen.getByTestId('conversation-host')
    expect(host).toBeInTheDocument()
    expect(host.getAttribute('data-visible')).toBe('false')
    expect(host.style.display).toBe('none')
  })

  it('切回后重新可见（display 恢复）', () => {
    renderWithProviders(<PrototypeApp />)
    act(() => navigate(routeFor('todo')))
    act(() => navigate(routeFor('chat')))

    const host = screen.getByTestId('conversation-host')
    expect(host.getAttribute('data-visible')).toBe('true')
    expect(host.style.display).toBe('flex')
  })

  it('快速连续切 20 次：最终 display 与最终路由一致，且节点始终是同一个 —— 要求③ / 验收 A4', () => {
    renderWithProviders(<PrototypeApp />)
    const first = screen.getByTestId('conversation-host')

    for (let i = 0; i < 20; i += 1) {
      act(() => navigate(routeFor(i % 2 === 0 ? 'workitems' : 'chat')))
      expect(screen.getByTestId('conversation-host')).toBe(first)
    }

    // 第 19 次是 i=19（奇数）⇒ 落在 chat ⇒ 应可见；与 URL 一致
    expect(window.location.search).toBe('?view=chat')
    expect(screen.getByTestId('conversation-host').style.display).toBe('flex')
  })

  it('宿主上的 epoch 是单调递增的（切走/切回各推一次），不与可见性错位 —— 要求③', () => {
    renderWithProviders(<PrototypeApp />)
    const epochAt = () => Number(screen.getByTestId('conversation-host').getAttribute('data-epoch'))

    const e0 = epochAt()
    act(() => navigate(routeFor('todo')))
    const e1 = epochAt()
    act(() => navigate(routeFor('chat')))
    const e2 = epochAt()

    expect(e1).toBeGreaterThan(e0)
    expect(e2).toBeGreaterThan(e1)
    // 关键：可见性与 epoch **同帧一致** —— 可见时 epoch 必然是最后一次变化后的值
    expect(screen.getByTestId('conversation-host').getAttribute('data-visible')).toBe('true')
    expect(e2).toBe(epochAt())
  })

  it('其余页面与对话**互斥显示**（同时只看得见一个）', () => {
    renderWithProviders(<PrototypeApp />)

    act(() => navigate(routeFor('workitems')))

    expect(screen.getByTestId('conversation-host').style.display).toBe('none')
    expect(screen.getByTestId('prototype-page')).toBeInTheDocument()
  })
})

describe('B3 三栏壳 · 悬浮助手（验收 A7）', () => {
  beforeEach(() => {
    resetPrototypeStore()
    goto('?view=chat')
  })

  it('路由切换前后是**同一个 DOM 节点**（不卸载）', () => {
    renderWithProviders(<PrototypeApp />)
    const before = screen.getByTestId('floating-assistant')

    act(() => navigate(routeFor('files')))
    act(() => navigate(routeFor('chat')))

    expect(screen.getByTestId('floating-assistant')).toBe(before)
  })

  it('打开抽屉后「待你处理」按规格顺序排列', async () => {
    renderWithProviders(<PrototypeApp />)
    act(() => usePrototypeStore.getState().setAssistantOpen(true))

    const drawer = await screen.findByRole('dialog')
    const kinds = within(drawer)
      .getAllByText(/^(待审批|待输入|受阻|失败|完成)$/)
      .map((node) => node.textContent)
    expect(kinds).toEqual(['待审批', '待输入', '受阻', '失败', '完成'])
  })

  it('意图识别是规则层：输入命中文案即出结果，并回传命中的正则', async () => {
    renderWithProviders(<PrototypeApp />)
    act(() => usePrototypeStore.getState().setAssistantOpen(true))
    const drawer = await screen.findByRole('dialog')

    await act(async () => {
      usePrototypeStore.getState().setAssistantDraft('派给内容岗写篇稿')
    })

    expect(within(drawer).getByText('按「委派」处理')).toBeInTheDocument()
    expect(within(drawer).getByText('命中：/派给/')).toBeInTheDocument()
  })
})

describe('B3 三栏壳 · 右栏与展开逃生口（规格 §5）', () => {
  beforeEach(() => {
    resetPrototypeStore()
  })

  it('URL 带 object ⇒ 右栏直接显示该对象（可直达 / 可分享）—— 验收 A5', () => {
    goto('?view=workitems&object=task-1&panel=brief')
    renderWithProviders(<PrototypeApp />)

    const panel = screen.getByTestId('right-panel')
    expect(within(panel).getByText('Q3 内容排期')).toBeInTheDocument()
    expect(within(panel).getByText('task-1')).toBeInTheDocument()
    // 「简要信息」页签只给对象本身，**不打**上下文字段（那是数字员工页签的事）
    expect(within(panel).queryByText(/current_task_id/)).not.toBeInTheDocument()
  })

  it('数字员工页签**显式打出要注入的上下文字段**（验收 A6 的界面证据）', () => {
    goto('?view=workitems&object=run-1&panel=employee')
    renderWithProviders(<PrototypeApp />)

    const panel = screen.getByTestId('right-panel')
    expect(within(panel).getByText('已带上当前对象上下文')).toBeInTheDocument()
    // 字段名在两处出现（说明文案 + 标签）⇒ 用 getAllByText
    expect(within(panel).getAllByText(/current_run_id/).length).toBeGreaterThan(0)
    expect(within(panel).getByText('注入字段：current_run_id')).toBeInTheDocument()
  })

  it('未选对象 ⇒ 右栏是空态说明，**不是空白**', () => {
    goto('?view=chat')
    renderWithProviders(<PrototypeApp />)

    expect(within(screen.getByTestId('right-panel')).getByText('未选中对象')).toBeInTheDocument()
  })

  it('展开全屏时：对话隐藏但**仍挂在文档里**（逃生口不牺牲"不卸载"）', () => {
    goto('?view=chat&object=task-1&panel=brief')
    renderWithProviders(<PrototypeApp />)

    act(() => navigate(routeFor('chat', 'task-1', 'brief', true)))

    const host = screen.getByTestId('conversation-host')
    expect(host).toBeInTheDocument()
    expect(host.style.display).toBe('none')
    expect(screen.getByTestId('right-panel').style.width).toBe('100%')
  })
})

describe('B3 三栏壳 · 侧栏收敛与设置（验收 A1 / A8）', () => {
  beforeEach(() => {
    resetPrototypeStore()
    goto('?view=chat')
  })

  it('侧栏业务入口是规格 §2 的主 5 + 更多 3（≤10）', () => {
    renderWithProviders(<PrototypeApp />)

    const labels = screen.getAllByRole('menuitem').map((node) => node.textContent ?? '')
    for (const title of ['新建对话', '待我处理', '我的数字员工', '工作项', '知识库', '自动化', '文件', '扩展']) {
      expect(labels.some((text) => text.includes(title))).toBe(true)
    }
    expect(labels.filter((text) => /自动化|文件|扩展|工作项|知识库|数字员工|待我处理|新建对话/.test(text))).toHaveLength(8)
  })

  it('被收掉的管理项在设置弹窗里**仍可到达**，且标明了原本在哪（收敛可逆 —— §13.2 R5 / 验收 A8）', async () => {
    renderWithProviders(<PrototypeApp />)
    act(() => usePrototypeStore.getState().setSettingsOpen(true))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('管理类功能不是被删掉，是被收进这里')).toBeInTheDocument()
    for (const entry of SETTINGS_ENTRIES) {
      expect(within(dialog).getByText(entry.title)).toBeInTheDocument()
    }
    // 「原本在哪」这一列是"可逆"的关键证据
    expect(within(dialog).getByText('workbench-web `audit-log`')).toBeInTheDocument()
  })
})
