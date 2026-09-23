import { useEffect, useRef, useState } from 'react'
import { ConversationError, openConversationStream } from './services/conversationService'
import { conversationErrorFromStatus } from './state'
import { createFrameParser } from './stream'
import type { ConversationErrorShape, StreamFrame, StreamStatus } from './types'

export interface RunStream {
  status: StreamStatus
  frames: StreamFrame[]
  lastSeq: number
  error: ConversationErrorShape | null
  /** 连续多轮重连都没有任何新帧（且未终态）⇒ 无可用过程数据（不无限挂长连接）。 */
  noData: boolean
  /** 当前流所属运行号（P2c-2）：显式 `runId` 优先，否则取响应头 `X-Stream-Run-Id` / 帧内 `run_id`。 */
  runId: string | null
}

const EMPTY: RunStream = { status: 'idle', frames: [], lastSeq: 0, error: null, noData: false, runId: null }

/** 帧入 state 的合批窗口（§2.13：流状态与主状态隔离 + ≤100ms 合批）。 */
const FLUSH_INTERVAL_MS = 100
/** 退避上限（§2.3）。 */
const MAX_BACKOFF_MS = 15_000
/** 空转上限：连续多少次「零新帧」的重连后停止（避免对已清理的 run 无限重试）。 */
const MAX_EMPTY_ATTEMPTS = 3

export interface UseRunStreamOptions {
  conversationId?: string
  /** 显式 run（发送响应给出的 `X-Stream-Run-Id`）；缺省 = 该会话最新 run（服务端解析）。 */
  runId?: string
  /** 是否开启（视图可见 + 有会话）。关闭即断开（不后台堆积长连接）。 */
  enabled: boolean
  /** 变化即重连（发送新消息时递增，用于重新发现新 run）。 */
  restartToken?: number
  /** 本次连接是否在**等一个即将出现的 run**（发送进行中）：`true` 时缺 run 不关流，继续等（边执行边看）。 */
  awaitRun?: boolean
  /** 收到终态帧（或服务端以终态关流）时回调一次。 */
  onTerminal?: () => void
}

/**
 * 流读端（P2c-1 §2.3）：`fetch` + 读流 + 增量解析；
 * 断线指数退避重连并携带 `Last-Event-ID` 真增量续播；终态关流；`401/403/404/422` 不重连。
 */
export function useRunStream(options: UseRunStreamOptions): RunStream {
  const { conversationId, runId, enabled, restartToken = 0, awaitRun = false, onTerminal } = options
  const [state, setState] = useState<RunStream>(EMPTY)
  // 运行号解析（P2c-2）：显式 `runId` 优先；否则从响应头 / 帧内 `run_id` 发现（历史会话据此加载概览与审批）。
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(null)

  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal

  useEffect(() => {
    const active = Boolean(conversationId) && enabled
    if (!active) {
      setState(EMPTY)
      setResolvedRunId(null)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    const frames: StreamFrame[] = []
    const queue: StreamFrame[] = []
    let lastSeq = 0
    let terminal = false
    let flushTimer: ReturnType<typeof setTimeout> | null = null
    let discoveredRunId: string | null = runId ?? null
    const noteRunId = (value: string | null | undefined) => {
      if (runId) return // 显式 run（本次发送）优先：不被响应头 / 帧内 `run_id` 覆盖
      const next = value ?? null
      if (!next || next === discoveredRunId) return
      discoveredRunId = next
      if (!cancelled) setResolvedRunId(next)
    }
    // 新连接即重置为「显式 runId 或未知」（会话切换 / 新一轮发送后不残留上一个 run）。
    setResolvedRunId(runId ?? null)
    // 发送进行中（`awaitRun`）⇒ 缺 run 时继续等（边执行边看）；否则缺 run 即关流如实告知。
    const waitingForRun = Boolean(awaitRun)

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
          noteRunId(frame.run_id) // P2c-2：帧内 `run_id`（只增）——覆盖「连接建立时无 run、稍后出现」
          queue.push(frame)
          if (frame.is_terminal) terminal = true
          scheduleFlush(frame.is_terminal)
        })
        let fatal: ConversationErrorShape | null = null
        let retryable = false

        try {
          const response = await openConversationStream({
            conversationId: conversationId as string,
            runId,
            since: attempt === 0 ? 0 : lastSeq,
            signal: controller.signal,
          })
          if (!response.body) {
            // 200 却没有响应体：按**可重试**的瞬时故障处理。
            // （原实现在这里按 `response.status`（=200）映射，会得到"请求未被接受（200）。"
            //   这种说不通的文案 —— 移植时改掉，如实登记。）
            retryable = true
          } else {
            // P2c-2：读端响应头 `X-Stream-Run-Id`（连接建立时已解析到 run 才出现）——
            // 历史会话（未发生本次发送）据此拿到 run，进而加载运行概览与审批。
            const headerRunId = response.headers?.get?.('X-Stream-Run-Id') ?? null
            noteRunId(headerRunId)
            if (!discoveredRunId && !waitingForRun) {
              // 连接建立时服务端**没有 run**（无响应头）且本次并非「发送进行中」⇒ 没有可回放的过程数据：
              // 关流并如实告知，**不挂无限长连接空等**一个可能永远不出现的 run（发送 / 决议会重开读端）。
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
        } catch (error) {
          if (cancelled) return
          // 基座请求层把 `!ok` 变成**异常**（不再返回非 2xx 的 Response）⇒ 这里按状态码分流。
          // 与 admin-web 的 `conversationErrorFromStatus(response.status)` **同义**：
          // 401/403/404/422 致命、立即停；网络失败 / 5xx 才退避重连。
          const status = error instanceof ConversationError ? error.status : 0
          const mapped = conversationErrorFromStatus(status)
          if (mapped.retryable) retryable = true
          else fatal = mapped
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
  }, [conversationId, runId, enabled, restartToken])

  return { ...state, runId: resolvedRunId }
}