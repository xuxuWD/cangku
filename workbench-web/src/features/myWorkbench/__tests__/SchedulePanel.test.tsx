import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SchedulePanel } from '../components/SchedulePanel'
import { SCHEDULE_ABSENT } from '../services/myWorkbenchService'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

describe('SchedulePanel', () => {
  it('固定渲染"尚未接入"：文案说明后端无实体，且**没有任何日程条目**', () => {
    render(<SchedulePanel availability={SCHEDULE_ABSENT} />)

    expect(screen.getByText(/尚未接入/)).toBeInTheDocument()
    expect(screen.getByText(/后端暂无日程实体（接口未定义）/)).toBeInTheDocument()
    // 不得出现任何日期 / 时间条目（严禁造日程数据）
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\d{1,2}:\d{2}/)).not.toBeInTheDocument()
    // 也不得出现"会议 / 议题"等日程语义内容
    expect(screen.queryByText(/会议|议题|日程安排表/)).not.toBeInTheDocument()
  })

  it('四态：props 可切换四态（便于后续后端落地时替换）', async () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(<SchedulePanel availability={SCHEDULE_ABSENT} state={state} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText(/尚未接入/)).not.toBeInTheDocument()
      unmount()
    }

    let retried = 0
    render(<SchedulePanel availability={SCHEDULE_ABSENT} state="error" onRetry={() => { retried += 1 }} />)
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })
})