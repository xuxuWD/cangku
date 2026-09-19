import { Icon } from '../components/Icon'
import { HelpTip } from '../components/HelpTip'
import { useConversationList } from '../features/conversation/listStore'
import {
  CONVERSATION_PAGE_SIZE,
  conversationModeLabel,
  conversationStatusLabel,
  conversationTitle,
  type ConversationStatus,
} from '../features/conversation/types'
import { relativeTime } from '../utils/time'

const STATUS_FILTERS: Array<{ value: ConversationStatus | 'all'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '进行中' },
  { value: 'archived', label: '已归档' },
]

/**
 * 左栏会话列表（UI v2 §3.1 第三段 · 真源 §2.17.1）。
 * 数据来自 `ConversationListProvider` —— **与对话页同一份**，不在这里另起一次拉取。
 */
export function SidebarConversations({
  activeConversationId,
  onSelectConversation,
}: {
  activeConversationId?: string
  onSelectConversation?: (conversationId: string) => void
}) {
  const list = useConversationList()
  const { conversations, total, statusFilter, offset, loading, error } = list

  return (
    <section className="conversations" aria-label="会话列表">
      <div className="conversations__head">
        <span className="conversations__label">会话</span>
        <HelpTip label="会话列表">
          <strong>这里是你所有的会话</strong>
          <span>点一条就能打开继续；「进行中 / 已归档」用来筛选。会话就是数字员工干活的地方。</span>
        </HelpTip>
        <span className="conversations__count">共 {total} 条</span>
        <button
          className="icon-btn"
          type="button"
          aria-label="刷新会话列表"
          title="刷新会话列表"
          onClick={() => void list.reload()}
        >
          <Icon name="refresh" size={14} />
        </button>
      </div>

      <div className="segmented" role="tablist" aria-label="会话筛选">
        {STATUS_FILTERS.map((option) => (
          <button
            key={option.value}
            role="tab"
            type="button"
            aria-selected={statusFilter === option.value}
            className={statusFilter === option.value ? 'is-active' : ''}
            onClick={() => void list.load(option.value, 0)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="conversations__state" role="status">
          <span className="loading-dot" />正在加载会话…
        </div>
      )}

      {!loading && error && (
        <div className="conversations__state conversations__state--error" role="alert">
          <span>{error.message}</span>
          {error.retryable && (
            <button className="text-action" type="button" onClick={() => void list.reload()}>
              重新尝试
            </button>
          )}
        </div>
      )}

      {!loading && !error && conversations.length === 0 && (
        <div className="conversations__state">
          <span>还没有会话</span>
          <span className="conversations__state-hint">点上面的「新建对话」开始。</span>
        </div>
      )}

      {!loading && !error && conversations.length > 0 && (
        <div className="conversations__list">
          {conversations.map((item) => (
            <div
              className={`conv ${item.conversation_id === activeConversationId ? 'is-active' : ''}`}
              role="button"
              tabIndex={0}
              aria-current={item.conversation_id === activeConversationId ? 'true' : undefined}
              key={item.conversation_id}
              onClick={() => onSelectConversation?.(item.conversation_id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectConversation?.(item.conversation_id)
                }
              }}
            >
              <strong className="conv__title" title={conversationTitle(item.title)}>
                {conversationTitle(item.title)}
              </strong>
              <span className="conv__meta">
                <span className={`badge ${item.status === 'active' ? 'badge--accent' : ''}`}>
                  {conversationStatusLabel(item.status)}
                </span>
                <span>{conversationModeLabel(item.mode)}</span>
                <span>{relativeTime(item.updated_at)}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {!loading && !error && total > CONVERSATION_PAGE_SIZE && (
        <div className="conversations__pagination">
          <button
            className="btn btn--secondary"
            type="button"
            disabled={offset === 0}
            onClick={() => void list.load(statusFilter, Math.max(0, offset - CONVERSATION_PAGE_SIZE))}
          >
            上一页
          </button>
          <span>
            {offset + 1}–{Math.min(offset + CONVERSATION_PAGE_SIZE, total)} / {total}
          </span>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={offset + CONVERSATION_PAGE_SIZE >= total}
            onClick={() => void list.load(statusFilter, offset + CONVERSATION_PAGE_SIZE)}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  )
}