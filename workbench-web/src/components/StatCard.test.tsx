import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StatCard } from './StatCard'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

describe('StatCard', () => {
  it('就绪：渲染数值、单位与趋势', () => {
    render(<StatCard label="本周完成" value={12} unit="条" trend={{ direction: 'up', text: '较上周 +3' }} />)
    expect(screen.getByText('本周完成')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('条')).toBeInTheDocument()
    expect(screen.getByText(/较上周 \+3/)).toBeInTheDocument()
  })

  it('四态：各自渲染可识别文案，且不显示数值与趋势', () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(
        <StatCard label="本周完成" value={12} unit="条" trend={{ direction: 'up', text: '较上周 +3' }} state={state} />,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('12')).not.toBeInTheDocument()
      expect(screen.queryByText(/较上周 \+3/)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('四态：error 的重试按钮可用', async () => {
    let retried = 0
    render(<StatCard label="本周完成" state="error" onRetry={() => { retried += 1 }} />)
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('状态保真：未配置 / 样本不足 / 未验证都如实展示，且不显示 0、不带趋势', () => {
    const cases = [
      ['not_configured', '未配置'],
      ['insufficient_sample', '样本不足'],
      ['unverified', '未验证'],
    ] as const

    for (const [presence, text] of cases) {
      const { unmount } = render(
        <StatCard label="满意度" presence={presence} unit="分" trend={{ direction: 'up', text: '上升' }} />,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('0')).not.toBeInTheDocument()
      expect(screen.queryByText('上升')).not.toBeInTheDocument()
      expect(screen.queryByText('分')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('没有数值时显示"暂无"，而不是 0', () => {
    render(<StatCard label="平均时长" value={undefined} unit="分钟" />)
    expect(screen.getByText('暂无')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})