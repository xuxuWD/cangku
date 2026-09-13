import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import {
  archiveConversation,
  createConversation,
  getConversation,
  listConversations,
  sendConversationMessage,
} from './api'
import { asConversationError, initialConversationState } from './state'
import {
  CONVERSATION_PAGE_SIZE,
  MAX_MESSAGE_LENGTH,
  MESSAGE_PAGE_SIZE,
  STUB_NOTICE,
  conversationStatusLabel,
  conversationTitle,
  formatMessageTime,
  roleLabel,
  type ConversationState,
  type ConversationStatus,
} from './types'

const STATUS_FILTERS: Array<{ value: ConversationStatus | 'all'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '进行中' },
  { value: 'archived', label: '已归档' },
]

// 每条消息生成一个新幂等键（§3.2 第四条）：同一键重放由服务端返回既有结果，
// 因此重试/双击不会产生第二次真实执行。优先用 `crypto.randomUUID`，不可用时回落。
function newIdempotencyKey(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function ConversationPage({
  conversationId,
  onNavigate,
  onSelectConversation,
}: {
  conversationId?: string
  onNavigate?: (view: AppView) => void
  onSelectConversation: (conversationId: string | undefined) => void
}) {
  const [state, setState] = useState<ConversationState>(initialConversationState)
  const [draft, setDraft] = useState('')
  const [messagesLimit, setMessagesLimit] = useState(MESSAGE_PAGE_SIZE)
  const [creating, setCreating] = useState(false)

  const loadList = useCallback(async (status: ConversationStatus | 'all', offset: number) => {
    setState((old) => ({ ...old, conversationsLoading: true, conversationsError: null }))
    try {
      const data = await listConversations({
        status: status === 'all' ? undefined : status,
        limit: CONVERSATION_PAGE_SIZE,
        offset,
      })
      setState((old) => ({
        ...old,
        conversations: Array.isArray(data.items) ? data.items : [],
        conversationsTotal: typeof data.total === 'number' ? data.total : 0,
        statusFilter: status,
        listOffset: offset,
        conversationsLoading: false,
        conversationsError: null,
      }))
    } catch (error) {
      setState((old) => ({ ...old, conversationsLoading: false, conversationsError: asConversationError(error) }))
    }
  }, [])

  const loadDetail = useCallback(async (id: string, limit: number) => {
    setState((old) => ({ ...old, detailLoading: true, detailError: null }))
    try {
      const detail = await getConversation(id, { limit, offset: 0 })
      setState((old) => ({ ...old, detail, detailLoading: false, detailError: null }))
      return detail
    } catch (error) {
      setState((old) => ({ ...old, detail: null, detailLoading: false, detailError: asConversationError(error) }))
      return null
    }
  }, [])

  useEffect(() => { void loadList('all', 0) }, [loadList])

  // URL 里带 conversation 时直接打开该会话；切换会话时清空残留详情与草稿。
  useEffect(() => {
    setDraft('')
    setMessagesLimit(MESSAGE_PAGE_SIZE)
    setState((old) => ({ ...old, detail: null, detailError: null, sendError: null }))
    if (conversationId) void loadDetail(conversationId, MESSAGE_PAGE_SIZE)
  }, [conversationId, loadDetail])

  const forbidden = state.conversationsError?.status === 403
  const archived = state.detail?.status !== 'active'
  const canSend = draft.trim().length > 0 && !state.sending && !archived

  const startConversation = async () => {
    setCreating(true)
    setState((old) => ({ ...old, createError: null }))
    try {
      // 新建会话不需要选入员工：agent_key 缺省即用默认员工。
      const created = await createConversation({})
      await loadList(state.statusFilter, state.listOffset)
      onSelectConversation(created.conversation_id)
    } catch (error) {
      setState((old) => ({ ...old, createError: asConversationError(error) }))
    } finally {
      setCreating(false)
    }
  }

  const send = async () => {
    const content = draft.trim()
    if (!conversationId || !canSend || !content) return
    setState((old) => ({ ...old, sending: true, sendError: null }))
    try {
      await sendConversationMessage(conversationId, content, newIdempotencyKey())
      setDraft('')
      // 服务端已确认落库；重取详情拿到真实顺序与最新总数，不做乐观拼接。
      const nextLimit = Math.max(messagesLimit, (state.detail?.messages_total ?? 0) + 2)
      setMessagesLimit(nextLimit)
      await loadDetail(conversationId, nextLimit)
      await loadList(state.statusFilter, state.listOffset)
      setState((old) => ({ ...old, sending: false, sendError: null }))
    } catch (error) {
      setState((old) => ({ ...old, sending: false, sendError: asConversationError(error) }))
    }
  }

  const archive = async () => {
    if (!conversationId || state.archiving) return
    setState((old) => ({ ...old, archiving: true }))
    try {
      const updated = await archiveConversation(conversationId)
      setState((old) => ({
        ...old,
        archiving: false,
        detail: old.detail ? { ...old.detail, status: updated.status, updated_at: updated.updated_at } : old.detail,
        toast: '会话已归档',
      }))
      await loadList(state.statusFilter, state.listOffset)
    } catch (error) {
      setState((old) => ({ ...old, archiving: false, detailError: asConversationError(error) }))
    }
  }

  const loadMoreMessages = () => {
    if (!conversationId) return
    const next = messagesLimit + MESSAGE_PAGE_SIZE
    setMessagesLimit(next)
    void loadDetail(conversationId, next)
  }

  const detail = state.detail

  return (
    <>
      <main className="main-content content-history conversation">
        <div className="page-head">
          <div>
            <h1 className="page-title">对话</h1>
            <p className="page-desc">与数字员工对话。会话与消息的数据模型、权限与审计都是真实的；助手回复是后端标注的桩回复。</p>
          </div>
          <div className="actions">
            <button className="button primary" type="button" disabled={creating || forbidden} onClick={() => void startConversation()}>新建会话</button>
            <button className="button" type="button" disabled={forbidden} onClick={() => void loadList(state.statusFilter, state.listOffset)}>刷新</button>
          </div>
        </div>

        <div className="notice" role="note">
          <div><strong>P1 桩回复</strong><p>{STUB_NOTICE}</p></div>
        </div>

        {state.createError && (
          <div className="notice notice-error" role="alert">
            <div><strong>新建会话失败</strong><p>{state.createError.message}</p></div>
            {state.createError.retryable && <button className="text-action" type="button" onClick={() => void startConversation()}>重新尝试</button>}
          </div>
        )}

        {forbidden ? (
          <div className="notice notice-error" role="alert">
            <div><strong>无法使用对话</strong><p>{state.conversationsError?.message}</p></div>
          </div>
        ) : (
          <div className="conversation-layout">
            <section className="history-panel" aria-label="会话列表">
              <div className="panel-header">
                <h2>会话</h2>
                <span>共 {state.conversationsTotal} 条</span>
              </div>
              <div className="panel-body">
                <div className="segment" role="tablist" aria-label="会话筛选">
                  {STATUS_FILTERS.map((option) => (
                    <button
                      key={option.value}
                      role="tab"
                      type="button"
                      aria-selected={state.statusFilter === option.value}
                      className={state.statusFilter === option.value ? 'active' : ''}
                      onClick={() => void loadList(option.value, 0)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {state.conversationsLoading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话…</div>}

              {!state.conversationsLoading && state.conversationsError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>会话列表加载失败</strong><p>{state.conversationsError.message}</p></div>
                  {state.conversationsError.retryable && <button className="text-action" type="button" onClick={() => void loadList(state.statusFilter, state.listOffset)}>重新尝试</button>}
                </div>
              )}

              {!state.conversationsLoading && !state.conversationsError && state.conversations.length === 0 && (
                <div className="empty-state"><strong>还没有会话</strong><span>点击「新建会话」，或回首页直接说第一句话。</span></div>
              )}

              {!state.conversationsLoading && !state.conversationsError && state.conversations.map((item) => (
                <div
                  className={`history-row conversation-item ${item.conversation_id === conversationId ? 'active' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-current={item.conversation_id === conversationId ? 'true' : undefined}
                  key={item.conversation_id}
                  onClick={() => onSelectConversation(item.conversation_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelectConversation(item.conversation_id)
                    }
                  }}
                >
                  <div className="history-row-main">
                    <strong>{conversationTitle(item.title)}</strong>
                    <div className="history-meta">
                      <span className={`status-badge status-${item.status}`}>{conversationStatusLabel(item.status)}</span>
                      {item.agent_key && <span className="ws-code">{item.agent_key}</span>}
                      <span>更新于 {formatMessageTime(item.updated_at)}</span>
                    </div>
                  </div>
                </div>
              ))}

              {!state.conversationsLoading && !state.conversationsError && state.conversationsTotal > CONVERSATION_PAGE_SIZE && (
                <div className="history-pagination">
                  <button className="button" type="button" disabled={state.listOffset === 0} onClick={() => void loadList(state.statusFilter, Math.max(0, state.listOffset - CONVERSATION_PAGE_SIZE))}>上一页</button>
                  <span>{state.listOffset + 1}–{Math.min(state.listOffset + CONVERSATION_PAGE_SIZE, state.conversationsTotal)} / {state.conversationsTotal}</span>
                  <button className="button" type="button" disabled={state.listOffset + CONVERSATION_PAGE_SIZE >= state.conversationsTotal} onClick={() => void loadList(state.statusFilter, state.listOffset + CONVERSATION_PAGE_SIZE)}>下一页</button>
                </div>
              )}
            </section>

            <section className="history-panel" aria-label="会话内容">
              {!conversationId && (
                <div className="empty-state"><strong>选择一个会话查看消息</strong><span>左侧列表里点一个会话，就能看到消息记录并继续对话。</span></div>
              )}

              {conversationId && state.detailLoading && !detail && (
                <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话内容…</div>
              )}

              {conversationId && !state.detailLoading && state.detailError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>会话加载失败</strong><p>{state.detailError.message}</p></div>
                  {state.detailError.retryable && <button className="text-action" type="button" onClick={() => void loadDetail(conversationId, messagesLimit)}>重新尝试</button>}
                </div>
              )}

              {detail && (
                <>
                  <div className="panel-header">
                    <div>
                      <h2>{conversationTitle(detail.title)}</h2>
                      <span className="page-code">{detail.conversation_id}</span>
                    </div>
                    <div className="history-actions">
                      <span className={`status-badge status-${detail.status}`}>{conversationStatusLabel(detail.status)}</span>
                      <button className="button" type="button" disabled={archived || state.archiving} onClick={() => void archive()}>归档</button>
                    </div>
                  </div>

                  <div className="panel-body">
                    <div className="history-meta">
                      {detail.agent_key && <span>执行人：<span className="ws-code">{detail.agent_key}</span></span>}
                      <span>共 {detail.messages_total} 条消息</span>
                    </div>
                  </div>

                  {detail.messages.length === 0 && (
                    <div className="empty-state"><strong>这个会话还没有消息</strong><span>在下方输入框发送第一条消息。</span></div>
                  )}

                  {detail.messages.length > 0 && (
                    <div className="conversation-messages">
                      {detail.messages.map((message) => (
                        <article className={`conversation-message conversation-message--${message.role}`} key={message.message_id}>
                          <div className="conversation-message__head">
                            <strong>{roleLabel(message.role)}</strong>
                            {message.role === 'assistant' && message.stub && <span className="status-badge status-reviewing">桩回复</span>}
                            {message.tool_name && <span className="ws-code">{message.tool_name}</span>}
                            <span>{formatMessageTime(message.created_at)}</span>
                          </div>
                          <p className="conversation-message__body">{message.content}</p>
                        </article>
                      ))}
                    </div>
                  )}

                  {detail.messages.length < detail.messages_total && (
                    <div className="history-pagination">
                      <button className="button" type="button" disabled={state.detailLoading} onClick={loadMoreMessages}>加载更多消息</button>
                      <span>已显示 {detail.messages.length} / {detail.messages_total}</span>
                    </div>
                  )}

                  <div className="conversation-composer">
                    <form
                      className="composer"
                      onSubmit={(event) => {
                        event.preventDefault()
                        void send()
                      }}
                    >
                      <textarea
                        className="composer-input"
                        aria-label="消息内容"
                        placeholder={archived ? '会话已归档，不能发送新消息' : '给数字员工发一条消息…'}
                        rows={3}
                        maxLength={MAX_MESSAGE_LENGTH}
                        value={draft}
                        disabled={archived}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                      <div className="composer-bar">
                        <span className="composer-field">{archived ? '会话已归档，不能发送' : `最长 ${MAX_MESSAGE_LENGTH} 字符`}</span>
                        <button className="composer-send" type="submit" disabled={!canSend} aria-label="发送消息">
                          <Icon name="send" size={18} />
                        </button>
                      </div>
                    </form>

                    {archived && (
                      <div className="notice" role="status">
                        <div><strong>会话已归档</strong><p>归档后不能再发送新消息（后端会返回 409），历史消息仍可查看；如需继续对话，请新建会话。</p></div>
                      </div>
                    )}

                    {state.sendError && (
                      <div className="notice notice-error" role="alert">
                        <div><strong>消息发送失败</strong><p>{state.sendError.message}</p></div>
                      </div>
                    )}
                  </div>
                </>
              )}
            </section>
          </div>
        )}
      </main>
      <Toast message={state.toast} />
    </>
  )
}
