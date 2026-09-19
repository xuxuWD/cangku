import { useEffect, useState } from 'react'
import { EmptyState } from '../../components/ui/EmptyState'
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

/**
 * 历史草稿（「任务」页签之一，UI v2 §3.2 合并）：
 * 页签与顶栏由 `TasksPage` 提供，这里只负责这一屏的内容（筛选 + 统计 + 列表 + 空态）。
 */
export function ContentHistoryPage({
  onOpenTask,
  onCreateTask,
}: {
  onOpenTask: (taskId: string) => void
  /** 空态主操作：切到「任务」页签去建第一份草稿（由 TasksPage 提供）。 */
  onCreateTask?: () => void
}) {
  const [status, setStatus] = useState<ContentStatus | ''>('')
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<ContentTaskSummary[]>([])
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 手动重试与「刷新」按钮共用：+1 触发一次重取（保持服务端权威，不做本地猜测）。
  const [nonce, setNonce] = useState(0)

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
  }, [status, page, nonce])

  const changeStatus = (value: ContentStatus | '') => { setStatus(value); setPage(1) }

  const reviewingCount = items.filter((item) => item.status === 'reviewing').length
  const failedCount = items.filter((item) => item.status === 'failed').length

  return <>
    <div className="tasks__body">
      <p className="page-desc">查看并继续处理已创建的内容任务；按状态筛选，或翻页找更早的草稿。</p>

      {/* 统计条：总数取服务端命中总数；其余为**本页**统计（如实标注，不冒充全局） */}
      <div className="metrics">
        <div className="metric">
          <div className="metric__label">任务总数</div>
          <div className="metric__value">{loading ? '—' : total}</div>
          <div className="metric__hint">服务端命中总数</div>
        </div>
        <div className="metric">
          <div className="metric__label">本页条数</div>
          <div className="metric__value">{loading ? '—' : items.length}</div>
          <div className="metric__hint">当前这一页</div>
        </div>
        <div className="metric">
          <div className="metric__label">待自检</div>
          <div className="metric__value">{loading ? '—' : reviewingCount}</div>
          <div className="metric__hint">按本页统计</div>
        </div>
        <div className={`metric ${failedCount > 0 ? 'metric--warn' : ''}`}>
          <div className="metric__label">失败</div>
          <div className="metric__value">{loading ? '—' : failedCount}</div>
          <div className="metric__hint">按本页统计</div>
        </div>
      </div>

      <div className="toolbar">
        <label className="history-filter">状态筛选<select aria-label="状态筛选" value={status} onChange={(event) => changeStatus(event.target.value as ContentStatus | '')}>{filters.map((item) => <option value={item.value} key={item.value || 'all'}>{item.label}</option>)}</select></label>
        <span className="history-count">共 {total} 条</span>
      </div>
      <section className="history-panel">
        {loading && <div className="loading-state" role="status">正在加载历史草稿…</div>}
        {!loading && error && <div className="notice notice-error" role="alert"><div><strong>历史草稿加载失败</strong><p>{error}</p></div><button className="text-action" type="button" onClick={() => setNonce((value) => value + 1)}>重新尝试</button></div>}
        {!loading && !error && items.length === 0 && (
          <EmptyState
            illustration="list"
            title="暂无历史草稿"
            text="创建内容任务后，草稿会出现在这里，可以随时继续编辑。"
          >
            {onCreateTask && <button className="btn btn--primary btn--sm" type="button" onClick={onCreateTask}>去创建第一份</button>}
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => setNonce((value) => value + 1)}>刷新</button>
          </EmptyState>
        )}
        {!loading && !error && items.length > 0 && <div className="history-list" role="list">{items.map((item) => <HistoryRow item={item} key={item.task_id} onOpenTask={onOpenTask} />)}</div>}
        <div className="history-pagination"><button className="button" type="button" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} 页</span><button className="button" type="button" disabled={loading || !hasNext} onClick={() => setPage((value) => value + 1)}>下一页</button></div>
      </section>
    </div>
  </>
}

function HistoryRow({ item, onOpenTask }: { item: ContentTaskSummary; onOpenTask: (taskId: string) => void }) {
  return <article className="history-row" role="listitem"><div className="history-row-main"><strong>{item.topic}</strong><div className="history-meta"><span className={`status-badge status-${item.status}`}>{labels[item.status]}</span><span>创建者：{item.created_by}</span><span>更新于 {formatDate(item.updated_at)}</span></div></div><div className="history-actions"><button className="button" type="button" onClick={() => onOpenTask(item.task_id)}>继续处理</button>{item.status === 'failed' && <button className="button primary" type="button" onClick={() => onOpenTask(item.task_id)}>重新生成</button>}</div></article>
}
