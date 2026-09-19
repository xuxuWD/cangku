import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
import { PendingApprovalRows } from '../approvals/PendingApprovalsList'
import { usePendingApprovals } from '../approvals/usePendingApprovals'
import { useSlotVisible } from '../conversation/useSlotVisible'
import { fetchWorkforceRoster } from './api'
import { asWorkforceError, initialWorkforceState } from './state'
import { scopeLabel, type WorkforceRosterItem, type WorkforceState } from './types'

/**
 * 员工与岗位（只读清单，模板 T3）+ **待我审批横幅**（S5）：横幅与工作台首页指标卡
 * 走**同一个聚合端点与同一个 hook**（`usePendingApprovals`），两处永远同源同数。
 */
export function WorkforcePage({
  onNavigate,
  onOpenTask,
  onOpenRun,
}: {
  onNavigate?: (view: AppView) => void
  onOpenTask?: (taskId: string) => void
  onOpenRun?: (runId: string) => void
}) {
  const [state, setState] = useState<WorkforceState>(initialWorkforceState)
  const rootRef = useRef<HTMLElement | null>(null)
  const visible = useSlotVisible(rootRef)
  const pending = usePendingApprovals({ enabled: visible })

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await fetchWorkforceRoster()
      setState({ items: Array.isArray(data.items) ? data.items : [], total: typeof data.total === 'number' ? data.total : 0, loading: false, error: null })
    } catch (error) {
      setState({ items: [], total: 0, loading: false, error: asWorkforceError(error) })
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // 统计条：项数取服务端 `total`；两个「已绑定」数量按本页返回的名册现状统计，不本地估算。
  const roleBoundCount = state.items.filter((item) => item.role_knowledge_base_ids.length > 0).length
  const agentBoundCount = state.items.filter((item) => item.agent_knowledge_base_ids.length > 0).length

  return <>
    <main className="main-content t3 workforce" ref={rootRef}>
      <div className="t3__intro">
        <p className="page-desc">这是只读视图：列出本租户已知的岗位与数字员工标识、各自绑定的知识库与关联任务数。数据来自知识范围绑定与任务记录，不做增删改；编辑绑定请前往「知识权限管理」。</p>
        <div className="t3__actions">
          {/* UI v2 §3.2：数字员工设置是「员工」下的配置页，从本页进入（侧栏不再单列入口）。 */}
          {onNavigate && <button className="btn btn--secondary btn--sm" type="button" onClick={() => onNavigate('workforceSettings')}>数字员工设置</button>}
          <button className="btn btn--ghost btn--sm" type="button" onClick={() => void load()}>刷新</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">名册项数</div>
          <div className="metric__value">{state.loading ? '—' : state.total}</div>
          <div className="metric__hint">按服务端返回的名册总数</div>
        </div>
        <div className="metric">
          <div className="metric__label">已绑定岗位知识范围</div>
          <div className="metric__value">{state.loading ? '—' : roleBoundCount}</div>
          <div className="metric__hint">按本页数据统计</div>
        </div>
        <div className="metric">
          <div className="metric__label">已绑定数字员工知识范围</div>
          <div className="metric__value">{state.loading ? '—' : agentBoundCount}</div>
          <div className="metric__hint">按本页数据统计</div>
        </div>
      </div>

      {/* S5：待我审批横幅（与工作台首页指标卡同源）；没有待办时不占版面，读取失败如实说明 */}
      {pending.counts.total > 0 && (
        <section className="card" aria-label="待我审批">
          <div className="card__head">
            <h2>待我审批</h2>
            <span className="page-meta">{pending.counts.total} 项</span>
          </div>
          <div className="rows">
            <PendingApprovalRows items={pending.items} destinations={{ onOpenTask, onOpenRun }} max={3} />
          </div>
        </section>
      )}
      {pending.error && (
        <p className="ws-hint">待我审批读取失败：{pending.error.message}</p>
      )}

      <section className="card" aria-label="岗位与数字员工清单">
        <div className="card__head">
          <h2>岗位与数字员工</h2>
          <span className="page-meta">{state.total} 项</span>
        </div>
        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载岗位与数字员工…</div>}
        {!state.loading && state.error && <div className="card__body"><div className="notice notice-error" role="alert"><div><strong>岗位与数字员工加载失败</strong><p>{state.error.message}</p></div>{state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}</div></div>}
        {!state.loading && !state.error && state.items.length === 0 && (
          <EmptyState illustration="list" title="暂无岗位或数字员工记录" text="配置知识范围或创建任务后，标识会出现在这里。">
            {onNavigate && <button className="btn btn--primary btn--sm" type="button" onClick={() => onNavigate('workforceSettings')}>数字员工设置</button>}
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
          </EmptyState>
        )}
        {!state.loading && !state.error && state.items.length > 0 && <table className="workforce__table">
          <thead>
            <tr><th scope="col">标识</th><th scope="col">岗位知识范围</th><th scope="col">数字员工知识范围</th><th scope="col">任务数</th></tr>
          </thead>
          <tbody>
            {state.items.map((item) => <WorkforceRow item={item} key={item.key} />)}
          </tbody>
        </table>}
      </section>
    </main>
  </>
}

function WorkforceRow({ item }: { item: WorkforceRosterItem }) {
  return <tr>
    <td><span className="workforce__key">{item.key}</span></td>
    <td><Scope ids={item.role_knowledge_base_ids} /></td>
    <td><Scope ids={item.agent_knowledge_base_ids} /></td>
    <td className="workforce__count">{item.task_count}</td>
  </tr>
}

function Scope({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="workforce__none">未绑定</span>
  return <span className="workforce__chips" aria-label={scopeLabel(ids)}>{ids.map((id) => <span className="workforce__chip" key={id}>{id}</span>)}</span>
}