import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SkeletonList } from './SkeletonList'

describe('SkeletonList', () => {
  it('加载中：只出现骨架行，**不出现"暂无数据"**', () => {
    const { container } = render(<SkeletonList rows={3} />)
    expect(container.querySelectorAll('.ant-skeleton')).toHaveLength(3)
    expect(screen.queryByText('暂无内容。')).not.toBeInTheDocument()
    expect(screen.queryByText(/暂无/)).not.toBeInTheDocument()
  })

  it('行数可配', () => {
    const { container } = render(<SkeletonList rows={5} />)
    expect(container.querySelectorAll('.ant-skeleton')).toHaveLength(5)
  })

  it('empty：加载结束才进入空态，骨架消失', () => {
    const { container } = render(<SkeletonList state="empty" />)
    expect(screen.getByText('暂无内容。')).toBeInTheDocument()
    expect(container.querySelectorAll('.ant-skeleton')).toHaveLength(0)
  })

  it('error / forbidden：与空态文案可区分，error 可重试', async () => {
    let retried = 0
    const error = render(<SkeletonList state="error" onRetry={() => { retried += 1 }} />)
    expect(screen.getByText('加载失败，请稍后再试。')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
    error.unmount()

    render(<SkeletonList state="forbidden" />)
    expect(screen.getByText('你没有查看该内容的权限。')).toBeInTheDocument()
  })
})