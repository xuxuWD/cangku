import { useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { listContentTasks } from '../contentWorkbench/api'
import type { ContentStatus, ContentTaskSummary } from '../contentWorkbench/types'

const labels: Record<ContentStatus, string> = { generating: '生成中', reviewing: '待自检', confirmed: '已确认', failed: '失败' }
const filters: Array<{ value: ContentStatus | ''; label: string }> = [
  { value: '', label: '全部' },
  { value: 'reviewing', label: '待自检' },
  { value: 'failed', label: '失败' },
  { value: 'confirmed', label: '已确认' },
]

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function ContentHistoryPage({ onOpenTask, onNavigate }: { onOpenTask: (taskId: string) => void; onNavigate?: (view: AppView) => void }) {
  const [status, setStatus] = useState<ContentStatus | ''>('')
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<ContentTaskSummary[]>([])
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void listContentTasks(status, page).then((result) => {
      if (!active) return
      setItems(result.items)
      setTotal(result.total)
      setHasNext(result.has_next)
    }).catch((cause) => {
      if (!active) return
      setError(cause instanceof Error ? cause.message : '历史草稿加载失败')
      setItems([])
      setTotal(0)
      setHasNext(false)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [status, page])

  const changeStatus = (value: ContentStatus | '') => { setStatus(value); setPage(1) }

  return <AppShell activeView="history" onNavigate={onNavigate}>
    <main className="main-content content-history">
      <div className="page-head">
        <div><div className="eyebrow">微信公众号图文</div><h1 className="page-title">历史草稿</h1><p className="page-desc">查看并继续处理已创建的内容任务。</p></div>
        <div className="content-status"><span>任务总数</span><strong>{total}</strong></div>
      </div>
      <section className="history-panel">
        <div className="history-toolbar"><label className="history-filter">状态筛选<select aria-label="状态筛选" value={status} onChange={(event) => changeStatus(event.target.value as ContentStatus | '')}>{filters.map((item) => <option value={item.value} key={item.value || 'all'}>{item.label}</option>)}</select></label><span className="history-count">共 {total} 条</span></div>
        {loading && <div className="loading-state" role="status">正在加载历史草稿…</div>}
        {!loading && error && <div className="notice notice-error" role="alert"><div><strong>历史草稿加载失败</strong><p>{error}</p></div></div>}
        {!loading && !error && items.length === 0 && <div className="empty-state"><strong>暂无历史草稿</strong><span>创建内容任务后，草稿会出现在这里。</span></div>}
        {!loading && !error && items.length > 0 && <div className="history-list" role="list">{items.map((item) => <HistoryRow item={item} key={item.task_id} onOpenTask={onOpenTask} />)}</div>}
        <div className="history-pagination"><button className="button" type="button" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} 页</span><button className="button" type="button" disabled={loading || !hasNext} onClick={() => setPage((value) => value + 1)}>下一页</button></div>
      </section>
    </main>
  </AppShell>
}

function HistoryRow({ item, onOpenTask }: { item: ContentTaskSummary; onOpenTask: (taskId: string) => void }) {
  return <article className="history-row" role="listitem"><div className="history-row-main"><strong>{item.topic}</strong><div className="history-meta"><span className={`status-badge status-${item.status}`}>{labels[item.status]}</span><span>创建者：{item.created_by}</span><span>更新于 {formatDate(item.updated_at)}</span></div></div><div className="history-actions"><button className="button" type="button" onClick={() => onOpenTask(item.task_id)}>继续处理</button>{item.status === 'failed' && <button className="button primary" type="button" onClick={() => onOpenTask(item.task_id)}>重新生成</button>}</div></article>
}
