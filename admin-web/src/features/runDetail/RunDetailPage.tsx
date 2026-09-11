import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { decideRunApproval, getRunMetrics, getTask, listRunApprovals, listRunEvents } from './api'
import { asRunError, initialRunDetailState } from './state'
import { approvalStatusLabel, finishReasonLabel, runEventLabel, runStatusLabel, RUN_EVENT_PAYLOAD_FIELDS, type RunApproval, type RunDetailState, type RunEvent, type RunMetrics, type RunTask } from './types'

// 与 Promise.allSettled 等价，但立即挂上处理函数，避免并发请求的拒绝变成未处理异常。
function settle<T>(promise: Promise<T>): Promise<PromiseSettledResult<T>> {
  return promise.then(
    (value) => ({ status: 'fulfilled', value }) as PromiseSettledResult<T>,
    (reason) => ({ status: 'rejected', reason }) as PromiseSettledResult<T>,
  )
}

function formatLocalTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

// 只渲染白名单字段；字符串/数字/布尔以外的值一律忽略。
function formatPayloadValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return ''
}

export function RunDetailPage({ runId, onNavigate }: { runId: string; onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<RunDetailState>(initialRunDetailState)
  const update = useCallback((patch: Partial<RunDetailState>) => setState((old) => ({ ...old, ...patch })), [])

  // 指标与任务同属「概览」区：指标失败时任务也拿不到（缺 task_id），两区一起失败才升级为整页级错误。
  const applyOverview = useCallback((metricsResult: PromiseSettledResult<RunMetrics>, taskResult: PromiseSettledResult<RunTask> | null) => {
    const metrics = metricsResult.status === 'fulfilled' ? metricsResult.value : null
    const metricsError = metricsResult.status === 'fulfilled' ? null : asRunError(metricsResult.reason)
    const task = taskResult && taskResult.status === 'fulfilled' ? taskResult.value : null
    const taskError = taskResult ? (taskResult.status === 'fulfilled' ? null : asRunError(taskResult.reason)) : metricsError
    return { metrics, metricsError, task, taskError }
  }, [])

  const load = useCallback(async () => {
    update({ loadingOverview: true, loadingEvents: true, loadingApprovals: true, toast: null })
    // 事件与审批和指标并发；任务需等指标返回 task_id 后再取。
    const eventsSettled = settle(listRunEvents(runId))
    const approvalsSettled = settle(listRunApprovals(runId))
    const [metricsResult] = await Promise.allSettled([getRunMetrics(runId)])
    let taskResult: PromiseSettledResult<RunTask> | null = null
    if (metricsResult.status === 'fulfilled') {
      const [settled] = await Promise.allSettled([getTask(metricsResult.value.task_id)])
      taskResult = settled
    }
    const eventsResult = await eventsSettled
    const approvalsResult = await approvalsSettled
    setState((old) => ({
      ...old,
      ...applyOverview(metricsResult, taskResult),
      events: eventsResult.status === 'fulfilled' && Array.isArray(eventsResult.value) ? eventsResult.value : [],
      eventsError: eventsResult.status === 'fulfilled' ? null : asRunError(eventsResult.reason),
      approvals: approvalsResult.status === 'fulfilled' && Array.isArray(approvalsResult.value.items) ? approvalsResult.value.items : [],
      approvalsError: approvalsResult.status === 'fulfilled' ? null : asRunError(approvalsResult.reason),
      loadingOverview: false,
      loadingEvents: false,
      loadingApprovals: false,
    }))
  }, [runId, applyOverview, update])

  useEffect(() => { void load() }, [load])

  const reloadOverview = useCallback(async () => {
    update({ loadingOverview: true })
    const [metricsResult] = await Promise.allSettled([getRunMetrics(runId)])
    let taskResult: PromiseSettledResult<RunTask> | null = null
    if (metricsResult.status === 'fulfilled') {
      const [settled] = await Promise.allSettled([getTask(metricsResult.value.task_id)])
      taskResult = settled
    }
    setState((old) => ({ ...old, ...applyOverview(metricsResult, taskResult), loadingOverview: false }))
  }, [runId, applyOverview, update])

  const reloadEvents = useCallback(async () => {
    update({ loadingEvents: true })
    const result = await settle(listRunEvents(runId))
    setState((old) => ({ ...old, events: result.status === 'fulfilled' && Array.isArray(result.value) ? result.value : [], eventsError: result.status === 'fulfilled' ? null : asRunError(result.reason), loadingEvents: false }))
  }, [runId, update])

  const reloadApprovals = useCallback(async () => {
    update({ loadingApprovals: true })
    const result = await settle(listRunApprovals(runId))
    setState((old) => ({ ...old, approvals: result.status === 'fulfilled' && Array.isArray(result.value.items) ? result.value.items : [], approvalsError: result.status === 'fulfilled' ? null : asRunError(result.reason), loadingApprovals: false }))
  }, [runId, update])

  const decide = async (approvalId: string, approved: boolean) => {
    update({ decidingId: approvalId, toast: null })
    try {
      await decideRunApproval(runId, approvalId, approved)
      await load()
      update({ decidingId: null, toast: approved ? '已通过' : '已驳回' })
    } catch (error) {
      const mapped = asRunError(error)
      // 409 表示审批已被决议，直接刷新拿到最新状态。
      if (mapped.status === 409) await load()
      update({ decidingId: null, toast: mapped.message })
    }
  }

  const pageError = state.metricsError && state.taskError ? state.metricsError : null
  const currentUserId = import.meta.env.VITE_USER_ID || 'admin'
  const isInitiator = state.task !== null && state.task.created_by === currentUserId
  const sortedEvents = [...state.events].sort((left, right) => left.sequence - right.sequence)
  const title = state.task?.title ?? `运行 ${runId}`

  return <AppShell activeView="run" onNavigate={onNavigate}>
    <main className="main-content content-history run-detail">
      <div className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-desc">展示该次运行的指标、事件时间线与审批项；审批通过与驳回由后端状态驱动。</p>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
      </div>

      {pageError && <div className="notice notice-error" role="alert"><div><strong>运行详情加载失败</strong><p>{pageError.message}</p></div><button className="text-action" type="button" onClick={() => void reloadOverview()}>重新尝试</button></div>}

      <section className="history-panel run-detail__panel" aria-label="运行概览">
        <div className="panel-header"><h2>运行概览</h2>{state.metrics && <span>{runStatusLabel(state.metrics.status)}</span>}</div>
        {state.loadingOverview && <div className="loading-state" role="status"><span className="loading-dot" />正在加载运行详情…</div>}
        {!state.loadingOverview && state.metrics && <div className="panel-body">
          <div className="run-detail__grid">
            <div className="run-detail__item"><span className="run-detail__label">运行状态</span><span className={`status-badge status-${state.metrics.status}`}>{runStatusLabel(state.metrics.status)}</span></div>
            <div className="run-detail__item"><span className="run-detail__label">结束原因</span><span className="run-detail__value">{finishReasonLabel(state.metrics.finish_reason)}</span></div>
            <div className="run-detail__item"><span className="run-detail__label">步骤完成度</span><span className="run-detail__value">{state.metrics.completed_step_count}/{state.metrics.step_count}</span></div>
            <div className="run-detail__item"><span className="run-detail__label">工具调用</span><span className="run-detail__value">{state.metrics.tool_calls}</span></div>
            <div className="run-detail__item"><span className="run-detail__label">耗时</span><span className="run-detail__value">{state.metrics.latency_ms} ms</span></div>
            <div className="run-detail__item"><span className="run-detail__label">开始时间</span><span className="run-detail__value">{formatLocalTime(state.metrics.started_at)}</span></div>
            <div className="run-detail__item"><span className="run-detail__label">结束时间</span><span className="run-detail__value">{state.metrics.finished_at ? formatLocalTime(state.metrics.finished_at) : '—'}</span></div>
          </div>
        </div>}
        {!state.loadingOverview && !state.metrics && !pageError && state.metricsError && <div className="notice notice-error" role="alert"><div><strong>运行概览加载失败</strong><p>{state.metricsError.message}</p></div><button className="text-action" type="button" onClick={() => void reloadOverview()}>重新尝试</button></div>}
      </section>

      <section className="history-panel run-detail__panel" aria-label="审批">
        <div className="panel-header"><h2>审批</h2><span>{state.approvals.length} 项</span></div>
        {state.loadingApprovals && <div className="loading-state" role="status"><span className="loading-dot" />正在加载审批…</div>}
        {!state.loadingApprovals && state.approvalsError && <div className="notice notice-error" role="alert"><div><strong>审批加载失败</strong><p>{state.approvalsError.message}</p></div><button className="text-action" type="button" onClick={() => void reloadApprovals()}>重新尝试</button></div>}
        {!state.loadingApprovals && !state.approvalsError && state.approvals.length === 0 && <div className="empty-state"><strong>该运行没有审批项</strong><span>运行内请求审批后会展示在这里。</span></div>}
        {!state.loadingApprovals && !state.approvalsError && state.approvals.length > 0 && <div className="history-list" role="list">
          {state.approvals.map((approval) => <ApprovalRow approval={approval} isInitiator={isInitiator} deciding={state.decidingId === approval.approval_id} onDecide={(approved) => void decide(approval.approval_id, approved)} key={approval.approval_id} />)}
        </div>}
      </section>

      <section className="history-panel run-detail__panel" aria-label="事件时间线">
        <div className="panel-header"><h2>事件时间线</h2><span>{state.events.length} 条</span></div>
        {state.loadingEvents && <div className="loading-state" role="status"><span className="loading-dot" />正在加载事件…</div>}
        {!state.loadingEvents && state.eventsError && <div className="notice notice-error" role="alert"><div><strong>事件加载失败</strong><p>{state.eventsError.message}</p></div><button className="text-action" type="button" onClick={() => void reloadEvents()}>重新尝试</button></div>}
        {!state.loadingEvents && !state.eventsError && sortedEvents.length === 0 && <div className="empty-state"><strong>暂无事件</strong><span>运行产生事件后会展示在这里。</span></div>}
        {!state.loadingEvents && !state.eventsError && sortedEvents.length > 0 && <div className="timeline run-detail__timeline" role="list">
          {sortedEvents.map((event) => <EventRow event={event} key={event.cursor} />)}
        </div>}
      </section>
    </main>
    <Toast message={state.toast} />
  </AppShell>
}

function ApprovalRow({ approval, isInitiator, deciding, onDecide }: { approval: RunApproval; isInitiator: boolean; deciding: boolean; onDecide: (approved: boolean) => void }) {
  const descriptor = approval.step_id || approval.tool ? `步骤 ${approval.step_id ?? '—'} / 工具 ${approval.tool ?? '—'}` : approval.approval_id
  const pending = approval.status === 'pending'
  return <article className="history-row" role="listitem">
    <div className="history-row-main">
      <strong>{descriptor}</strong>
      <div className="history-meta"><span className={`status-badge status-${approval.status}`}>{approvalStatusLabel(approval.status)}</span></div>
    </div>
    {pending && <div className="history-actions">
      {isInitiator
        ? <span className="run-detail__note">发起人不能审批自己发起的运行</span>
        : <><button className="button" type="button" disabled={deciding} onClick={() => onDecide(true)}>通过</button><button className="button danger" type="button" disabled={deciding} onClick={() => onDecide(false)}>驳回</button></>}
    </div>}
  </article>
}

function EventRow({ event }: { event: RunEvent }) {
  const summary = RUN_EVENT_PAYLOAD_FIELDS.map(({ key, label }) => {
    const text = formatPayloadValue(event.payload[key])
    return text ? `${label} ${text}` : ''
  }).filter(Boolean).join(' · ')
  return <article className="audit-event run-detail__event" role="listitem">
    <strong>#{event.sequence} {runEventLabel(event.event_type)}</strong>
    {summary && <p>{summary}</p>}
  </article>
}
