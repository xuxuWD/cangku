import { useCallback, useEffect, useRef, useState } from 'react'
import { listPendingApprovals, SessionExpiredError } from './api'
import type { PendingApproval, PendingApprovalCounts } from './types'

const EMPTY_COUNTS: PendingApprovalCounts = {
  task_approval: 0,
  plan_proposal: 0,
  account_registration: 0,
  total: 0,
}

// 轮询间隔（毫秒）：配置非法或 ≤0 时回退 30 秒。
export function resolvePollIntervalMs(): number {
  const seconds = Number(import.meta.env.VITE_APPROVAL_POLL_SECONDS ?? 30)
  if (!Number.isFinite(seconds) || seconds <= 0) return 30_000
  return seconds * 1000
}

export interface PendingApprovalsState {
  items: PendingApproval[]
  counts: PendingApprovalCounts
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function usePendingApprovals(onSessionExpired?: () => void): PendingApprovalsState {
  const [items, setItems] = useState<PendingApproval[]>([])
  const [counts, setCounts] = useState<PendingApprovalCounts>(EMPTY_COUNTS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const expiredRef = useRef(onSessionExpired)
  expiredRef.current = onSessionExpired

  const refresh = useCallback(async () => {
    try {
      const data = await listPendingApprovals()
      setItems(data.items)
      setCounts(data.counts)
      setError(null)
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        // 会话失效：交给上层清理并要求重新登录。
        expiredRef.current?.()
        return
      }
      setError(err instanceof Error ? err.message : '待办加载失败。')
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  useEffect(() => {
    void refreshRef.current()
    const timer = window.setInterval(() => {
      // 页面不可见时跳过轮询请求，省电。
      if (document.hidden) return
      void refreshRef.current()
    }, resolvePollIntervalMs())
    const handleVisibility = () => {
      if (!document.hidden) void refreshRef.current()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return { items, counts, loading, error, refresh }
}
