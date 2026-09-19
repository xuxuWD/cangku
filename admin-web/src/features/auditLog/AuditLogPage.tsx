import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
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

// 是否带着筛选条件查询过：用于区分「还没有审计记录」与「没有符合条件的记录」。
function hasActiveFilters(filters: AuditFilters): boolean {
  return filters.actions.length > 0 || Boolean(filters.actorId || filters.targetType || filters.targetId || filters.since || filters.until)
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
  const filtered = hasActiveFilters(filters)

  return <>
    <main className="main-content content-history audit-log t3">
      <div className="t3__intro">
        <p className="page-desc">谁在什么时候做了什么、结果如何：按动作、操作者、目标与时间范围查询本租户的关键操作审计；仅 CEO 与超级管理员可查看。</p>
        <div className="t3__actions">
          <button className="btn btn--secondary" type="button" onClick={reset}>重置</button>
          <button className="btn btn--primary" type="button" onClick={submit}>查询</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">命中</div>
          <div className="metric__value">{state.loading ? '—' : state.total}</div>
          <div className="metric__hint">符合当前筛选条件的记录数</div>
        </div>
        <div className="metric">
          <div className="metric__label">本页</div>
          <div className="metric__value">{state.loading ? '—' : state.items.length}</div>
          <div className="metric__hint">当前页返回的记录数</div>
        </div>
        <div className="metric">
          <div className="metric__label">每页条数</div>
          <div className="metric__value">{filters.limit}</div>
          <div className="metric__hint">可在筛选条件里调整</div>
        </div>
      </div>

      <section className="card" aria-label="审计筛选">
        <div className="card__head"><h2>筛选条件</h2></div>
        <div className="card__body">
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
          </div>
        </div>
      </section>

      <section className="card" aria-label="审计记录">
        <div className="card__head"><h2>审计记录</h2></div>

        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载审计记录…</div>}

        {!state.loading && state.error && (
          <div className="card__body">
            <div className="notice notice-error" role="alert">
              <div><strong>{state.error.status === 403 ? '暂时无法查看审计日志' : '审计日志加载失败'}</strong><p>{state.error.message}</p></div>
              {state.error.retryable && <button className="text-action" type="button" onClick={() => void load(filters)}>重新尝试</button>}
            </div>
          </div>
        )}

        {!state.loading && !state.error && state.items.length === 0 && (
          <EmptyState
            illustration="list"
            title={filtered ? '没有符合条件的记录' : '还没有审计记录'}
            text={filtered ? '调整筛选条件或时间范围后再查询。' : '关键操作发生后会记录在这里，可以用上方条件筛选。'}
          >
            {filtered
              ? <button className="btn btn--secondary btn--sm" type="button" onClick={reset}>清除筛选条件</button>
              : <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load(filters)}>刷新</button>}
          </EmptyState>
        )}

        {!state.loading && !state.error && state.items.length > 0 && (
          <div className="rows" role="list">{state.items.map((record) => <AuditRow record={record} key={record.record_id} />)}</div>
        )}

        <div className="history-pagination">
          <button className="btn btn--secondary btn--sm" type="button" disabled={!canPrev} onClick={goPrev}>上一页</button>
          <span>共 {state.total} 条（第 {start}–{end} 条）</span>
          <button className="btn btn--secondary btn--sm" type="button" disabled={!canNext} onClick={goNext}>下一页</button>
        </div>
      </section>
    </main>
  </>
}

function AuditRow({ record }: { record: AuditRecord }) {
  const target = record.target_type && record.target_id ? `${record.target_type}:${record.target_id}` : '—'
  const entries = auditDetailEntries(record.detail)
  return <article className="row audit-log__row" role="listitem">
    <div className="row__main">
      <strong className="row__title">{formatLocalTime(record.occurred_at)} · {auditActionLabel(record.action)}</strong>
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