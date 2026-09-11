import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { listInbox, markAllInboxRead, markInboxRead } from './api'
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

export function InboxPage({ onOpenTask, onNavigate }: { onOpenTask?: (taskId: string) => void; onNavigate?: (view: AppView) => void } = {}) {
  const [state, setState] = useState<InboxState>(initialInboxState)
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

  const openItem = async (item: InboxItem) => {
    if (item.read_at === null) await markRead(item)
    if (item.target_type === 'task' && item.target_id) onOpenTask?.(item.target_id)
  }

  const canOpen = (item: InboxItem) => item.read_at !== null && item.target_type === 'task' && Boolean(item.target_id)

  return <AppShell activeView="inbox" onNavigate={onNavigate}>
    <main className="main-content content-history">
      <div className="page-head">
        <div><div className="eyebrow">站内通知</div><h1 className="page-title">通知</h1><p className="page-desc">审批结果与运行结果会记录在这里，标记已读只影响你自己的收件箱。</p></div>
        <div className="actions"><button className="button" type="button" disabled={state.markingAll || state.unreadCount === 0} onClick={() => void markAll()}>{state.markingAll ? '正在处理' : '全部标记已读'}</button></div>
      </div>
      <div className="controls"><span className="role-note">未读通知 {state.unreadCount} 条</span></div>
      {state.error && <div className="notice notice-error" role="alert"><div><strong>通知加载失败</strong><p>{state.error.message}</p></div><button className="text-action" type="button" onClick={() => void load()}>重新尝试</button></div>}
      <section className="history-panel">
        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载通知…</div>}
        {!state.loading && !state.error && state.items.length === 0 && <div className="empty-state"><strong>暂无通知</strong><span>有新的审批或运行结果时会展示在这里。</span></div>}
        {!state.loading && !state.error && state.items.length > 0 && <div className="history-list" role="list">{state.items.map((item) => <InboxRow item={item} busy={state.markingId === item.inbox_id} canOpen={canOpen(item)} onOpen={() => void openItem(item)} key={item.inbox_id} />)}</div>}
      </section>
    </main>
    <Toast message={state.toast} />
  </AppShell>
}

function InboxRow({ item, busy, canOpen, onOpen }: { item: InboxItem; busy: boolean; canOpen: boolean; onOpen: () => void }) {
  const unread = item.read_at === null
  const showButton = unread || canOpen
  return <article className={`history-row inbox-row ${unread ? 'inbox-row--unread' : ''}`} role="listitem">
    <div className="history-row-main">
      <strong>{item.title}</strong>
      <div className="history-meta">
        <span className={`status-badge ${unread ? 'status-unread' : 'status-confirmed'}`}>{unread ? '未读' : '已读'}</span>
        <span>{inboxKindLabel(item.kind)}</span>
        <span title={item.created_at}>{formatTime(item.created_at)}</span>
      </div>
    </div>
    {showButton && <div className="history-actions"><button className="button" type="button" disabled={busy} onClick={onOpen}>{unread ? '标为已读' : '查看'}</button></div>}
  </article>
}
