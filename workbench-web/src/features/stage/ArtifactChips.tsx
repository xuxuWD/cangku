/**
 * 对话流内的「产出 chip」（P2c-3 §2.7 事项 K）：由帧里的 `file_changes` 聚合而成。
 *
 * **来源**：由 `admin-web/src/features/stage/ArtifactChips.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（12 处 className）换成 **AntD `Button` + 令牌**，符合 ADR-0003
 * 「禁止用 div 模拟按钮」—— chip 是可点击控件，故用 `Button` 而不是 `Tag`。
 *
 * **纪律（原实现，重写后由用例保证）**：
 * - **数据源 = 帧**（不额外请求）；同一虚拟路径取**最新一次**变更（按 `seq`）；
 * - 点开显示该变更的**有界 diff 摘录**（无摘录则如实告知：删除 / 非文本 / 关闭 diff 通道）；
 * - 截断（`file_changes_truncated`）**显式告知**；无变更帧 ⇒ **不渲染**（不摆假 chip）。
 */
import { useState } from 'react'
import { Button, Space, Typography } from 'antd'
import type { StreamFrame } from '../conversation/types'
import { changeKindLabel } from '../runDetail/types'
import { collectFileChanges, fileChangesTruncated } from './ToolOutputPanels'

export function ArtifactChips({
  frames,
  runId,
  onOpenRunDetail,
}: {
  frames: StreamFrame[]
  runId?: string
  onOpenRunDetail?: (runId: string) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const changes = collectFileChanges(frames)
  if (changes.length === 0) return null

  const latest = new Map<string, (typeof changes)[number]>()
  for (const change of changes) {
    const previous = latest.get(change.virtualPath)
    if (!previous || change.seq >= previous.seq) latest.set(change.virtualPath, change)
  }
  const chips = [...latest.values()]
  const truncated = fileChangesTruncated(frames)

  return (
    <div aria-label="产出">
      <Space wrap size="small" align="center">
        <Typography.Text type="secondary">产出</Typography.Text>
        {chips.map((chip) => {
          const open = expanded === chip.virtualPath
          return (
            <Button
              key={chip.virtualPath}
              size="small"
              aria-expanded={open}
              onClick={() => setExpanded(open ? null : chip.virtualPath)}
            >
              {/* ⚠️ 三段必须**各自独立成节点**（原实现如此）：拼成一整串会让
                  "按字节数取文"的用例取不到，也会让读屏把路径/类型/字节读成一口气的长串。 */}
              <span>{chip.virtualPath}</span>
              {chip.changeKind && <span>{changeKindLabel(chip.changeKind)}</span>}
              {chip.bytes !== null && <span>{`${chip.bytes} B`}</span>}
            </Button>
          )
        })}
        {onOpenRunDetail && runId && (
          <Button type="link" size="small" onClick={() => onOpenRunDetail(runId)}>
            在运行详情中打开
          </Button>
        )}
      </Space>

      {chips
        .filter((chip) => expanded === chip.virtualPath)
        .map((chip) => (
          <div key={`detail:${chip.virtualPath}`}>
            {chip.diffExcerpt ? (
              <pre aria-label={`${chip.virtualPath} 的 diff 摘录`} style={{ margin: 0, overflowX: 'auto' }}>
                {chip.diffExcerpt}
              </pre>
            ) : (
              <Typography.Text type="secondary">
                该变更没有 diff 摘录（删除 / 非文本内容不回传）。
              </Typography.Text>
            )}
          </div>
        ))}

      {truncated && (
        <Typography.Text type="secondary">
          变更条数超过回传上限，已截断（仅展示前若干条，不静默丢弃）。
        </Typography.Text>
      )}
    </div>
  )
}
