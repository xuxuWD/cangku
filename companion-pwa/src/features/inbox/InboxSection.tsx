import { inboxKindLabel } from './types'
import { useInbox } from './useInbox'

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

interface InboxSectionProps {
  onSessionExpired?: () => void
}

export function InboxSection({ onSessionExpired }: InboxSectionProps) {
  const { items, unreadCount, loading, error, refresh } = useInbox(onSessionExpired)

  return (
    <section className="inbox">
      <div className="inbox__head">
        <h2 className="inbox__title">通知</h2>
        <span className="inbox__count" aria-label={`未读通知 ${unreadCount} 条`}>
          未读 {unreadCount}
        </span>
      </div>

      {error ? (
        <div className="inbox__error" role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => void refresh()}>
            重试
          </button>
        </div>
      ) : null}

      {loading && items.length === 0 ? <p className="inbox__loading">加载中…</p> : null}
      {!loading && !error && items.length === 0 ? <p className="inbox__empty">暂无通知</p> : null}

      <ul className="inbox__list">
        {items.map((item) => (
          <li key={item.inbox_id} className={`inbox-card ${item.read_at === null ? 'inbox-card--unread' : ''}`}>
            <div className="inbox-card__head">
              <span className="inbox-card__kind">{inboxKindLabel(item.kind)}</span>
              <span className="inbox-card__time">{formatTime(item.created_at)}</span>
            </div>
            <h3 className="inbox-card__title">{item.title}</h3>
            {item.read_at === null ? <span className="inbox-card__unread">未读</span> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
