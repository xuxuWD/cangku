import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('默认空态：使用统一空态文案', () => {
    render(<EmptyState />)
    expect(screen.getByText('暂无内容。')).toBeInTheDocument()
  })

  it('可以覆盖文案，并渲染主操作按钮', async () => {
    let clicked = 0
    render(<EmptyState description="还没有数字员工。" actionText="新建数字员工" onAction={() => { clicked += 1 }} />)
    expect(screen.getByText('还没有数字员工。')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '新建数字员工' }))
    expect(clicked).toBe(1)
  })

  it('四态：loading / error（含重试）/ forbidden 都能呈现', async () => {
    let retried = 0
    const { unmount } = render(<EmptyState state="loading" />)
    expect(screen.getByText('正在加载，请稍候…')).toBeInTheDocument()
    unmount()

    const error = render(<EmptyState state="error" onRetry={() => { retried += 1 }} />)
    expect(screen.getByText('加载失败，请稍后再试。')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
    error.unmount()

    render(<EmptyState state="forbidden" />)
    expect(screen.getByText('你没有查看该内容的权限。')).toBeInTheDocument()
  })
})