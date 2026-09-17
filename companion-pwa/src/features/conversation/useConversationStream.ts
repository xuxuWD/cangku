import { useEffect, useRef, useState } from 'react'
import { ConversationApiError, conversationErrorFromStatus, openConversationStream } from './api'
import { createFrameParser } from './stream'
import type { StreamFrame, StreamStatus } from './types'

export interface ConversationStream {
  status: StreamStatus
  frames: StreamFrame[]
  lastSeq: number
  error: ConversationApiError | null
  /** 连接建立时该会话没有任何 run（无 `X-Stream-Run-Id` 响应头）⇒ 无可用过程数据（不挂空连接）。 */
  noData: boolean
}

const EMPTY: ConversationStream = { status: 'idle', frames: [], lastSeq: 0, error: null, noData: false }

/** 帧入 state 的合批窗口（§2.13：流状态与主状态隔离 + ≤100ms 合批）。 */
const FLUSH_INTERVAL_MS = 100
/** 退避上限（§2.3）。 */
const MAX_BACKOFF_MS = 15_000
/** 空转上限：连续多少次「零新帧」的重连后停止（避免对已清理的 run 无限重试）。 */
const MAX_EMPTY_ATTEMPTS = 3

export interface UseConversationStreamOptions {
  conversationId?: string
  /** 是否开启（有会话 + 视图可见）。关闭即断开（不后台堆积长连接）。 */
  enabled: boolean
  /** 变化即重连（进入会话回放 / 发送后尾随新 run）。 */
  restartToken?: number
  /** 收到终态帧时回调一次（面板据此重取消息与列表）。 */
  onTerminal?: () => void
  /** 读端 401 ⇒ 交上层清理会话（不重连）。 */
  onSessionExpired?: () => void
}

/**
 * 简化流读端（§2.12 裁定；网页管理台读端的最小复制）：
 * `fetch` + 读流 + 增量解析；断线指数退避重连并携带 `Last-Event-ID` 真增量续播；
 * 终态关流；会话无 run ⇒ 关流 + `noData`；`401/403/404/422` 不重连。
 */
export function useConversationStream(options: UseConversationStreamOptions): ConversationStream {
  const { conversationId, enabled, restartToken = 0, onTerminal, onSessionExpired } = options
  const [state, setState] = useState<ConversationStream>(EMPTY)

  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal
  const expiredRef = useRef(onSessionExpired)
  expiredRef.current = onSessionExpired

  useEffect(() => {
    const active = Boolean(conversationId) && enabled
    if (!active) {
      setState(EMPTY)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    const frames: StreamFrame[] = []
    const queue: StreamFrame[] = []
    let lastSeq = 0
    let terminal = false
    let flushTimer: ReturnType<typeof setTimeout> | null = null

    const flush = () => {
      flushTimer = null
      if (queue.length === 0) return
      frames.push(...queue.splice(0, queue.length))
      setState((old) => ({ ...old, frames: [...frames], lastSeq }))
    }
    const scheduleFlush = (immediate: boolean) => {
      if (immediate) {
        if (flushTimer !== null) clearTimeout(flushTimer)
        flush()
        return
      }
      if (flushTimer === null) flushTimer = setTimeout(flush, FLUSH_INTERVAL_MS)
    }

    setState({ ...EMPTY, status: 'connecting' })

    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          controller.signal.removeEventListener('abort', abort)
          resolve()
        }, ms)
        const abort = () => {
          clearTimeout(timer)
          resolve()
        }
        controller.signal.addEventListener('abort', abort, { once: true })
      })

    const run = async () => {
      let attempt = 0
      let emptyAttempts = 0
      while (!cancelled) {
        let framesThisAttempt = 0
        const parser = createFrameParser((frame) => {
          framesThisAttempt += 1
          lastSeq = Math.max(lastSeq, frame.seq)
          queue.push(frame)
          if (frame.is_terminal) terminal = true
          scheduleFlush(frame.is_terminal)
        })
        let fatal: ConversationApiError | null = null
        let retryable = false

        try {
          const response = await openConversationStream({
            conversationId: conversationId as string,
            since: attempt === 0 ? 0 : lastSeq,
            signal: controller.signal,
          })
          if (!response.ok || !response.body) {
            const mapped = conversationErrorFromStatus(response.status)
            if (mapped.retryable) retryable = true
            else fatal = mapped
          } else {
            // P2c-2 响应头：连接建立时已解析到当前 run 才出现；没有 ⇒ 会话尚无过程数据。
            const hasRun = Boolean(response.headers?.get?.('X-Stream-Run-Id'))
            if (!hasRun) {
              setState((old) => ({ ...old, status: 'closed', frames: [...frames], lastSeq, noData: true }))
              return
            }
            setState((old) => (old.status === 'streaming' ? old : { ...old, status: 'streaming' }))
            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            for (;;) {
              const { done, value } = await reader.read()
              if (done) break
              parser.feed(decoder.decode(value, { stream: true }))
            }
            parser.reset()
            // reader 自然结束：有终态帧即正常收口，否则按「服务端关流」重连续播（如连接寿命到点）。
            if (!terminal) retryable = true
          }
        } catch {
          if (cancelled) return
          retryable = true
        }
        if (cancelled) return

        if (terminal) {
          scheduleFlush(true)
          setState((old) => ({ ...old, status: 'closed', frames: [...frames], lastSeq, noData: false }))
          onTerminalRef.current?.()
          return
        }
        if (fatal) {
          scheduleFlush(true)
          setState((old) => ({ ...old, status: 'error', error: fatal, frames: [...frames], lastSeq }))
          if (fatal.status === 401) expiredRef.current?.()
          return
        }
        if (!retryable) {
          setState((old) => ({ ...old, status: 'closed', frames: [...frames], lastSeq }))
          return
        }

        // 退避重连：起点 = 已收最大 seq（真增量续播）。
        attempt += 1
        if (framesThisAttempt === 0) {
          emptyAttempts += 1
          if (emptyAttempts >= MAX_EMPTY_ATTEMPTS) {
            scheduleFlush(true)
            setState((old) => ({ ...old, status: 'closed', frames: [...frames], lastSeq, noData: true }))
            return
          }
        } else {
          emptyAttempts = 0
        }
        await wait(Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (attempt - 1)))
      }
    }

    void run()
    return () => {
      cancelled = true
      controller.abort()
      if (flushTimer !== null) clearTimeout(flushTimer)
    }
  }, [conversationId, enabled, restartToken])

  return state
}