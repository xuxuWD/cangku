import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuickActions } from '../components/QuickActions'
import { QUICK_ACTIONS } from '../services/myWorkbenchService'
import { useSession } from '../../../app/session'
import type { QuickActionItem } from '../types'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

/** 管理类入口（需要能力）。 */
const ADMIN_ACTIONS = QUICK_ACTIONS.filter((action) => action.kind === 'admin')

describe('QuickActions', () => {
  beforeEach(() => {
    useSession.setState({ role: 'employee' })
  })

  it('员工：管理类入口**渲染为禁用 + 原因**，且入口本身仍然可见（不静默隐藏）', () => {
    render(<QuickActions actions={QUICK_ACTIONS} />)

    expect(screen.getByRole('button', { name: '发起对话' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '我的数字员工' })).toBeEnabled()

    for (const action of ADMIN_ACTIONS) {
      const button = screen.getByRole('button', { name: action.label })
      expect(button).toBeVisible()
      expect(button).toBeDisabled()
    }
    expect(screen.getByText(/需要「数字员工管理」权限，当前角色「员工」不可用/)).toBeInTheDocument()
    expect(screen.getByText(/需要「权限配置」权限，当前角色「员工」不可用/)).toBeInTheDocument()
  })

  it('管理员：管理类入口可用，且不显示原因提示', () => {
    act(() => {
      useSession.setState({ role: 'super_admin' })
    })
    render(<QuickActions actions={QUICK_ACTIONS} />)

    for (const action of ADMIN_ACTIONS) {
      expect(screen.getByRole('button', { name: action.label })).toBeEnabled()
    }
    expect(screen.queryByText(/不可用/)).not.toBeInTheDocument()
  })

  it('点击可用入口会回调（本轮只做跳转占位）', async () => {
    const ran: QuickActionItem[] = []
    render(<QuickActions actions={QUICK_ACTIONS} onRun={(action) => ran.push(action)} />)

    await userEvent.click(screen.getByRole('button', { name: '新建任务' }))
    expect(ran[0].key).toBe('new-task')
  })

  it('四态：loading / empty / error（可重试）/ forbidden', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(<QuickActions actions={QUICK_ACTIONS} state={state} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '发起对话' })).not.toBeInTheDocument()
      unmount()
    }

    let retried = 0
    render(<QuickActions actions={QUICK_ACTIONS} state="error" onRetry={() => { retried += 1 }} />)
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('空目录：渲染明确空态文案', () => {
    render(<QuickActions actions={[]} />)
    expect(screen.getByText('暂无可用的快捷入口。')).toBeInTheDocument()
  })
})