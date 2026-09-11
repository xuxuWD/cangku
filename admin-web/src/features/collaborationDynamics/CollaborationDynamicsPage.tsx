import { useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { listCollaborationDynamics } from './api'
import { COLLABORATION_DYNAMIC_STATUS_LABELS, type CollaborationDynamic } from './types'

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function CollaborationDynamicsPage({ onOpenTask, onNavigate }: { onOpenTask: (taskId: string) => void; onNavigate?: (view: AppView) => void }) {
  const [items, setItems] = useState<CollaborationDynamic[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void listCollaborationDynamics().then((result) => {
      if (!active) return
      setItems(result)
    }).catch((cause) => {
      if (!active) return
      setError(cause instanceof Error ? cause.message : '协同动态加载失败')
      setItems([])
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return <AppShell activeView="dynamics" onNavigate={onNavigate}>
    <main className="main-content content-history">
      <div className="page-head">
        <div><div className="eyebrow">协同动态</div><h1 className="page-title">协同动态</h1><p className="page-desc">展示当前账号有权限查看的任务动态，点击「查看任务」可进入任务详情。</p></div>
        <div className="content-status"><span>动态总数</span><strong>{items.length}</strong></div>
      </div>
      <section className="history-panel">
        {loading && <div className="loading-state" role="status">正在加载协同动态…</div>}
        {!loading && error && <div className="notice notice-error" role="alert"><div><strong>协同动态加载失败</strong><p>{error}</p></div></div>}
        {!loading && !error && items.length === 0 && <div className="empty-state"><strong>暂无协同动态</strong><span>有新的任务动态后会展示在这里。</span></div>}
        {!loading && !error && items.length > 0 && <div className="history-list" role="list">{items.map((item) => <DynamicRow item={item} key={item.event_id} onOpenTask={onOpenTask} />)}</div>}
      </section>
    </main>
  </AppShell>
}

function DynamicRow({ item, onOpenTask }: { item: CollaborationDynamic; onOpenTask: (taskId: string) => void }) {
  return <article className="history-row" role="listitem"><div className="history-row-main"><strong>{item.title}</strong><div className="history-meta"><span className={`status-badge status-${item.status}`}>{COLLABORATION_DYNAMIC_STATUS_LABELS[item.status]}</span><span>数字员工：{item.employee_key}</span><span>发生时间 {formatDate(item.occurred_at)}</span></div></div><div className="history-actions"><button className="button" type="button" onClick={() => onOpenTask(item.aggregate_id)}>查看任务</button></div></article>
}
