import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { StreamFrame } from '../../conversation/types'
import { ProcessTimeline } from '../ProcessTimeline'

const frames: StreamFrame[] = [
  {
    seq: 1,
    kind: 'tool.call',
    // `args_digest` / `authorization` 不在展示白名单里：即使服务端/适配器带了，也不得渲染。
    payload: { tool_key: 'cmd.run', args_digest: 'deadbeef', authorization: 'Bearer secret-token' },
    is_terminal: false,
  },
  { seq: 2, kind: 'stream.unavailable', payload: { reason: 'byte_limit' }, is_terminal: true },
]

describe('ProcessTimeline（过程时间线）', () => {
  it('只渲染白名单字段：工具键可见，参数摘要与凭据不外溢', async () => {
    render(<ProcessTimeline frames={frames} status="closed" error={null} noData={false} />)

    expect(screen.getByText('工具调用')).toBeInTheDocument()
    expect(screen.getByText('流已停止（系统告知）')).toBeInTheDocument()
    expect(screen.getByText('过程数据量超上限')).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: '详情' })[0])
    expect(screen.getByText('cmd.run')).toBeInTheDocument()
    expect(screen.queryByText('deadbeef')).not.toBeInTheDocument()
    expect(screen.queryByText(/secret-token/)).not.toBeInTheDocument()
  })

  it('未知 kind 显示为「其他事件」且不猜测 payload（无可展开字段时不出现详情按钮）', () => {
    render(
      <ProcessTimeline
        frames={[{ seq: 7, kind: 'future.event', payload: { secret: 'x' }, is_terminal: false }]}
        status="closed"
        error={null}
        noData={false}
      />,
    )
    expect(screen.getByText('其他事件')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '详情' })).not.toBeInTheDocument()
    expect(screen.queryByText('x')).not.toBeInTheDocument()
  })

  it('空态区分「暂无」与「无可用过程数据」', () => {
    const { rerender } = render(<ProcessTimeline frames={[]} status="closed" error={null} noData={false} />)
    expect(screen.getByText('暂无过程事件')).toBeInTheDocument()

    rerender(<ProcessTimeline frames={[]} status="closed" error={null} noData />)
    expect(screen.getByText('无可用过程数据')).toBeInTheDocument()
  })

  it('读端失败时显示错误态文案', () => {
    render(
      <ProcessTimeline
        frames={[]}
        status="error"
        error={{ status: 404, message: '会话不存在，或不属于当前账号。', retryable: false }}
        noData={false}
      />,
    )
    expect(screen.getByText('会话不存在，或不属于当前账号。')).toBeInTheDocument()
  })
})