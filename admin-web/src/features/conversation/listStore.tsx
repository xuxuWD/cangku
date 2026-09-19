import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createConversation, listConversations } from './api'
import { asConversationError } from './state'
import {
  CONVERSATION_PAGE_SIZE,
  type Conversation,
  type ConversationErrorShape,
  type ConversationStatus,
} from './types'

/**
 * 会话列表的**单一可信来源**（前端真源 §2.17.3）：
 * 应用里由 `ConversationListProvider` 在 App 层持有，左栏与会话页读**同一份**状态，
 * 写操作后由本状态统一刷新；**不允许两处各自调用 `listConversations`**
 * （否则会出现"左栏新建了、页内列表不刷新"）。
 */
export interface ConversationListValue {
  conversations: Conversation[]
  total: number
  statusFilter: ConversationStatus | 'all'
  offset: number
  loading: boolean
  error: ConversationErrorShape | null
  load: (status: ConversationStatus | 'all', offset: number) => Promise<void>
  /** 按**当前**筛选与偏移重新拉取（新建 / 归档 / 删除 / 成员变更后的统一刷新入口）。 */
  reload: () => Promise<void>
  /** 新建会话并返回其 id；**不负责跳转**（跳转由调用方决定）。 */
  create: () => Promise<string>
}

const ConversationListContext = createContext<ConversationListValue | null>(null)

/**
 * 列表状态的实现体。`autoLoad` 决定是否在挂载时自动拉一次：
 * Provider 传 `true`；独立渲染（组件单测等，无 Provider）时传 `false`，避免凭空发请求。
 */
function useConversationListSource(autoLoad: boolean): ConversationListValue {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<ConversationStatus | 'all'>('all')
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(autoLoad)
  const [error, setError] = useState<ConversationErrorShape | null>(null)

  // `reload()` 要读"当前"筛选与偏移；用 ref 持有，避免把回调绑死在每次都变的 state 上。
  const current = useRef({ statusFilter, offset })
  current.current = { statusFilter, offset }

  const load = useCallback(async (status: ConversationStatus | 'all', nextOffset: number) => {
    setLoading(true)
    setError(null)
    try {
      const data = await listConversations({
        status: status === 'all' ? undefined : status,
        limit: CONVERSATION_PAGE_SIZE,
        offset: nextOffset,
      })
      // 服务端字段缺失时回落为空列表 / 0，不凭空造数据。
      setConversations(Array.isArray(data.items) ? data.items : [])
      setTotal(typeof data.total === 'number' ? data.total : 0)
      setStatusFilter(status)
      setOffset(nextOffset)
      setLoading(false)
    } catch (err) {
      setLoading(false)
      setError(asConversationError(err))
    }
  }, [])

  const reload = useCallback(() => load(current.current.statusFilter, current.current.offset), [load])

  const create = useCallback(async () => {
    // 新建不需要选入员工：`agent_key` 缺省即用默认员工（与既有行为逐字一致）。
    const created = await createConversation({})
    // 新建后统一回第一页刷新：新会话按更新时间排序，必然出现在首页。
    await load(current.current.statusFilter, 0)
    return created.conversation_id
  }, [load])

  useEffect(() => {
    if (autoLoad) void load('all', 0)
  }, [autoLoad, load])

  return useMemo<ConversationListValue>(
    () => ({ conversations, total, statusFilter, offset, loading, error, load, reload, create }),
    [conversations, total, statusFilter, offset, loading, error, load, reload, create],
  )
}

export function ConversationListProvider({ children }: { children: ReactNode }) {
  const value = useConversationListSource(true)
  return <ConversationListContext.Provider value={value}>{children}</ConversationListContext.Provider>
}

export function useConversationList(): ConversationListValue {
  const shared = useContext(ConversationListContext)
  // 没有 Provider 时（例如组件单测直接渲染）自持一份，行为一致、只是不与其它消费者共享。
  // `autoLoad` 两者互斥 ⇒ 有 Provider 时不会重复拉一次列表。
  const standalone = useConversationListSource(shared === null)
  return shared ?? standalone
}
