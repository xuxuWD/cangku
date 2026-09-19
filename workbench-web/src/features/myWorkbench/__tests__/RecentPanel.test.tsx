import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RecentPanel } from '../components/RecentPanel'
import { SAMPLE_DATA_BADGE } from '../services/myWorkbenchService'
import type { RecentItem } from '../types'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

const ITEMS: RecentItem[] = [
  {
    kind: 'conversation',
    target_id: 'sample-conversation-0001',
    title: '示例会话：季度内容排期',
    updated_at: '2026-09-19T09:05:00+08:00',
  },
  {
    kind: 'run',
    target_id: 'sample-run-0001',
    title: '示例运行：文档摘要生成',
    updated_at: '2026-09-18T18:40:00+08:00',
  },
]

describe('RecentPanel', () => {
  it('就绪：会话与运行各带类型标签、时间与"打开"跳转占位', async () => {
    const opened: RecentItem[] = []
    render(<RecentPanel items={ITEMS} onOpen={(item) => opened.push(item)} />)

    expect(screen.getByText('会话')).toBeInTheDocument()
    expect(screen.getByText('运行')).toBeInTheDocument()
    expect(screen.getByText('示例会话：季度内容排期')).toBeInTheDocument()
    expect(screen.getByText('最近更新：2026-09-18 18:40')).toBeInTheDocument()

    const buttons = screen.getAllByRole('button', { name: /打\s*开/ })
    await userEvent.click(buttons[1])
    expect(opened[0].target_id).toBe('sample-run-0001')
  })

  it('四态：loading / empty / error（可重试）/ forbidden', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(<RecentPanel items={ITEMS} state={state} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('示例会话：季度内容排期')).not.toBeInTheDocument()
      unmount()
    }

    let retried = 0
    render(<RecentPanel items={ITEMS} state="error" onRetry={() => { retried += 1 }} />)
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('加载态与空态可区分：加载中不出现"暂无"类文案', () => {
    const loading = render(<RecentPanel items={[]} state="loading" />)
    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
    expect(screen.queryByText(/暂无/)).not.toBeInTheDocument()
    loading.unmount()

    render(<RecentPanel items={[]} />)
    expect(screen.getByText('暂无最近使用记录。')).toBeInTheDocument()
  })

  it('样例数据标识：sample=true 时可见', () => {
    const { unmount } = render(<RecentPanel items={ITEMS} sample />)
    expect(screen.getByText(SAMPLE_DATA_BADGE)).toBeInTheDocument()
    unmount()

    render(<RecentPanel items={ITEMS} />)
    expect(screen.queryByText(SAMPLE_DATA_BADGE)).not.toBeInTheDocument()
  })
})