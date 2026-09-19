import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodoPanel } from '../components/TodoPanel'
import { SAMPLE_DATA_BADGE } from '../services/myWorkbenchService'
import type { TodoItem } from '../types'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

const ITEMS: TodoItem[] = [
  {
    source: 'approval',
    kind: 'task_approval',
    title: '待审批：整理本周选题',
    created_at: '2026-09-19T09:20:00+08:00',
    target_type: 'task',
    target_id: 'sample-task-0001',
  },
  {
    source: 'notification',
    kind: 'notification_result',
    title: '任务已通过：整理客户反馈',
    created_at: '2026-09-18T17:05:00+08:00',
    target_type: 'task',
    target_id: 'sample-task-0002',
  },
]

describe('TodoPanel', () => {
  it('就绪：每项有类型标签、时间与"查看"跳转占位', async () => {
    const opened: TodoItem[] = []
    render(<TodoPanel items={ITEMS} onOpen={(item) => opened.push(item)} />)

    expect(screen.getByText('任务审批')).toBeInTheDocument()
    expect(screen.getByText('结果通知')).toBeInTheDocument()
    expect(screen.getByText('待审批：整理本周选题')).toBeInTheDocument()
    expect(screen.getByText('2026-09-19 09:20')).toBeInTheDocument()

    const openButtons = screen.getAllByRole('button', { name: /查\s*看/ })
    expect(openButtons).toHaveLength(2)
    await userEvent.click(openButtons[0])
    expect(opened[0].target_id).toBe('sample-task-0001')
  })

  it('四态：loading / empty / error（可重试）/ forbidden 各自渲染可识别文案', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(
        <TodoPanel items={ITEMS} state={state} onRetry={() => {}} />,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      // 非就绪时不渲染任何待办条目
      expect(screen.queryByText('待审批：整理本周选题')).not.toBeInTheDocument()
      unmount()
    }

    let retried = 0
    render(<TodoPanel items={ITEMS} state="error" onRetry={() => { retried += 1 }} />)
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('空列表：渲染明确空态文案，不渲染表格', () => {
    render(<TodoPanel items={[]} />)
    expect(screen.getByText('当前没有待办（待审批与通知都为空）。')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('样例数据标识：sample=true 时卡片上可见（防假数据假装真数据）', () => {
    const { unmount } = render(<TodoPanel items={ITEMS} sample />)
    expect(screen.getByText(SAMPLE_DATA_BADGE)).toBeInTheDocument()
    unmount()

    render(<TodoPanel items={ITEMS} />)
    expect(screen.queryByText(SAMPLE_DATA_BADGE)).not.toBeInTheDocument()
  })
})