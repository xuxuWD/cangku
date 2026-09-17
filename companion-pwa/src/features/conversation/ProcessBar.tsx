import { useState } from 'react'
import type { ConversationApiError } from './api'
import { frameKindLabel, type StreamFrame, type StreamStatus } from './types'

/** 渲染窗口（§2.13：最多渲染最近 500 行；后端帧数熔断已封顶）。 */
const RENDER_WINDOW = 500

/**
 * 过程折叠条（PWA 简化版，§2.12）：运行期间一行摘要（可展开），终态后收为一行保留。
 * **简化口径**：只渲染帧标签（不渲染 payload 明细字段）；无过程数据时不占版面（返回 null），不摆空壳。
 */
export function ProcessBar({
  frames,
  status,
  error,
  noData,
}: {
  frames: StreamFrame[]
  status: StreamStatus
  error: ConversationApiError | null
  noData: boolean
}) {
  const [open, setOpen] = useState(false)

  const hasProcessData = frames.length > 0
  if (!hasProcessData && status !== 'streaming' && status !== 'connecting') return null

  const latest = frames.length > 0 ? frames[frames.length - 1] : null
  const headline = status === 'streaming' ? '执行中' : status === 'connecting' ? '连接中' : noData ? '过程不可用' : '过程'
  const visible = frames.length > RENDER_WINDOW ? frames.slice(-RENDER_WINDOW) : frames

  return (
    <div className="process-bar">
      <div className="process-bar__line">
        <span className={`process-bar__dot ${status === 'streaming' ? 'active' : ''}`} aria-hidden="true" />
        <strong>{headline}</strong>
        {latest && <span className="process-bar__latest">{frameKindLabel(latest.kind)}</span>}
        <span className="process-bar__count">共 {frames.length} 条</span>
        <button className="process-bar__toggle" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? '收起' : '展开'}
        </button>
      </div>
      {open && status === 'error' && error && (
        <p className="process-bar__error" role="status">
          {error.message}
        </p>
      )}
      {open && visible.length > 0 && (
        <ol className="process-bar__list" role="log" aria-live="polite">
          {visible.map((frame) => (
            <li className="process-bar__row" key={frame.seq}>
              <span className="process-bar__seq">#{frame.seq}</span>
              <span>{frameKindLabel(frame.kind)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}