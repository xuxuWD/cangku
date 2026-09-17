import { useCallback, useEffect, useRef, useState } from 'react'
import { ConversationApiError, ConversationSessionExpiredError, listConversations } from './api'
import { CONVERSATION_PAGE_SIZE, type Conversation } from './types'

export interface ConversationListState {
  items: Conversation[]
  total: number
  offset: number
  loading: boolean
  error: ConversationApiError | null
  /** 加载指定页（offset ≥ 0）；失败不改动已加载列表，只置错误态。 */
  load: (offset: number) => Promise<void>
  refresh: () => Promise<void>
}

/** 会话列表（分页口径与服务端一致；401 ⇒ 交上层清理会话）。 */
export function useConversations(onSessionExpired?: () => void): ConversationListState {
  const [items, setItems] = useState<Conversation[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ConversationApiError | null>(null)

  const expiredRef = useRef(onSessionExpired)
  expiredRef.current = onSessionExpired
  const offsetRef = useRef(offset)
  offsetRef.current = offset

  const load = useCallback(async (nextOffset: number) => {
    setLoading(true)
    setError(null)
    try {
      const data = await listConversations({ limit: CONVERSATION_PAGE_SIZE, offset: Math.max(0, nextOffset) })
      setItems(Array.isArray(data.items) ? data.items : [])
      setTotal(typeof data.total === 'number' ? data.total : 0)
      setOffset(Math.max(0, nextOffset))
    } catch (err) {
      if (err instanceof ConversationSessionExpiredError) {
        // 会话失效：交给上层清理并要求重新登录。
        expiredRef.current?.()
        return
      }
      setError(err instanceof ConversationApiError ? err : new ConversationApiError('会话列表加载失败，请稍后重试。', 0))
    } finally {
      setLoading(false)
    }
  }, [])

  const refresh = useCallback(async () => {
    await load(offsetRef.current)
  }, [load])

  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    void loadRef.current(0)
  }, [])

  return { items, total, offset, loading, error, load, refresh }
}