// P2c-5 实时流：SSE 行协议解析与帧解码（网页管理台读端的**最小复制实现**，见规格 §2.12 裁定）。
// 契约：docs/api-contract.md「实时流与过程事件（P2b）」——帧格式 `id` / `event` / `data`（JSON），
// 心跳是注释行（`: hb`，不产生事件、不干扰 Last-Event-ID）。
import { createParser } from 'eventsource-parser'
import type { StreamFrame } from './types'

/**
 * SSE `data` → 帧。**坏 JSON / 非法结构一律丢弃**（返回 null）：
 * 不让一帧坏掉整条流（契约的客户端容错口径）。
 */
export function frameFromData(data: string, fallbackKind?: string): StreamFrame | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }
  if (typeof parsed !== 'object' || parsed === null) return null
  const candidate = parsed as { seq?: unknown; kind?: unknown; payload?: unknown; is_terminal?: unknown; run_id?: unknown }
  const seq = typeof candidate.seq === 'number' ? candidate.seq : Number(candidate.seq)
  if (!Number.isFinite(seq)) return null
  const kind = typeof candidate.kind === 'string' && candidate.kind ? candidate.kind : (fallbackKind ?? '')
  const payload =
    typeof candidate.payload === 'object' && candidate.payload !== null
      ? (candidate.payload as Record<string, unknown>)
      : {}
  const runId = typeof candidate.run_id === 'string' && candidate.run_id ? candidate.run_id : undefined
  return {
    seq: Math.trunc(seq),
    kind,
    payload,
    is_terminal: candidate.is_terminal === true,
    ...(runId ? { run_id: runId } : {}),
  }
}

export interface FrameParser {
  feed(chunk: string): void
  reset(): void
}

/**
 * 增量帧解析器（`eventsource-parser` 只做行协议，帧结构由本模块解释）。
 * `maxBufferSize` 防畸形流无限缓冲；超出后解析器进入终止态，后续 feed 被吞掉并计一次丢弃。
 */
export function createFrameParser(
  onFrame: (frame: StreamFrame) => void,
  onDiscard?: (reason: string) => void,
): FrameParser {
  const parser = createParser({
    onEvent: (message) => {
      const frame = frameFromData(message.data, message.event)
      if (frame) onFrame(frame)
      else onDiscard?.('bad_frame')
    },
    onError: (error) => onDiscard?.(error.type),
    maxBufferSize: 512 * 1024,
  })
  return {
    feed(chunk: string) {
      try {
        parser.feed(chunk)
      } catch {
        onDiscard?.('terminated')
      }
    },
    reset() {
      parser.reset()
    },
  }
}