import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { formatLocalTime } from '../../utils/time'
import { changeOpportunityStage, getOpportunity, listOpportunities } from './api'
import { CrmNotice, Pagination, AccountName, useAccountNames, type AccountNames } from './CrmShared'
import { asCrmError, CRM_LIMIT_OPTIONS, daysSince, formatCents, formatDays } from './state'
import { crmLabel, OPPORTUNITY_STAGE_LABELS, OPPORTUNITY_STAGE_TRANSITIONS, type CrmErrorShape, type CrmOpportunity, type CrmPage, type CrmStageEvent } from './types'

const STAGE_OPTIONS = ['qualification', 'proposal', 'negotiation', 'won', 'lost']

interface OpportunityPageState extends CrmPage<CrmOpportunity> {
  loading: boolean
  error: CrmErrorShape | null
}

export function CrmOpportunitiesPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  // 客户名映射在页面层取一次：列表 ↔ 详情切换不重复请求。
  const accountNames = useAccountNames()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  if (selectedId) return <OpportunityDetail opportunityId={selectedId} accountNames={accountNames} onBack={() => setSelectedId(null)} />
  return <OpportunityList accountNames={accountNames} onOpen={setSelectedId} />
}

// ---------------------------------------------------------------- 列表

function OpportunityList({ accountNames, onOpen }: { accountNames: AccountNames; onOpen: (opportunityId: string) => void }) {
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
          <thead><tr><th>名称</th><th>客户</th><th>阶段</th><th>金额</th><th>进入阶段时间</th><th>预计成交</th><th>阶段推进</th><th>操作</th></tr></thead>
          <tbody>{state.items.map((item) => <tr key={item.opportunity_id} onClick={() => onOpen(item.opportunity_id)} title="点击行查看商机详情">
            <td><span className="workforce__key">{item.name}</span></td>
            <td><AccountName accountId={item.account_id} names={accountNames} /></td>
            <td><span className={`status-badge ${stageTone(item.stage)}`}>{crmLabel(OPPORTUNITY_STAGE_LABELS, item.stage)}</span></td>
            <td>{formatCents(item.amount_cents)}</td>
            <td>{formatLocalTime(item.stage_entered_at) || '—'}</td>
            <td>{item.expected_close || '—'}</td>
            {/* 推进按钮不触发行跳转：事件在容器上停止冒泡。 */}
            <td><div className="crm-stage-actions" onClick={(event) => event.stopPropagation()}>{(OPPORTUNITY_STAGE_TRANSITIONS[item.stage] ?? []).length === 0
              ? <span className="workforce__none">终态，不可回迁</span>
              : (OPPORTUNITY_STAGE_TRANSITIONS[item.stage] ?? []).map((to) => <button
                className="button"
                type="button"
                key={to}
                disabled={busyId === item.opportunity_id}
                aria-label={`将「${item.name}」推进到 ${crmLabel(OPPORTUNITY_STAGE_LABELS, to)}`}
                onClick={() => void advance(item, to)}
              >→ {crmLabel(OPPORTUNITY_STAGE_LABELS, to)}</button>)}</div></td>
            <td><button className="text-action" type="button" aria-label={`查看「${item.name}」商机详情`} onClick={(event) => { event.stopPropagation(); onOpen(item.opportunity_id) }}>查看详情</button></td>
          </tr>)}</tbody>
        </table></div>}
      <Pagination total={state.total} limit={state.limit} offset={state.offset} loading={state.loading} onPrev={() => setOffset(Math.max(0, state.offset - state.limit))} onNext={() => setOffset(state.offset + state.limit)} />
    </section>}

    <Toast message={toast} />
  </main>
}

// ---------------------------------------------------------------- 详情

function OpportunityDetail({ opportunityId, accountNames, onBack }: { opportunityId: string; accountNames: AccountNames; onBack: () => void }) {
  const [opportunity, setOpportunity] = useState<CrmOpportunity | null>(null)
  const [events, setEvents] = useState<CrmStageEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<CrmErrorShape | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getOpportunity(opportunityId)
      setOpportunity(data.opportunity ?? null)
      setEvents(Array.isArray(data.stage_events) ? data.stage_events : [])
    } catch (err) {
      setError(asCrmError(err))
    } finally {
      setLoading(false)
    }
  }, [opportunityId])

  useEffect(() => { void load() }, [load])

  const advance = async (toStage: string) => {
    if (!opportunity) return
    setBusy(true)
    setToast(null)
    try {
      const updated = await changeOpportunityStage(opportunity.opportunity_id, toStage)
      setToast(`阶段已迁移为「${crmLabel(OPPORTUNITY_STAGE_LABELS, updated.stage)}」`)
      await load()
    } catch (err) {
      const info = asCrmError(err)
      // 并发「首写获胜」：服务端 409 ⇒ 提示并刷新详情与时间线。
      if (info.status === 409) {
        setToast('状态已被变更，请刷新')
        await load()
      } else {
        setToast(info.message)
      }
    } finally {
      setBusy(false)
    }
  }

  if (!opportunity) {
    if (loading) return <main className="main-content content-history crm"><div className="loading-state" role="status"><span className="loading-dot" />正在加载商机详情…</div></main>
    return <main className="main-content content-history crm">
      <div className="page-head"><div><h1 className="page-title">商机详情</h1></div><div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div></div>
      <CrmNotice
        tone="error"
        title="商机详情加载失败"
        action={error?.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
      >
        <p>{error?.message ?? '没有找到该商机。'}</p>
      </CrmNotice>
    </main>
  }

  const transitions = OPPORTUNITY_STAGE_TRANSITIONS[opportunity.stage] ?? []

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">{opportunity.name}</h1>
        <p className="page-desc">商机详情：阶段机状态、金额、阶段停留天数与阶段事件时间线（append-only）。</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div>
    </div>

    {error && <CrmNotice
      tone="error"
      title="刷新失败，展示的是上一次加载的数据"
      action={error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{error.message}</p>
    </CrmNotice>}

    <section className="history-panel crm__panel" aria-label="商机信息">
      <div className="panel-header"><h2>基本信息</h2><span>{opportunity.opportunity_id}</span></div>
      <div className="panel-body">
        <div className="run-detail__grid">
          <div className="run-detail__item"><span className="run-detail__label">客户</span><span className="run-detail__value"><AccountName accountId={opportunity.account_id} names={accountNames} /></span></div>
          <div className="run-detail__item"><span className="run-detail__label">阶段</span><span className="run-detail__value"><span className={`status-badge ${stageTone(opportunity.stage)}`}>{crmLabel(OPPORTUNITY_STAGE_LABELS, opportunity.stage)}</span></span></div>
          <div className="run-detail__item"><span className="run-detail__label">金额</span><span className="run-detail__value">{formatCents(opportunity.amount_cents)}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">预计成交日</span><span className="run-detail__value">{opportunity.expected_close || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">负责人</span><span className="run-detail__value">{opportunity.owner_id}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">创建时间</span><span className="run-detail__value">{formatLocalTime(opportunity.created_at) || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">当前阶段停留</span><span className="run-detail__value">{formatDays(daysSince(opportunity.stage_entered_at))}</span></div>
        </div>
      </div>
    </section>

    <section className="history-panel crm__panel" aria-label="阶段推进">
      <div className="panel-header"><h2>阶段推进</h2><span>单向迁移；非法 / 并发先写由服务端返回 409</span></div>
      <div className="panel-body"><div className="crm-stage-actions">{transitions.length === 0
        ? <span className="workforce__none">终态，不可回迁</span>
        : transitions.map((to) => <button
          className="button"
          type="button"
          key={to}
          disabled={busy}
          aria-label={`将「${opportunity.name}」推进到 ${crmLabel(OPPORTUNITY_STAGE_LABELS, to)}`}
          onClick={() => void advance(to)}
        >→ {crmLabel(OPPORTUNITY_STAGE_LABELS, to)}</button>)}</div></div>
    </section>

    <section className="history-panel crm__panel" aria-label="阶段事件时间线">
      <div className="panel-header"><h2>阶段事件时间线</h2><span>{events.length} 条（按发生时间正序）</span></div>
      {events.length === 0
        ? <div className="empty-state"><strong>暂无阶段事件</strong><span>阶段事件为追加式记录：创建与每次迁移都会写入一条。</span></div>
        : <div className="panel-body crm__timeline"><div className="timeline">{events.map((event, index) => <article className="audit-event" key={event.event_id || index}>
          <time>{formatLocalTime(event.occurred_at) || '—'}</time>
          <strong>{event.from_stage
            ? `${crmLabel(OPPORTUNITY_STAGE_LABELS, event.from_stage)} → ${crmLabel(OPPORTUNITY_STAGE_LABELS, event.to_stage)}`
            : `创建 → ${crmLabel(OPPORTUNITY_STAGE_LABELS, event.to_stage)}`}</strong>
          <p>
            <span>操作者：{event.actor_id || '—'}</span>
            <span>金额快照：{formatCents(event.amount_cents)}</span>
          </p>
        </article>)}</div></div>}
    </section>

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