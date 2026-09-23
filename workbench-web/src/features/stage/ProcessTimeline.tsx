/**
 * 过程时间线：帧 `kind` 原值 → 行；payload **只渲染白名单字段**，未知键一律不猜测。
 *
 * **来源**：由 `admin-web/src/features/stage/ProcessTimeline.tsx` 合并移植（行为等价，见下）。
 * 呈现层从**手写 CSS**（`process-timeline` / `process-row` / `text-action` 等 14 处 className）
 * 换成 **AntD + 项目组件库**，符合 ADR-0003「禁止用 div 模拟按钮」。
 *
 * **⚠️ 一条必须守住的安全属性**（原实现的纪律，重写后由用例保证）：
 * payload 里 `args_digest` / `authorization` 之类的键**即使服务端带了也不得渲染** ——
 * 只走 `RUN_EVENT_PAYLOAD_FIELDS` 白名单，**不遍历未知键**。
 *
 * 渲染窗口：时间线最多渲染最近 500 行（§2.13；后端 2000 帧熔断已封顶）。
 */
import { useState } from 'react'
import { Button, Descriptions, Space, Typography } from 'antd'
import { EmptyState, SkeletonList } from '../../components'
import { frameKindLabel } from '../conversation/types'
import type { ConversationErrorShape, StreamFrame, StreamStatus } from '../conversation/types'
import { RUN_EVENT_PAYLOAD_FIELDS } from '../runDetail/types'

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

/** **只按白名单取值** —— 未知键一律忽略（安全属性，不得改成遍历 payload）。 */
function payloadEntries(payload: Record<string, unknown>): Array<{ label: string; value: string }> {
  const entries: Array<{ label: string; value: string }> = []
  for (const field of RUN_EVENT_PAYLOAD_FIELDS) {
    const value = displayValue(payload[field.key])
    if (value !== null) entries.push({ label: field.label, value })
  }
  return entries
}

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
      ? (error?.message ?? '过程读取失败。')
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
    <div>
      <Typography.Text type="secondary" role="status">
        {statusText}
        {frames.length > 0 && ` · 共 ${frames.length} 条`}
      </Typography.Text>

      {status === 'streaming' && frames.length === 0 && <SkeletonList rows={2} state="loading" boxed={false} />}

      {status !== 'streaming' && frames.length === 0 && status !== 'connecting' && (
        <EmptyState
          boxed={false}
          description="暂无过程事件"
          action={
            <Typography.Text type="secondary">
              {noData
                ? '没有可读取的过程数据（可能已过期或尚未产生）。'
                : '发起一次结构化工具调用后，这里会显示逐步过程。'}
            </Typography.Text>
          }
        />
      )}

      {visible.length > 0 && (
        <ol role="log" aria-live="polite" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {visible.map((frame) => {
            const entries = payloadEntries(frame.payload)
            const reason = frame.kind === 'stream.unavailable' ? displayValue(frame.payload.reason) : null
            const isOpen = expanded.has(frame.seq)
            return (
              <li key={frame.seq}>
                <Space wrap size="small">
                  <Typography.Text type="secondary">{`#${frame.seq}`}</Typography.Text>
                  <Typography.Text>{frameKindLabel(frame.kind)}</Typography.Text>
                  {reason && <Typography.Text type="warning">{UNAVAILABLE_REASON_LABELS[reason] ?? reason}</Typography.Text>}
                  {entries.length > 0 && (
                    <Button type="link" size="small" aria-expanded={isOpen} onClick={() => toggle(frame.seq)}>
                      {isOpen ? '收起' : '详情'}
                    </Button>
                  )}
                </Space>
                {isOpen && entries.length > 0 && (
                  <Descriptions
                    column={1}
                    size="small"
                    bordered
                    items={entries.map((entry) => ({ key: entry.label, label: entry.label, children: entry.value }))}
                  />
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
