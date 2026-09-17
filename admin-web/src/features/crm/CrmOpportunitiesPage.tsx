import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { formatLocalTime } from '../../utils/time'
import { changeOpportunityStage, listOpportunities } from './api'
import { CrmNotice, Pagination } from './CrmShared'
import { asCrmError, CRM_LIMIT_OPTIONS, formatCents } from './state'
import { crmLabel, OPPORTUNITY_STAGE_LABELS, OPPORTUNITY_STAGE_TRANSITIONS, type CrmErrorShape, type CrmOpportunity, type CrmPage } from './types'

const STAGE_OPTIONS = ['qualification', 'proposal', 'negotiation', 'won', 'lost']

interface OpportunityPageState extends CrmPage<CrmOpportunity> {
  loading: boolean
  error: CrmErrorShape | null
}

export function CrmOpportunitiesPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  const [stage, setStage] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [state, setState] = useState<OpportunityPageState>({ items: [], total: 0, limit: 50, offset: 0, loading: true, error: null })

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await listOpportunities({ stage, limit, offset })
      setState({
        items: Array.isArray(data.items) ? data.items : [],
        total: typeof data.total === 'number' ? data.total : 0,
        limit: typeof data.limit === 'number' ? data.limit : limit,
        offset: typeof data.offset === 'number' ? data.offset : offset,
        loading: false,
        error: null,
      })
    } catch (error) {
      setState({ items: [], total: 0, limit, offset, loading: false, error: asCrmError(error) })
    }
  }, [stage, limit, offset])

  useEffect(() => { void load() }, [load])

  const advance = async (opportunity: CrmOpportunity, toStage: string) => {
    setBusyId(opportunity.opportunity_id)
    setToast(null)
    try {
      const updated = await changeOpportunityStage(opportunity.opportunity_id, toStage)
      setState((old) => ({ ...old, items: old.items.map((row) => row.opportunity_id === updated.opportunity_id ? updated : row) }))
      setToast(`阶段已迁移为「${crmLabel(OPPORTUNITY_STAGE_LABELS, updated.stage)}」`)
    } catch (error) {
      const info = asCrmError(error)
      // 并发「首写获胜」：服务端 409 ⇒ 提示并刷新，不静默覆盖。
      if (info.status === 409) {
        setToast('状态已被变更，请刷新')
        await load()
      } else {
        setToast(info.message)
      }
    } finally {
      setBusyId(null)
    }
  }

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">商机</h1>
        <p className="page-desc">商机阶段单向推进（资格确认 → 方案报价 → 商务谈判 → 赢单 / 输单），终态不可回迁；服务端按白名单校验，非法迁移返回 409。</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
    </div>

    <div className="toolbar">
      <label className="history-filter">阶段
        <select value={stage} onChange={(event) => { setStage(event.target.value); setOffset(0) }}>
          <option value="">全部</option>
          {STAGE_OPTIONS.map((option) => <option value={option} key={option}>{crmLabel(OPPORTUNITY_STAGE_LABELS, option)}</option>)}
        </select>
      </label>
      <label className="history-filter">每页条数
        <select value={String(limit)} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0) }}>
          {CRM_LIMIT_OPTIONS.map((size) => <option value={size} key={size}>{size} 条</option>)}
        </select>
      </label>
      <span className="history-count">共 {state.total} 条</span>
    </div>

    {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载商机列表…</div>}
    {!state.loading && state.error && <CrmNotice
      tone="error"
      title="商机列表加载失败"
      action={state.error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{state.error.message}</p>
    </CrmNotice>}
    {!state.loading && !state.error && <section className="history-panel crm__panel" aria-label="商机列表">
      <div className="panel-header"><h2>商机列表</h2><span>{state.total} 条</span></div>
      {state.items.length === 0
        ? <div className="empty-state"><strong>暂无商机</strong><span>调整阶段筛选，或从线索转化 / 接口建商机。</span></div>
        : <div className="panel-body"><table className="workforce__table">
          <thead><tr><th>名称</th><th>客户</th><th>阶段</th><th>金额</th><th>进入阶段时间</th><th>预计成交</th><th>阶段推进</th></tr></thead>
          <tbody>{state.items.map((item) => <tr key={item.opportunity_id}>
            <td><span className="workforce__key">{item.name}</span></td>
            <td>{item.account_id}</td>
            <td><span className={`status-badge ${stageTone(item.stage)}`}>{crmLabel(OPPORTUNITY_STAGE_LABELS, item.stage)}</span></td>
            <td>{formatCents(item.amount_cents)}</td>
            <td>{formatLocalTime(item.stage_entered_at) || '—'}</td>
            <td>{item.expected_close || '—'}</td>
            <td><div className="crm-stage-actions">{(OPPORTUNITY_STAGE_TRANSITIONS[item.stage] ?? []).length === 0
              ? <span className="workforce__none">终态，不可回迁</span>
              : (OPPORTUNITY_STAGE_TRANSITIONS[item.stage] ?? []).map((to) => <button
                className="button"
                type="button"
                key={to}
                disabled={busyId === item.opportunity_id}
                aria-label={`将「${item.name}」推进到 ${crmLabel(OPPORTUNITY_STAGE_LABELS, to)}`}
                onClick={() => void advance(item, to)}
              >→ {crmLabel(OPPORTUNITY_STAGE_LABELS, to)}</button>)}</div></td>
          </tr>)}</tbody>
        </table></div>}
      <Pagination total={state.total} limit={state.limit} offset={state.offset} loading={state.loading} onPrev={() => setOffset(Math.max(0, state.offset - state.limit))} onNext={() => setOffset(state.offset + state.limit)} />
    </section>}

    <Toast message={toast} />
  </main>
}

function stageTone(stage: string): string {
  if (stage === 'won') return 'status-confirmed'
  if (stage === 'lost') return 'status-failed'
  if (stage === 'negotiation') return 'status-pending'
  if (stage === 'proposal') return 'status-generating'
  return 'status-reviewing'
}