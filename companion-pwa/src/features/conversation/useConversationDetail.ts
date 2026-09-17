import { useCallback, useEffect, useRef, useState } from 'react'
import { ConversationApiError, ConversationSessionExpiredError, getConversation } from './api'
import { MESSAGE_PAGE_SIZE, type ConversationDetail } from './types'

export interface ConversationDetailState {
  detail: ConversationDetail | null
  loading: boolean
  error: ConversationApiError | null
  /** 按当前窗口重取（发送后调用：窗口自动扩到「已见总数 + 2」，确保新消息在窗口内）。 */
  reload: () => Promise<void>
  /** 扩大消息窗口（历史消息按 `limit` 递增加载，与服务端分页口径一致）。 */
  loadMore: () => Promise<void>
}

/** 会话详情与消息（切换会话即重置；401 ⇒ 交上层清理会话）。 */
export function useConversationDetail(
  conversationId: string | undefined,
  onSessionExpired?: () => void,
): ConversationDetailState {
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ConversationApiError | null>(null)

  const expiredRef = useRef(onSessionExpired)
  expiredRef.current = onSessionExpired
  const limitRef = useRef(MESSAGE_PAGE_SIZE)
  const detailRef = useRef(detail)
  detailRef.current = detail

  const load = useCallback(async (id: string, limit: number) => {
    setLoading(true)
    setError(null)
    try {
      const data = await getConversation(id, { limit, offset: 0 })
      setDetail(data)
    } catch (err) {
      if (err instanceof ConversationSessionExpiredError) {
        expiredRef.current?.()
        return
      }
      setDetail(null)
      setError(err instanceof ConversationApiError ? err : new ConversationApiError('会话加载失败，请稍后重试。', 0))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    limitRef.current = MESSAGE_PAGE_SIZE
    setDetail(null)
    setError(null)
    if (conversationId) void load(conversationId, MESSAGE_PAGE_SIZE)
  }, [conversationId, load])

  const reload = useCallback(async () => {
    if (!conversationId) return
    const next = Math.max(limitRef.current, (detailRef.current?.messages_total ?? 0) + 2)
    limitRef.current = next
    await load(conversationId, next)
  }, [conversationId, load])

  const loadMore = useCallback(async () => {
    if (!conversationId) return
    const next = limitRef.current + MESSAGE_PAGE_SIZE
    limitRef.current = next
    await load(conversationId, next)
  }, [conversationId, load])

  return { detail, loading, error, reload, loadMore }
}