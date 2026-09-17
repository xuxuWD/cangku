import { useEffect, useRef, useState } from 'react'
import {
  ConversationApiError,
  ConversationSessionExpiredError,
  sendMessage,
  sendMessageStream,
} from './api'
import { parseToolInvocation } from './invocation'
import { ProcessBar } from './ProcessBar'
import { useConversationDetail } from './useConversationDetail'
import { useConversations } from './useConversations'
import { useConversationStream } from './useConversationStream'
import {
  CONVERSATION_PAGE_SIZE,
  MAX_MESSAGE_LENGTH,
  conversationStatusLabel,
  conversationTitle,
  formatMessageTime,
  roleLabel,
} from './types'

// 每条消息生成一个新幂等键：同一键重放由服务端返回既有结果，重试 / 双击不会产生第二次真实执行。
function newIdempotencyKey(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * 手机伴侣端对话面板（P2c-5 事项 O）：会话列表 / 消息 / 发送 / 过程折叠条（简化版）。
 * **不做**侧栏重组与右舞台（无概览 / 审批 / 终端 / diff / 产物面板）；审批仍在既有审批页。
 * 发送路由沿用 §2.4：结构化调用 ⇒ `messages:stream` + 幂等键；纯文本 ⇒ 不带键（桩路径）。
 */
export function ConversationPanel({ onSessionExpired }: { onSessionExpired?: () => void }) {
  const list = useConversations(onSessionExpired)
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined)
  const detailState = useConversationDetail(selectedId, onSessionExpired)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<ConversationApiError | null>(null)
  const [streamNotice, setStreamNotice] = useState<string | null>(null)
  const [streamActive, setStreamActive] = useState(false)
  const [restartToken, setRestartToken] = useState(0)
  const messageFrameSeqRef = useRef(0)

  // 进入 / 切换会话：清草稿与提示，开启读端做**回放**（该会话最新 run 的帧；无 run 则如实关流）。
  useEffect(() => {
    setDraft('')
    setSendError(null)
    setStreamNotice(null)
    setStreamActive(Boolean(selectedId))
    setRestartToken((value) => value + 1)
    messageFrameSeqRef.current = 0
  }, [selectedId])

  const { reload, loadMore } = detailState
  const handleTerminal = () => {
    void reload()
    void list.refresh()
  }
  const stream = useConversationStream({
    conversationId: selectedId,
    enabled: streamActive,
    restartToken,
    onTerminal: handleTerminal,
    onSessionExpired,
  })

  // `message.*` 帧只作「已落定」信号：重取消息（正文由消息表权威提供，帧不落正文）。
  useEffect(() => {
    const latest = stream.frames
      .filter((frame) => frame.kind === 'message.user' || frame.kind === 'message.assistant')
      .reduce((max, frame) => Math.max(max, frame.seq), 0)
    if (latest <= messageFrameSeqRef.current) return
    messageFrameSeqRef.current = latest
    void reload()
  }, [stream.frames, reload])

  const detail = detailState.detail
  const forbidden = list.error?.status === 403
  const archived = detail !== null && detail.status !== 'active'
  const draftInvocation = parseToolInvocation(draft)
  const canSend = Boolean(selectedId) && draft.trim().length > 0 && !sending && !archived

  const send = async () => {
    const content = draft.trim()
    if (!selectedId || !content || !canSend) return
    setSending(true)
    setSendError(null)
    setStreamNotice(null)
    try {
      const invocation = parseToolInvocation(content)
      if (invocation) {
        const result = await sendMessageStream(selectedId, content, newIdempotencyKey())
        if (result.runId) {
          // 有运行 ⇒ 开流尾随（帧从 `seq 1` 补发，不丢帧）。
          setStreamActive(true)
          setRestartToken((value) => value + 1)
        } else {
          // 没有运行 ⇒ 后端未装配真实执行（回落桩路径）：如实告知并关流，不留永远「执行中」的假过程条。
          setStreamActive(false)
          setStreamNotice('未产生运行：后端未装配真实执行，本次按桩回复处理（没有过程流）。')
        }
        if (result.body.status === 'pending_approval') {
          setStreamActive(false)
          setStreamNotice('已提交审批：待批期间没有过程帧；决议后可在网页管理台查看推进过程。')
        }
      } else {
        // 纯文本 ⇒ 不带键（桩路径：不写帧、无流、无副作用）。
        await sendMessage(selectedId, content)
      }
      setDraft('')
      await reload()
      await list.refresh()
    } catch (error) {
      if (error instanceof ConversationSessionExpiredError) {
        onSessionExpired?.()
        return
      }
      setSendError(error instanceof ConversationApiError ? error : new ConversationApiError('消息发送失败，请稍后重试。', 0))
    } finally {
      setSending(false)
    }
  }

  if (forbidden) {
    return (
      <section className="conversation">
        <div className="conversation__error" role="alert">
          <strong>无法使用对话</strong>
          <p>{list.error?.message}</p>
        </div>
      </section>
    )
  }

  if (selectedId) {
    return (
      <section className="conversation">
        <div className="conversation-thread">
          <button className="conversation-thread__back" type="button" onClick={() => setSelectedId(undefined)}>
            返回会话列表
          </button>

          {detailState.loading && !detail && (
            <p className="conversation__loading" role="status">
              正在加载会话内容…
            </p>
          )}

          {detailState.error && !detail && (
            <div className="conversation__error" role="alert">
              <p>{detailState.error.message}</p>
              {detailState.error.retryable && (
                <button type="button" onClick={() => void reload()}>
                  重试
                </button>
              )}
            </div>
          )}

          {detail && (
            <>
              <h2 className="conversation-thread__title">{conversationTitle(detail.title)}</h2>
              <p className="conversation-thread__meta">
                <span className={`conversation-badge conversation-badge--${detail.status}`}>
                  {conversationStatusLabel(detail.status)}
                </span>
                <span>共 {detail.messages_total} 条消息</span>
              </p>

              {detail.messages.length === 0 && (
                <div className="conversation__empty">
                  <strong>这个会话还没有消息</strong>
                  <span>在下方输入框发送第一条消息。</span>
                </div>
              )}

              {detail.messages.length > 0 && (
                <div className="conversation-messages">
                  {detail.messages.map((message) => (
                    <article className={`conversation-message conversation-message--${message.role}`} key={message.message_id}>
                      <div className="conversation-message__head">
                        <strong>{roleLabel(message.role)}</strong>
                        {message.role === 'assistant' && message.stub && <span className="conversation-badge">桩回复</span>}
                        {message.tool_name && <span className="conversation-message__tool">{message.tool_name}</span>}
                        <span>{formatMessageTime(message.created_at)}</span>
                      </div>
                      <p className="conversation-message__body">{message.content}</p>
                    </article>
                  ))}
                </div>
              )}

              {detail.messages.length < detail.messages_total && (
                <div className="conversation-thread__more">
                  <button type="button" disabled={detailState.loading} onClick={() => void loadMore()}>
                    加载更多消息
                  </button>
                  <span>
                    已显示 {detail.messages.length} / {detail.messages_total}
                  </span>
                </div>
              )}

              <ProcessBar frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />

              <form
                className="composer"
                onSubmit={(event) => {
                  event.preventDefault()
                  void send()
                }}
              >
                <label className="composer__label" htmlFor="conversation-draft">
                  消息内容
                </label>
                <textarea
                  id="conversation-draft"
                  className="composer__input"
                  aria-label="消息内容"
                  placeholder={archived ? '会话已归档，不能发送新消息' : '给数字员工发一条消息…'}
                  rows={3}
                  maxLength={MAX_MESSAGE_LENGTH}
                  value={draft}
                  disabled={archived || sending}
                  onChange={(event) => setDraft(event.target.value)}
                />
                <div className="composer__bar">
                  <span className="composer__hint">
                    {archived
                      ? '会话已归档，不能发送'
                      : draftInvocation
                        ? `结构化调用：${draftInvocation.tool_key}（按真实执行路径发送）`
                        : `最长 ${MAX_MESSAGE_LENGTH} 字符 · 纯文本不触发真实执行`}
                  </span>
                  <button className="composer__send" type="submit" disabled={!canSend}>
                    {sending ? '发送中…' : '发送'}
                  </button>
                </div>
              </form>

              {sendError && (
                <div className="conversation__error" role="alert">
                  <p>{sendError.message}</p>
                </div>
              )}

              {streamNotice && (
                <div className="conversation__notice" role="status">
                  <strong>本次没有过程流</strong>
                  <p>{streamNotice}</p>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="conversation">
      <div className="conversation__head">
        <h2 className="conversation__title">对话</h2>
        <button className="conversation__refresh" type="button" onClick={() => void list.refresh()}>
          刷新
        </button>
      </div>

      {list.loading && (
        <p className="conversation__loading" role="status">
          正在加载会话…
        </p>
      )}

      {!list.loading && list.error && (
        <div className="conversation__error" role="alert">
          <p>{list.error.message}</p>
          {list.error.retryable && (
            <button type="button" onClick={() => void list.refresh()}>
              重试
            </button>
          )}
        </div>
      )}

      {!list.loading && !list.error && list.items.length === 0 && (
        <div className="conversation__empty">
          <strong>还没有会话</strong>
          <span>请先在网页管理台发起对话。</span>
        </div>
      )}

      {!list.loading && !list.error && list.items.length > 0 && (
        <ul className="conversation-list">
          {list.items.map((item) => (
            <li key={item.conversation_id}>
              <button className="conversation-list__item" type="button" onClick={() => setSelectedId(item.conversation_id)}>
                <strong className="conversation-list__title">{conversationTitle(item.title)}</strong>
                <span className="conversation-list__meta">
                  <span className={`conversation-badge conversation-badge--${item.status}`}>{conversationStatusLabel(item.status)}</span>
                  <span>更新于 {formatMessageTime(item.updated_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!list.loading && !list.error && list.total > CONVERSATION_PAGE_SIZE && (
        <div className="conversation-list__pagination">
          <button type="button" disabled={list.offset === 0} onClick={() => void list.load(Math.max(0, list.offset - CONVERSATION_PAGE_SIZE))}>
            上一页
          </button>
          <span>
            {list.offset + 1}–{Math.min(list.offset + CONVERSATION_PAGE_SIZE, list.total)} / {list.total}
          </span>
          <button
            type="button"
            disabled={list.offset + CONVERSATION_PAGE_SIZE >= list.total}
            onClick={() => void list.load(list.offset + CONVERSATION_PAGE_SIZE)}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  )
}