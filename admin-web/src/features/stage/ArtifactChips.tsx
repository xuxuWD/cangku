import { useState } from 'react'
import type { StreamFrame } from '../conversation/types'
import { changeKindLabel } from '../runDetail/types'
import { collectFileChanges, fileChangesTruncated } from './ToolOutputPanels'

/**
 * 对话流内的「产出 chip」（P2c-3 §2.7 事项 K）：由帧里的 `file_changes` 聚合而成。
 *
 * 纪律：
 * - **数据源 = 帧**（不额外请求）；同一虚拟路径取**最新一次**变更（按 `seq`）；
 * - 点开显示该变更的**有界 diff 摘录**（无摘录如实告知：删除 / 非文本 / 关闭 diff 通道）；
 * - 截断（`file_changes_truncated`）**显式告知**；无变更帧 ⇒ **不渲染**（不摆假 chip）。
 */
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
    <div className="artifact-chips" aria-label="产出">
      <div className="artifact-chips__row">
        <span className="artifact-chips__title">产出</span>
        {chips.map((chip) => {
          const open = expanded === chip.virtualPath
          return (
            <button
              className="artifact-chip"
              type="button"
              key={chip.virtualPath}
              aria-expanded={open}
              onClick={() => setExpanded(open ? null : chip.virtualPath)}
            >
              <span className="artifact-chip__path">{chip.virtualPath}</span>
              {chip.changeKind && <span className="artifact-chip__kind">{changeKindLabel(chip.changeKind)}</span>}
              {chip.bytes !== null && <span className="artifact-chip__bytes">{chip.bytes} B</span>}
            </button>
          )
        })}
        {onOpenRunDetail && runId && (
          <button className="text-action" type="button" onClick={() => onOpenRunDetail(runId)}>
            在运行详情中打开
          </button>
        )}
      </div>

      {chips
        .filter((chip) => expanded === chip.virtualPath)
        .map((chip) => (
          <div className="artifact-chip__detail" key={`detail:${chip.virtualPath}`}>
            {chip.diffExcerpt ? (
              <pre className="file-change__diff" aria-label={`${chip.virtualPath} 的 diff 摘录`}>
                {chip.diffExcerpt}
              </pre>
            ) : (
              <p className="stage-hint">该变更没有 diff 摘录（删除 / 非文本内容不回传）。</p>
            )}
          </div>
        ))}

      {truncated && (
        <p className="stage-hint">变更条数超过回传上限，已截断（仅展示前若干条，不静默丢弃）。</p>
      )}
    </div>
  )
}