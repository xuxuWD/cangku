import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { listAudits } from './api'
import { asAuditError, initialAuditFilters, initialAuditLogState } from './state'
import { AUDIT_ACTION_LABELS, auditActionLabel, auditDetailEntries, type AuditFilters, type AuditLogState, type AuditRecord } from './types'
import { formatLocalTime } from '../../utils/time'

// 动作多选取值来自标签表，按动作码排序，避免与后端枚举顺序耦合。
const ACTION_OPTIONS = Object.keys(AUDIT_ACTION_LABELS).sort()
const LIMIT_OPTIONS = [20, 50, 100, 200]

// datetime-local 不带时区，提交前转成 toISOString() 的 Z 形式；解析失败则视为未填。
function toIsoValue(local: string): string {
  if (!local) return ''
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

export function AuditLogPage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<AuditLogState>(initialAuditLogState)
  const [draft, setDraft] = useState<AuditFilters>(initialAuditFilters)
  const [filters, setFilters] = useState<AuditFilters>(initialAuditFilters)

  const load = useCallback(async (query: AuditFilters) => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await listAudits(query)
      setState({ items: Array.isArray(data.items) ? data.items : [], total: typeof data.total === 'number' ? data.total : 0, loading: false, error: null })
    } catch (error) {
      setState({ items: [], total: 0, loading: false, error: asAuditError(error) })
    }
  }, [])

  useEffect(() => { void load(filters) }, [filters, load])

  const patchDraft = (patch: Partial<AuditFilters>) => setDraft((old) => ({ ...old, ...patch }))
  const toggleAction = (action: string, checked: boolean) => setDraft((old) => ({ ...old, actions: checked ? [...old.actions, action] : old.actions.filter((item) => item !== action) }))
  // 任何筛选提交都把 offset 归零，避免停留在旧页码上看到空页。
  const submit = () => setFilters({ ...draft, offset: 0, since: toIsoValue(draft.since), until: toIsoValue(draft.until) })
  const reset = () => { setDraft(initialAuditFilters); setFilters({ ...initialAuditFilters }) }
  const goPrev = () => setFilters((old) => ({ ...old, offset: Math.max(0, old.offset - old.limit) }))
  const goNext = () => setFilters((old) => ({ ...old, offset: old.offset + old.limit }))

  const start = state.total === 0 ? 0 : filters.offset + 1
  const end = Math.min(filters.offset + filters.limit, state.total)
  const canPrev = !state.loading && filters.offset > 0
  const canNext = !state.loading && filters.offset + filters.limit < state.total

  return <AppShell activeView="audit" onNavigate={onNavigate}>
    <main className="main-content content-history audit-log">
      <div className="page-head">
        <div>
          <h1 className="page-title">审计日志</h1>
          <p className="page-desc">按动作、操作者、目标与时间范围查询本租户的关键操作审计；仅 CEO 与超级管理员可查看。</p>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => void load(filters)}>刷新</button></div>
      </div>

      <section className="history-panel audit-log__panel" aria-label="审计筛选">
        <div className="audit-log__filters">
          <div className="audit-log__field audit-log__field--wide">
            <span>动作</span>
            <div className="audit-log__options">
              {ACTION_OPTIONS.map((action) => <label key={action}><input type="checkbox" checked={draft.actions.includes(action)} onChange={(event) => toggleAction(action, event.target.checked)} />{auditActionLabel(action)}</label>)}
            </div>
          </div>
          <label className="audit-log__field">操作者<input type="text" value={draft.actorId} onChange={(event) => patchDraft({ actorId: event.target.value })} /></label>
          <label className="audit-log__field">目标类型<input type="text" value={draft.targetType} onChange={(event) => patchDraft({ targetType: event.target.value })} /></label>
          <label className="audit-log__field">目标 ID<input type="text" value={draft.targetId} onChange={(event) => patchDraft({ targetId: event.target.value })} /></label>
          <label className="audit-log__field">起始时间<input type="datetime-local" value={draft.since} onChange={(event) => patchDraft({ since: event.target.value })} /></label>
          <label className="audit-log__field">截止时间<input type="datetime-local" value={draft.until} onChange={(event) => patchDraft({ until: event.target.value })} /></label>
          <label className="audit-log__field">每页条数<select value={String(draft.limit)} onChange={(event) => patchDraft({ limit: Number(event.target.value) })}>{LIMIT_OPTIONS.map((size) => <option value={size} key={size}>{size} 条</option>)}</select></label>
          <div className="audit-log__submit"><button className="button primary" type="button" onClick={submit}>查询</button><button className="button" type="button" onClick={reset}>重置</button></div>
        </div>
      </section>

      <section className="history-panel audit-log__panel" aria-label="审计记录">
        <div className="panel-header"><h2>审计记录</h2><span>{state.items.length} 条</span></div>
        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载审计记录…</div>}
        {!state.loading && state.error && <div className="notice notice-error" role="alert"><div><strong>审计日志加载失败</strong><p>{state.error.message}</p></div><button className="text-action" type="button" onClick={() => void load(filters)}>重新尝试</button></div>}
        {!state.loading && !state.error && state.items.length === 0 && <div className="empty-state"><strong>没有匹配的审计记录</strong><span>调整筛选条件或时间范围后再试。</span></div>}
        {!state.loading && !state.error && state.items.length > 0 && <div className="history-list" role="list">{state.items.map((record) => <AuditRow record={record} key={record.record_id} />)}</div>}
        <div className="history-pagination">
          <button className="button" type="button" disabled={!canPrev} onClick={goPrev}>上一页</button>
          <span>共 {state.total} 条（第 {start}–{end} 条）</span>
          <button className="button" type="button" disabled={!canNext} onClick={goNext}>下一页</button>
        </div>
      </section>
    </main>
  </AppShell>
}

function AuditRow({ record }: { record: AuditRecord }) {
  const target = record.target_type && record.target_id ? `${record.target_type}:${record.target_id}` : '—'
  const entries = auditDetailEntries(record.detail)
  return <article className="history-row audit-log__row" role="listitem">
    <div className="history-row-main">
      <strong>{formatLocalTime(record.occurred_at)} · {auditActionLabel(record.action)}</strong>
      <div className="history-meta">
        <span className="audit-log__code">{record.action}</span>
        <span>操作者：{record.actor_id ?? '—'}</span>
        <span>目标：{target}</span>
        {record.phone_masked && <span>手机号：{record.phone_masked}</span>}
      </div>
      {entries.length > 0 && <p className="audit-log__detail"><span className="audit-log__detail-label">明细</span>{entries.map((entry) => <span className="audit-log__detail-item" key={entry.key}>{`${entry.key}: ${entry.text}`}</span>)}</p>}
    </div>
  </article>
}
