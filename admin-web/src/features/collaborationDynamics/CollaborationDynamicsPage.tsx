import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
import { listCollaborationDynamics } from './api'
import { COLLABORATION_DYNAMIC_STATUS_LABELS, type CollaborationDynamic } from './types'

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

// api.ts 对 401/403 抛出这句固定文案；页面据此把「无权限」与「真故障」分开处理（无权限不给重试）。
const UNAUTHORIZED_MESSAGE = '当前账号没有查看协同动态的权限。'
const FALLBACK_ERROR = '协同动态暂时无法加载，请检查网络后重新尝试。'

interface DynamicsError {
  message: string
  unauthorized: boolean
}

export function CollaborationDynamicsPage({ onOpenTask }: { onOpenTask: (taskId: string) => void; onNavigate?: (view: AppView) => void }) {
  const [items, setItems] = useState<CollaborationDynamic[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<DynamicsError | null>(null)
  // 重新拉取用「自增序号」触发，保证加载中/错误态都能重跑同一段真实请求。
  const [reloadNonce, setReloadNonce] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    void listCollaborationDynamics().then((result) => {
      if (!active) return
      // 接口约定返回数组：异常载荷按「没有动态」处理，不让面板整块空白。
      setItems(Array.isArray(result) ? result : [])
    }).catch((cause) => {
      if (!active) return
      const raw = cause instanceof Error ? cause.message : ''
      // 只透出接口给的中文文案；网络层英文报错（如 Failed to fetch）换成中文，不暴露内部细节。
      const isChinese = /[\u4e00-\u9fa5]/.test(raw)
      setError({ message: isChinese ? raw : FALLBACK_ERROR, unauthorized: raw === UNAUTHORIZED_MESSAGE })
      setItems([])
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [reloadNonce])

  const reload = useCallback(() => setReloadNonce((value) => value + 1), [])

  // 统计条只用真实可得的数字，并明确标注「按本页统计」。
  const taskCount = useMemo(() => new Set(items.map((item) => item.aggregate_id)).size, [items])
  const pendingApprovalCount = useMemo(() => items.filter((item) => item.status === 'pending_approval').length, [items])
  const showMetrics = !loading && error === null

  return <>
    <main className="main-content content-history t3">
      <div className="t3__intro">
        <p className="page-desc">展示当前账号有权限查看的任务动态，点击「查看任务」可进入任务详情。</p>
        <div className="t3__actions">
          <button className="btn btn--secondary" type="button" disabled={loading} onClick={reload}>{loading ? '正在刷新' : '刷新'}</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">本页动态</div>
          <div className="metric__value">{showMetrics ? items.length : '—'}</div>
          <div className="metric__hint">本次拉取到的动态条数</div>
        </div>
        <div className="metric">
          <div className="metric__label">涉及任务</div>
          <div className="metric__value">{showMetrics ? taskCount : '—'}</div>
          <div className="metric__hint">按本页统计，去重后的任务数</div>
        </div>
        <div className="metric">
          <div className="metric__label">等待审批</div>
          <div className="metric__value">{showMetrics ? pendingApprovalCount : '—'}</div>
          <div className="metric__hint">按本页统计，状态为等待审批的动态</div>
        </div>
      </div>

      <section className="card" aria-label="协同动态列表">
        <div className="card__head"><h2>动态列表</h2></div>

        {loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载协同动态…</div>}

        {!loading && error?.unauthorized && (
          <div className="card__body">
            <div className="notice" role="status">
              <div><strong>暂时无法查看协同动态</strong><p>当前账号没有查看协同动态的权限。请联系超级管理员开通后再查看。</p></div>
            </div>
          </div>
        )}

        {!loading && error && !error.unauthorized && (
          <div className="card__body">
            <div className="notice notice-error" role="alert">
              <div><strong>协同动态加载失败</strong><p>{error.message}</p></div>
              <button className="text-action" type="button" onClick={reload}>重新尝试</button>
            </div>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <EmptyState illustration="list" title="暂无协同动态" text="有新的任务动态后会展示在这里。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={reload}>刷新</button>
          </EmptyState>
        )}

        {!loading && !error && items.length > 0 && (
          <div className="rows" role="list">{items.map((item) => <DynamicRow item={item} key={item.event_id} onOpenTask={onOpenTask} />)}</div>
        )}
      </section>
    </main>
  </>
}

function DynamicRow({ item, onOpenTask }: { item: CollaborationDynamic; onOpenTask: (taskId: string) => void }) {
  return <article className="row" role="listitem">
    <div className="row__main">
      <strong className="row__title">{item.title}</strong>
      <span className="row__sub"><span className={`status-badge status-${item.status}`}>{COLLABORATION_DYNAMIC_STATUS_LABELS[item.status]}</span>{' '}<span>数字员工：{item.employee_key}</span></span>
    </div>
    <span className="row__side">
      <span className="row__time" title={item.occurred_at}>{formatDate(item.occurred_at)}</span>
      <button className="btn btn--secondary btn--sm" type="button" onClick={() => onOpenTask(item.aggregate_id)}>查看任务</button>
    </span>
  </article>
}