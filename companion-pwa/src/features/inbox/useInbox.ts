import { useCallback, useEffect, useRef, useState } from 'react'
import { InboxSessionExpiredError, listInbox } from './api'
import type { InboxItem } from './types'

// 轮询间隔（毫秒）：配置非法或 ≤0 时回退 30 秒。
export function resolveInboxPollIntervalMs(): number {
  const seconds = Number(import.meta.env.VITE_INBOX_POLL_SECONDS ?? 30)
  if (!Number.isFinite(seconds) || seconds <= 0) return 30_000
  return seconds * 1000
}

export interface InboxState {
  items: InboxItem[]
  unreadCount: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useInbox(onSessionExpired?: () => void): InboxState {
  const [items, setItems] = useState<InboxItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const expiredRef = useRef(onSessionExpired)
  expiredRef.current = onSessionExpired

  const refresh = useCallback(async () => {
    try {
      const data = await listInbox(false, 20)
      setItems(Array.isArray(data.items) ? data.items : [])
      setUnreadCount(typeof data.unread_count === 'number' ? data.unread_count : 0)
      setError(null)
    } catch (err) {
      if (err instanceof InboxSessionExpiredError) {
        // 会话失效：交给上层清理并要求重新登录。
        expiredRef.current?.()
        return
      }
      setError(err instanceof Error ? err.message : '通知加载失败。')
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
    }, resolveInboxPollIntervalMs())
    const handleVisibility = () => {
      if (!document.hidden) void refreshRef.current()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return { items, unreadCount, loading, error, refresh }
}
