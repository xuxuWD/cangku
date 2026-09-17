import { useState } from 'react'
import { frameKindLabel } from '../conversation/types'
import type { ConversationErrorShape, StreamFrame, StreamStatus } from '../conversation/types'
import { RUN_EVENT_PAYLOAD_FIELDS } from '../runDetail/types'

/** 渲染窗口（§2.13：时间线最多渲染最近 500 行；后端 2000 帧熔断已封顶）。 */
const RENDER_WINDOW = 500

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  frame_limit: '过程帧数超上限',
  byte_limit: '过程数据量超上限',
  write_failed: '过程写入失败',
  stalled: '运行长时间无更新',
}

function displayValue(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return null
}

function payloadEntries(payload: Record<string, unknown>): Array<{ label: string; value: string }> {
  const entries: Array<{ label: string; value: string }> = []
  for (const field of RUN_EVENT_PAYLOAD_FIELDS) {
    const value = displayValue(payload[field.key])
    if (value !== null) entries.push({ label: field.label, value })
  }
  return entries
}

/** 过程时间线：帧 `kind` 原值 → 行；payload **只渲染白名单字段**，未知键一律不猜测。 */
export function ProcessTimeline({
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
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())

  const toggle = (seq: number) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(seq)) next.delete(seq)
      else next.add(seq)
      return next
    })

  const visible = frames.length > RENDER_WINDOW ? frames.slice(-RENDER_WINDOW) : frames

  const statusText =
    status === 'error'
      ? error?.message ?? '过程读取失败。'
      : status === 'streaming'
        ? '正在接收过程…'
        : status === 'connecting'
          ? '正在连接过程…'
          : noData
            ? '无可用过程数据'
            : frames.length === 0
              ? '暂无过程'
              : '过程已结束'

  return (
    <div className="process-timeline">
      <p className="process-timeline__status" role="status">
        {statusText}
        {frames.length > 0 && <span> · 共 {frames.length} 条</span>}
      </p>
      {status === 'streaming' && frames.length === 0 && (
        <div className="loading-state" role="status">
          <span className="loading-dot" />
          正在接收过程…
        </div>
      )}
      {status !== 'streaming' && frames.length === 0 && status !== 'connecting' && (
        <div className="empty-state">
          <strong>暂无过程事件</strong>
          <span>{noData ? '没有可读取的过程数据（可能已过期或尚未产生）。' : '发起一次结构化工具调用后，这里会显示逐步过程。'}</span>
        </div>
      )}
      {visible.length > 0 && (
        <ol className="process-timeline__list" role="log" aria-live="polite">
          {visible.map((frame) => {
            const entries = payloadEntries(frame.payload)
            const reason = frame.kind === 'stream.unavailable' ? displayValue(frame.payload.reason) : null
            const isOpen = expanded.has(frame.seq)
            return (
              <li className="process-row" key={frame.seq}>
                <div className="process-row__line">
                  <span className="process-row__seq">#{frame.seq}</span>
                  <span className="process-row__kind">{frameKindLabel(frame.kind)}</span>
                  {reason && <span className="process-row__reason">{UNAVAILABLE_REASON_LABELS[reason] ?? reason}</span>}
                  {entries.length > 0 && (
                    <button className="text-action" type="button" aria-expanded={isOpen} onClick={() => toggle(frame.seq)}>
                      {isOpen ? '收起' : '详情'}
                    </button>
                  )}
                </div>
                {isOpen && entries.length > 0 && (
                  <dl className="process-row__payload">
                    {entries.map((entry) => (
                      <div className="process-row__field" key={entry.label}>
                        <dt>{entry.label}</dt>
                        <dd>{entry.value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}