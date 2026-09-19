import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
import { Toast } from '../../components/Toast'
import { listInbox, markAllInboxRead, markInboxRead } from './api'
import { resolveInboxAction } from './destinations'
import { asInboxError, initialInboxState } from './state'
import { inboxKindLabel, type InboxItem, type InboxState } from './types'
import { INBOX_CHANGED_EVENT } from './useUnreadCount'

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const diff = Date.now() - date.getTime()
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

type InboxFilter = 'all' | 'unread'

/**
 * 通知页（S3：**无死胡同** / UI v2 · T3 骨架）。
 * 七类目标各有明确结果：能到的直达（任务 / 运行详情 / 合同 / 进度概览），
 * 不能到的**行内如实说明**（计划提案、编排优化、账号注册等处理入口尚未交付）；
 * 任何点击都会先把该条标为已读（真实副作用），绝不出现「点了没反应」。
 *
 * 「全部 / 未读」是**纯前端筛选**（基于已加载的 items），不改变任何服务端语义。
 */
export function InboxPage({
  onOpenTask,
  onOpenRun,
  onOpenConversation,
  onNavigate,
}: {
  onOpenTask?: (taskId: string) => void
  onOpenRun?: (runId: string) => void
  /** S1 第三款：带会话上文的通知直达「该会话（的该条卡）」。 */
  onOpenConversation?: (conversationId: string, approvalId?: string) => void
  onNavigate?: (view: AppView) => void
} = {}) {
  const [state, setState] = useState<InboxState>(initialInboxState)
  const [filter, setFilter] = useState<InboxFilter>('all')
  const update = useCallback((patch: Partial<InboxState>) => setState((old) => ({ ...old, ...patch })), [])

  const load = useCallback(async () => {
    update({ loading: true, error: null })
    try {
      const data = await listInbox(false)
      update({ loading: false, items: Array.isArray(data.items) ? data.items : [], unreadCount: typeof data.unread_count === 'number' ? data.unread_count : 0 })
    } catch (error) {
      update({ loading: false, error: asInboxError(error) })
    }
  }, [update])

  useEffect(() => { void load() }, [load])

  const markRead = async (item: InboxItem) => {
    update({ markingId: item.inbox_id, toast: null })
    try {
      const updated = await markInboxRead(item.inbox_id)
      const wasUnread = item.read_at === null
      setState((old) => ({ ...old, markingId: null, items: old.items.map((row) => row.inbox_id === item.inbox_id ? updated : row), unreadCount: wasUnread ? Math.max(0, old.unreadCount - 1) : old.unreadCount }))
      window.dispatchEvent(new Event(INBOX_CHANGED_EVENT))
    } catch (error) {
      update({ markingId: null, toast: asInboxError(error).message })
    }
  }

  const markAll = async () => {
    if (state.markingAll || state.unreadCount === 0) return
    update({ markingAll: true, toast: null })
    try {
      await markAllInboxRead()
      const now = new Date().toISOString()
      setState((old) => ({ ...old, markingAll: false, items: old.items.map((row) => row.read_at ? row : { ...row, read_at: now }), unreadCount: 0, toast: '已全部标记为已读' }))
      window.dispatchEvent(new Event(INBOX_CHANGED_EVENT))
    } catch (error) {
      update({ markingAll: false, toast: asInboxError(error).message })
    }
  }

  // 点击 = 先标已读（真实副作用）+ 有落点则跳转；无落点时按钮文案与行内说明已如实告知。
  const handleRowAction = async (item: InboxItem, run?: () => void) => {
    if (item.read_at === null) await markRead(item)
    run?.()
  }

  // 「未读」档只看已加载 items 里 read_at === null 的行，纯前端筛选。
  const visibleItems = useMemo(() => filter === 'unread' ? state.items.filter((item) => item.read_at === null) : state.items, [filter, state.items])
  const noUnreadVisible = state.items.length > 0 && visibleItems.length === 0

  return <>
    <main className="main-content content-history t3">
      <div className="t3__intro">
        <p className="page-desc">审批结果与运行结果会记录在这里；标记已读只影响你自己的收件箱。</p>
        <div className="t3__actions">
          <button className="btn btn--secondary" type="button" disabled={state.loading} onClick={() => void load()}>{state.loading ? '正在刷新' : '刷新'}</button>
          <button className="btn btn--primary" type="button" disabled={state.markingAll || state.unreadCount === 0} onClick={() => void markAll()}>{state.markingAll ? '正在处理' : '全部标记已读'}</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">未读</div>
          <div className="metric__value">{state.loading ? '—' : state.unreadCount}</div>
          <div className="metric__hint">服务端返回的收件箱未读数</div>
        </div>
        <div className="metric">
          <div className="metric__label">本页共</div>
          <div className="metric__value">{state.loading ? '—' : state.items.length}</div>
          <div className="metric__hint">本次拉取到的通知条数</div>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="tablist" aria-label="通知筛选">
          <button type="button" role="tab" aria-selected={filter === 'all'} className={filter === 'all' ? 'is-active' : ''} onClick={() => setFilter('all')}>全部</button>
          <button type="button" role="tab" aria-selected={filter === 'unread'} className={filter === 'unread' ? 'is-active' : ''} onClick={() => setFilter('unread')}>未读</button>
        </div>
        <span className="role-note">未读通知 {state.unreadCount} 条</span>
      </div>

      <section className="card" aria-label="通知列表">
        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载通知…</div>}

        {!state.loading && state.error && (
          <div className="card__body">
            <div className="notice notice-error" role="alert">
              <div><strong>{state.error.unauthorized ? '暂时无法查看通知' : '通知加载失败'}</strong><p>{state.error.message}</p></div>
              {state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          </div>
        )}

        {!state.loading && !state.error && state.items.length === 0 && (
          <EmptyState illustration="list" title="暂无通知" text="有新的审批或运行结果时会展示在这里。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
          </EmptyState>
        )}

        {!state.loading && !state.error && noUnreadVisible && (
          <EmptyState illustration="list" title="没有未读通知" text="当前列表里的通知都已读；切回「全部」可以查看历史通知。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
          </EmptyState>
        )}

        {!state.loading && !state.error && visibleItems.length > 0 && (
          <div className="rows" role="list">
            {visibleItems.map((item) => (
              <InboxRow
                item={item}
                busy={state.markingId === item.inbox_id}
                action={resolveInboxAction(item, { onOpenTask, onOpenRun, onOpenConversation, onNavigate })}
                onAction={(run) => void handleRowAction(item, run)}
                key={item.inbox_id}
              />
            ))}
          </div>
        )}
      </section>
    </main>
    <Toast message={state.toast} />
  </>
}

function InboxRow({
  item,
  busy,
  action,
  onAction,
}: {
  item: InboxItem
  busy: boolean
  action: ReturnType<typeof resolveInboxAction>
  onAction: (run?: () => void) => void
}) {
  const unread = item.read_at === null
  const opens = Boolean(action.run)
  // 按钮文案直接说明**去哪里**（打开任务 / 打开运行详情 / 打开合同页…）；
  // 「读取并打开」不写死：点击本身就会先标记已读，界面上「已读」徽标会立刻变化。
  const buttonLabel = opens ? action.label : unread ? '标为已读' : ''
  const showButton = Boolean(buttonLabel)
  return <article className={`row ${unread ? 'inbox-row--unread' : ''}`} role="listitem">
    <div className="row__main">
      <span className="row__title">{item.title}</span>
      <span className="row__sub">
        <span className={`status-badge ${unread ? 'status-unread' : 'status-confirmed'}`}>{unread ? '未读' : '已读'}</span>{' '}{inboxKindLabel(item.kind)}
      </span>
      {action.note && <span className="row__note">{action.note}</span>}
    </div>
    <span className="row__side">
      <span className="row__time" title={item.created_at}>{formatTime(item.created_at)}</span>
      {showButton && <button className="btn btn--secondary btn--sm" type="button" disabled={busy} onClick={() => onAction(action.run)}>{buttonLabel}</button>}
    </span>
  </article>
}