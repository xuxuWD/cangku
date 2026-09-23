import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { StreamFrame } from '../../conversation/types'
import { ArtifactChips } from '../ArtifactChips'

const frame = (seq: number, kind: string, payload: Record<string, unknown>): StreamFrame => ({
  seq,
  kind,
  payload,
  is_terminal: false,
})

describe('ArtifactChips（产出 chip · 帧驱动）', () => {
  it('无变更帧 ⇒ 不渲染（不摆假 chip）', () => {
    const { container } = render(<ArtifactChips frames={[frame(1, 'tool.result', { output_excerpt: 'ok' })]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('按虚拟路径聚合，同一路径取最新一次变更（seq 大者胜）', () => {
    render(
      <ArtifactChips
        frames={[
          frame(1, 'tool.result', {
            file_changes: [{ virtual_path: '/workspace/a.txt', change_kind: 'created', bytes: 10, sha256: 'sha256:a' }],
          }),
          frame(2, 'tool.result', {
            file_changes: [{ virtual_path: '/workspace/a.txt', change_kind: 'overwritten', bytes: 20, sha256: 'sha256:b' }],
          }),
        ]}
      />,
    )
    expect(screen.getByRole('button', { name: /\/workspace\/a\.txt/ })).toHaveTextContent('覆盖')
    expect(screen.getByText('20 B')).toBeInTheDocument()
    expect(screen.queryByText('10 B')).toBeNull()
  })

  it('点开显示有界 diff 摘录；无摘录如实告知（删除 / 非文本 / 关闭 diff 通道）', async () => {
    render(
      <ArtifactChips
        frames={[
          frame(1, 'tool.result', {
            file_changes: [
              { virtual_path: '/workspace/a.txt', change_kind: 'created', bytes: 5, sha256: 'sha256:a', diff_excerpt: '+hello' },
            ],
          }),
          frame(2, 'tool.result', {
            file_changes: [{ virtual_path: '/workspace/gone.txt', change_kind: 'deleted', bytes: 3, sha256: 'sha256:c' }],
          }),
        ]}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /\/workspace\/a\.txt/ }))
    expect(screen.getByLabelText('/workspace/a.txt 的 diff 摘录')).toHaveTextContent('+hello')

    await userEvent.click(screen.getByRole('button', { name: /\/workspace\/gone\.txt/ }))
    expect(screen.getByText(/该变更没有 diff 摘录/)).toBeInTheDocument()
  })

  it('截断必须显式告知（`file_changes_truncated`）', () => {
    render(
      <ArtifactChips
        frames={[
          frame(1, 'tool.result', {
            file_changes: [{ virtual_path: '/workspace/a.txt', change_kind: 'created', bytes: 1, sha256: 'sha256:a' }],
            file_changes_truncated: true,
          }),
        ]}
      />,
    )
    expect(screen.getByText(/变更条数超过回传上限，已截断/)).toBeInTheDocument()
  })

  it('缺虚拟路径的条目整条丢弃；注入键不渲染（白名单）', () => {
    render(
      <ArtifactChips
        frames={[
          frame(1, 'tool.result', {
            file_changes: [
              { change_kind: 'created', bytes: 1, secret: 'sk-live-abcdef' },
              { virtual_path: '/workspace/ok.txt', change_kind: 'created', bytes: 1, sha256: 'sha256:a', api_key: 'sk-abcdef' },
            ],
          }),
        ]}
      />,
    )
    expect(screen.getByRole('button', { name: /\/workspace\/ok\.txt/ })).toBeInTheDocument()
    expect(screen.queryByText(/sk-live-abcdef/)).toBeNull()
    expect(screen.queryByText(/sk-abcdef/)).toBeNull()
  })

  it('有 run 时可跳运行详情（回调只透传 run_id）', async () => {
    const opened: string[] = []
    render(
      <ArtifactChips
        frames={[
          frame(1, 'tool.result', {
            file_changes: [{ virtual_path: '/workspace/a.txt', change_kind: 'created', bytes: 1, sha256: 'sha256:a' }],
          }),
        ]}
        runId="run-9"
        onOpenRunDetail={(runId) => opened.push(runId)}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: '在运行详情中打开' }))
    expect(opened).toEqual(['run-9'])
  })
})