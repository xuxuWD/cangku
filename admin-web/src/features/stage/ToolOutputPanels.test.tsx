import { render, screen } from '@testing-library/react'
import type { StreamFrame } from '../conversation/types'
import { FileDiffPanel, TerminalOutputPanel } from './ToolOutputPanels'

const frame = (seq: number, kind: string, payload: Record<string, unknown>): StreamFrame => ({
  seq,
  kind,
  payload,
  is_terminal: false,
})

describe('TerminalOutputPanel（终端输出 · 有界摘录）', () => {
  it('渲染文本摘录与字节数（未截断）', () => {
    render(
      <TerminalOutputPanel
        frames={[frame(1, 'tool.result', { tool_key: 'cmd.run', output_excerpt: 'total 0', output_truncated: false, output_bytes: 7 })]}
      />,
    )
    expect(screen.getByLabelText('执行输出摘录')).toHaveTextContent('total 0')
    expect(screen.getByText(/本次回传 7 字节/)).toBeInTheDocument()
  })

  it('截断必须显式告知（不静默截断）', () => {
    render(
      <TerminalOutputPanel
        frames={[frame(1, 'tool.result', { output_excerpt: 'x'.repeat(20), output_truncated: true, output_bytes: 4096 })]}
      />,
    )
    expect(screen.getByText(/输出超过回传上限，已截断（已读取 4096 字节/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '终端输出' })).toHaveTextContent('已截断')
  })

  it('非文本（无摘录、只有字节数与摘要）⇒ 不显示内容', () => {
    render(
      <TerminalOutputPanel
        frames={[frame(1, 'tool.result', { output_sha256: 'sha256:abcdef', output_truncated: false, output_bytes: 12 })]}
      />,
    )
    expect(screen.queryByLabelText('执行输出摘录')).toBeNull()
    expect(screen.getByText(/非文本输出不落内容/)).toBeInTheDocument()
    expect(screen.getByText(/sha256:abcdef/)).toBeInTheDocument()
  })

  it('无输出帧 ⇒ 不渲染面板（不摆空面板）；未知 / 注入键一律不渲染（白名单）', () => {
    const { container } = render(<TerminalOutputPanel frames={[frame(1, 'tool.call', { step_id: 's-1' })]} />)
    expect(container).toBeEmptyDOMElement()

    render(
      <TerminalOutputPanel
        frames={[frame(2, 'tool.result', { output_excerpt: 'ok', output_secret: 'sk-live-abcdef', api_key: 'sk-abcdef' })]}
      />,
    )
    expect(screen.queryByText(/sk-live-abcdef/)).toBeNull()
    expect(screen.queryByText(/sk-abcdef/)).toBeNull()
  })
})

describe('FileDiffPanel（文件改动 · 有界 diff 摘录）', () => {
  it('渲染虚拟路径 / 变更类型 / 字节 / diff 摘录', () => {
    render(
      <FileDiffPanel
        frames={[
          frame(1, 'tool.result', {
            file_changes: [
              { virtual_path: '/workspace/a.txt', change_kind: 'write', bytes: 12, sha256: 'sha256:aa', diff_excerpt: '+hello' },
            ],
          }),
        ]}
      />,
    )
    expect(screen.getByText('/workspace/a.txt')).toBeInTheDocument()
    expect(screen.getByText('写入')).toBeInTheDocument()
    expect(screen.getByText('12 B')).toBeInTheDocument()
    expect(screen.getByLabelText('/workspace/a.txt 的 diff 摘录')).toHaveTextContent('+hello')
  })

  it('缺 virtual_path 的条目整条丢弃（不猜测）；无 file_changes 则不渲染', () => {
    render(<FileDiffPanel frames={[frame(1, 'tool.result', { file_changes: [{ change_kind: 'delete' }] })]} />)
    expect(screen.queryByRole('region', { name: '文件改动' })).toBeNull()

    const { container } = render(<FileDiffPanel frames={[frame(2, 'tool.result', { output_excerpt: 'ok' })]} />)
    expect(container).toBeEmptyDOMElement()
  })
})