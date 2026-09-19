import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from 'antd'
import { PageContainer } from './PageContainer'

const FOUR_STATES = [
  ['loading', '正在加载，请稍候…'],
  ['empty', '暂无内容。'],
  ['error', '加载失败，请稍后再试。'],
  ['forbidden', '你没有查看该内容的权限。'],
] as const

describe('PageContainer', () => {
  it('ready：渲染标题、描述、右上操作区与内容', () => {
    render(
      <PageContainer title="运行概览" description="本周运行情况" extra={<Button>导出</Button>}>
        <div>页面内容</div>
      </PageContainer>,
    )
    expect(screen.getByRole('heading', { level: 2, name: '运行概览' })).toBeInTheDocument()
    expect(screen.getByText('本周运行情况')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /导\s*出/ })).toBeInTheDocument()
    expect(screen.getByText('页面内容')).toBeInTheDocument()
  })

  it('四态：各自渲染可识别文案，且不渲染 children', () => {
    for (const [state, text] of FOUR_STATES) {
      const { unmount } = render(
        <PageContainer title="标题" state={state}>
          <div>页面内容</div>
        </PageContainer>,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('页面内容')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('error 态给重试回调时按钮可用', async () => {
    let retried = 0
    render(
      <PageContainer title="标题" state="error" onRetry={() => { retried += 1 }} />,
    )
    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(retried).toBe(1)
  })

  it('四态可以用自定义说明文案覆盖默认文案', () => {
    render(<PageContainer title="标题" state="forbidden" stateDescription="该页面仅管理员可见。" />)
    expect(screen.getByText('该页面仅管理员可见。')).toBeInTheDocument()
    expect(screen.queryByText('你没有查看该内容的权限。')).not.toBeInTheDocument()
  })
})