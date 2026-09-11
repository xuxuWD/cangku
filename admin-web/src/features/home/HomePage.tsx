import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import { createHomeTask, listHomeDrafts, listHomeEmployees, newIdempotencyKey } from './api'
import { asHomeError, initialHomeState } from './state'
import {
  HOME_DRAFT_LIMIT,
  RISK_LABELS,
  draftStatusLabel,
  formatDraftTime,
  type HomeDraft,
  type HomeRiskLevel,
  type HomeState,
} from './types'

const RISK_OPTIONS: HomeRiskLevel[] = ['low', 'medium', 'high']

export function HomePage({
  onOpenTask,
  onNavigate,
}: {
  onOpenTask: (taskId: string) => void
  onNavigate?: (view: AppView) => void
}) {
  const [state, setState] = useState<HomeState>(initialHomeState)
  const [title, setTitle] = useState('')
  const [agentKey, setAgentKey] = useState('')
  const [risk, setRisk] = useState<HomeRiskLevel>('low')

  const load = useCallback(async () => {
    setState((old) => ({ ...old, employeesLoading: true, employeesError: null, draftsLoading: true, draftsError: null }))
    // 两个读取互不阻塞：任一侧失败只影响自己那一块。
    const [employees, drafts] = await Promise.allSettled([listHomeEmployees(), listHomeDrafts(HOME_DRAFT_LIMIT)])
    setState((old) => ({
      ...old,
      employees: employees.status === 'fulfilled' && Array.isArray(employees.value.items) ? employees.value.items : [],
      employeesLoading: false,
      employeesError: employees.status === 'rejected' ? asHomeError(employees.reason) : null,
      drafts: drafts.status === 'fulfilled' && Array.isArray(drafts.value.items) ? drafts.value.items : [],
      draftsLoading: false,
      draftsError: drafts.status === 'rejected' ? asHomeError(drafts.reason) : null,
    }))
  }, [])

  useEffect(() => { void load() }, [load])

  const usableEmployees = state.employees.filter((item) => item.status === 'active')

  // 默认选中首个启用中的数字员工；原选择被停用或删除时自动回落。
  useEffect(() => {
    setAgentKey((current) =>
      usableEmployees.some((item) => item.agent_key === current) ? current : usableEmployees[0]?.agent_key ?? '',
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.employees])

  const canSubmit = title.trim().length > 0 && agentKey !== '' && !state.submitting

  const submit = async () => {
    if (!canSubmit) return
    setState((old) => ({ ...old, submitting: true, submitError: null, toast: null }))
    try {
      const task = await createHomeTask({
        title: title.trim(),
        employeeKey: agentKey,
        riskLevel: risk,
        idempotencyKey: newIdempotencyKey(),
      })
      setTitle('')
      setState((old) => ({
        ...old,
        submitting: false,
        toast: task.status === 'pending_approval'
          ? `任务已创建并提交审批：${task.id}`
          : `任务已创建：${task.id}`,
      }))
    } catch (error) {
      setState((old) => ({ ...old, submitting: false, submitError: asHomeError(error) }))
    }
  }

  return (
    <AppShell activeView="home" onNavigate={onNavigate}>
      <main className="main-content home">
        <section className="home-hero" aria-label="快速创建任务">
          <h1 className="home-title">数字员工，我帮你</h1>
          <p className="home-subtitle">用一句话描述要做的事，交给数字员工执行；高风险任务会自动进入审批。</p>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <textarea
              className="composer-input"
              aria-label="任务描述"
              placeholder="今天帮你做些什么？例如：整理本周客户反馈要点"
              value={title}
              rows={3}
              onChange={(event) => setTitle(event.target.value)}
            />
            <div className="composer-bar">
              <label className="composer-field">
                执行人
                <select
                  aria-label="执行人"
                  value={agentKey}
                  disabled={usableEmployees.length === 0}
                  onChange={(event) => setAgentKey(event.target.value)}
                >
                  {usableEmployees.length === 0 && <option value="">无可用执行人</option>}
                  {usableEmployees.map((item) => (
                    <option value={item.agent_key} key={item.agent_key}>{item.name}</option>
                  ))}
                </select>
              </label>
              <label className="composer-field">
                风险等级
                <select
                  aria-label="风险等级"
                  value={risk}
                  onChange={(event) => setRisk(event.target.value as HomeRiskLevel)}
                >
                  {RISK_OPTIONS.map((option) => (
                    <option value={option} key={option}>{RISK_LABELS[option]}</option>
                  ))}
                </select>
              </label>
              <button className="composer-send" type="submit" disabled={!canSubmit} aria-label="创建任务">
                <Icon name="send" size={18} />
              </button>
            </div>
          </form>

          {state.employeesLoading && <p className="composer-hint" role="status">正在读取可用的数字员工…</p>}

          {!state.employeesLoading && state.employeesError && (
            <div className="notice notice-error" role="alert">
              <div><strong>数字员工读取失败</strong><p>{state.employeesError.message}</p></div>
              {state.employeesError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          )}

          {!state.employeesLoading && !state.employeesError && usableEmployees.length === 0 && (
            <div className="composer-hint composer-hint--empty">
              <strong>还没有启用中的数字员工</strong>
              <span>先创建岗位与数字员工，这里才能派活。</span>
              {onNavigate && <button className="text-action" type="button" onClick={() => onNavigate('workforceSettings')}>去创建</button>}
            </div>
          )}

          {state.submitError && (
            <div className="notice notice-error" role="alert">
              <div><strong>任务创建失败</strong><p>{state.submitError.message}</p></div>
            </div>
          )}
        </section>

        <section className="home-drafts" aria-label="最近的内容草稿">
          <div className="home-section-head">
            <h2>最近的内容草稿</h2>
            {onNavigate && <button className="text-action" type="button" onClick={() => onNavigate('history')}>查看全部</button>}
          </div>

          {state.draftsLoading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载内容草稿…</div>}

          {!state.draftsLoading && state.draftsError && (
            <div className="notice notice-error" role="alert">
              <div><strong>内容草稿加载失败</strong><p>{state.draftsError.message}</p></div>
              {state.draftsError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          )}

          {!state.draftsLoading && !state.draftsError && state.drafts.length === 0 && (
            <div className="empty-state"><strong>还没有内容草稿</strong><span>在「内容工作台」提交主题后，草稿会出现在这里。</span></div>
          )}

          {!state.draftsLoading && !state.draftsError && state.drafts.length > 0 && (
            <div className="home-card-grid">
              {state.drafts.map((item) => <DraftCard draft={item} onOpen={() => onOpenTask(item.task_id)} key={item.task_id} />)}
            </div>
          )}
        </section>
      </main>
      <Toast message={state.toast} />
    </AppShell>
  )
}

function DraftCard({ draft, onOpen }: { draft: HomeDraft; onOpen: () => void }) {
  return (
    <button className="home-card" type="button" onClick={onOpen}>
      <span className="home-card-cover" aria-hidden="true"><Icon name="document" size={22} /></span>
      <span className="home-card-body">
        <strong>{draft.topic}</strong>
        <span className="home-card-meta">
          <span className={`status-badge status-${draft.status}`}>{draftStatusLabel(draft.status)}</span>
          <span>更新于 {formatDraftTime(draft.updated_at)}</span>
        </span>
      </span>
    </button>
  )
}
