import { useCallback, useEffect, useState } from 'react'
import type { ApiErrorShape } from '../inbox/types'
import { asInboxError } from '../inbox/state'
import { subscribeApprovalDecided } from '../runDetail/approvalEvents'
import { listPendingApprovals } from './api'
import { EMPTY_PENDING_COUNTS, type PendingApprovalCounts, type PendingApprovalItem } from './types'

export interface PendingApprovalsState {
  items: PendingApprovalItem[]
  counts: PendingApprovalCounts
  loading: boolean
  error: ApiErrorShape | null
  reload: () => void
}

/**
 * 「待我审批」聚合（S5）：**首页指标卡与员工页横幅共用本 hook** ⇒ 两处永远同源同数。
 *
 * 三条纪律：
 *  * 非审批角色由服务端返回 200 + 空列表 + 全 0 ⇒ 界面直接显示「暂无待办」，不报错；
 *  * 首屏轮询（默认 60 秒）只在 `enabled`（= 页面可见）时进行；
 *  * 任一处决议后由 `approvalEvents` 广播即时刷新，不必等下一个轮询周期。
 */
export function usePendingApprovals(options?: { enabled?: boolean; pollMs?: number }): PendingApprovalsState {
  const enabled = options?.enabled ?? true
  const pollMs = options?.pollMs ?? 60_000
  const [items, setItems] = useState<PendingApprovalItem[]>([])
  const [counts, setCounts] = useState<PendingApprovalCounts>(EMPTY_PENDING_COUNTS)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<ApiErrorShape | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    void (async () => {
      try {
        const data = await listPendingApprovals()
        if (cancelled) return
        const nextItems = Array.isArray(data.items) ? data.items : []
        setItems(nextItems)
        setCounts(
          data.counts && typeof data.counts.total === 'number'
            ? data.counts
            : { ...EMPTY_PENDING_COUNTS, total: nextItems.length },
        )
        setError(null)
      } catch (cause) {
        if (!cancelled) setError(asInboxError(cause))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [enabled, nonce])

  useEffect(() => {
    if (!enabled || pollMs <= 0) return
    const timer = window.setInterval(() => setNonce((value) => value + 1), pollMs)
    return () => window.clearInterval(timer)
  }, [enabled, pollMs])

  useEffect(() => {
    if (!enabled) return
    return subscribeApprovalDecided(() => setNonce((value) => value + 1))
  }, [enabled])

  return { items, counts, loading, error, reload }
}

/** 兼容：调用方只关心错误文案时可统一走这里（与通知页同一套中文口径）。 */
export function pendingApprovalsErrorMessage(error: ApiErrorShape | null): string | null {
  return error ? error.message : null
}