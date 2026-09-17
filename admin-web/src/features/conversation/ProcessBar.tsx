import { useState } from 'react'
import { frameKindLabel, type ConversationErrorShape, type StreamFrame, type StreamStatus } from './types'
import { ProcessTimeline } from '../stage/ProcessTimeline'

/**
 * 过程折叠条（P2c-1 §2.5）：运行期间一行摘要（可展开），终态后收为一行保留。
 * 无过程数据时不占版面（返回 null），不摆空壳。
 */
export function ProcessBar({
  frames,
  status,
  error,
  noData,
}: {
  frames: StreamFrame[]
  status: StreamStatus
  error: ConversationErrorShape | null
  noData: boolean
}) {
  const [open, setOpen] = useState(false)

  const hasProcessData = frames.length > 0
  if (!hasProcessData && status !== 'streaming' && status !== 'connecting') return null

  const latest = frames.length > 0 ? frames[frames.length - 1] : null
  const headline = status === 'streaming' ? '执行中' : status === 'connecting' ? '连接中' : noData ? '过程不可用' : '过程'

  return (
    <div className="process-bar">
      <div className="process-bar__line">
        <span className={`process-bar__dot ${status === 'streaming' ? 'active' : ''}`} aria-hidden="true" />
        <strong>{headline}</strong>
        {latest && <span>{frameKindLabel(latest.kind)}</span>}
        <span>共 {frames.length} 条</span>
        <button className="text-action" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? '收起' : '展开'}
        </button>
      </div>
      {open && <ProcessTimeline frames={frames} status={status} error={error} noData={noData} />}
    </div>
  )
}