import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { fetchWorkforceRoster } from './api'
import { asWorkforceError, initialWorkforceState } from './state'
import { scopeLabel, type WorkforceRosterItem, type WorkforceState } from './types'

export function WorkforcePage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<WorkforceState>(initialWorkforceState)

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

  return <AppShell activeView="workforce" onNavigate={onNavigate}>
    <main className="main-content content-history workforce">
      <div className="page-head">
        <div>
          <div className="eyebrow">组织与权限</div>
          <h1 className="page-title">员工与岗位</h1>
          <p className="page-desc">这是只读视图：列出本租户已知的岗位与数字员工标识、各自绑定的知识库与关联任务数。数据来自知识范围绑定与任务记录，不做增删改；编辑绑定请前往「知识权限管理」。</p>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
      </div>

      <section className="history-panel workforce__panel" aria-label="岗位与数字员工清单">
        <div className="panel-header"><h2>岗位与数字员工</h2><span>{state.total} 项</span></div>
        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载岗位与数字员工…</div>}
        {!state.loading && state.error && <div className="notice notice-error" role="alert"><div><strong>岗位与数字员工加载失败</strong><p>{state.error.message}</p></div>{state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}</div>}
        {!state.loading && !state.error && state.items.length === 0 && <div className="empty-state"><strong>暂无岗位或数字员工记录</strong><span>配置知识范围或创建任务后，标识会出现在这里。</span></div>}
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
  </AppShell>
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
