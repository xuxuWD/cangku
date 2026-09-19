import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ContentState } from './ContentState'

describe('ContentState 四态占位', () => {
  it('loading：渲染转圈与默认文案', () => {
    render(<ContentState state="loading" />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
  })

  it('empty：渲染空态与默认文案', () => {
    render(<ContentState state="empty" />)
    expect(screen.getByText('暂无内容。')).toBeInTheDocument()
  })

  it('empty：可以覆盖说明文案（占位页用的就是这条路径）', () => {
    render(<ContentState state="empty" description="「知识库」尚未接入（第 4 轮实现）。" />)
    expect(screen.getByText('「知识库」尚未接入（第 4 轮实现）。')).toBeInTheDocument()
  })

  it('error：渲染错误态文案，没有重试回调时不出现重试按钮', () => {
    render(<ContentState state="error" />)
    expect(screen.getByText('出错了')).toBeInTheDocument()
    expect(screen.getByText('加载失败，请稍后再试。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /重\s*试/ })).not.toBeInTheDocument()
  })

  it('error：给了重试回调就出现重试按钮，点击能触发', async () => {
    let retried = 0
    render(<ContentState state="error" onRetry={() => { retried += 1 }} />)
    // AntD 会在两个汉字之间自动留空（"重 试"），所以用正则匹配可访问名。
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('forbidden：渲染无权限态文案', () => {
    render(<ContentState state="forbidden" />)
    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText('你没有查看该内容的权限。')).toBeInTheDocument()
  })
})