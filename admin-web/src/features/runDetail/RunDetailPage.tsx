import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { ApprovalCard } from '../stage/ApprovalCard'
import { useRunAcceptance } from '../stage/useRunAcceptance'
import { useRunArtifacts } from '../stage/useRunArtifacts'
import { decideRunApproval, getRunMetrics, getTask, listRunApprovals, listRunEvents } from './api'
import { AcceptanceDecisionPanel } from './AcceptanceDecisionPanel'
import { publishApprovalDecided, subscribeApprovalDecided } from './approvalEvents'
import { RunActions } from './RunActions'
import { asRunError, initialRunDetailState } from './state'
import { changeKindLabel, finishReasonLabel, runApprovalOutcomeLabel, runEventLabel, runStatusLabel, RUN_EVENT_PAYLOAD_FIELDS, type RunDetailState, type RunEvent, type RunMetrics, type RunTask } from './types'
import { formatLocalTime } from '../../utils/time'

// 与 Promise.allSettled 等价，但立即挂上处理函数，避免并发请求的拒绝变成未处理异常。
function settle<T>(promise: Promise<T>): Promise<PromiseSettledResult<T>> {
  return promise.then(
    (value) => ({ status: 'fulfilled', value }) as PromiseSettledResult<T>,
    (reason) => ({ status: 'rejected', reason }) as PromiseSettledResult<T>,
  )
}


// 只渲染白名单字段；字符串/数字/布尔以外的值一律忽略。
function formatPayloadValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return ''
}

/**
 * 运行详情（UI v2 · T4 详情页骨架）。
 *
 * 四段：概览（指标 + 运行信息）· 交付（产物清单 + 结构判定，**只读**）· 审批 · 事件时间线；
 * 顶部动作区提供 S4 干预（暂停 / 恢复 / 取消，见 `RunActions`）——是否可操作由服务端判定，
 * 前端只按运行状态决定展示哪些按钮，失败时原样展示服务端的结论。
 *
 * 纪律：
 * - **无假按钮**：验收确认 / 打回重做 / 存成任务都接服务端动作；「设为自动化」未交付，只给行内说明；
 * - **不自行复算**：结构判定与状态一律取服务端结论，不在前端二次计算「算不算完成」。
 */
export function RunDetailPage({
  runId,
  onNavigate,
  originConversationId,
  onOpenConversation,
}: {
  runId: string
  onNavigate?: (view: AppView) => void
  /** S3：来源会话（由 URL `&conversation=` 带过来）；有它才给「回到会话」退路。 */
  originConversationId?: string
  onOpenConversation?: (conversationId: string) => void
}) {
  const [state, setState] = useState<RunDetailState>(initialRunDetailState)
  const update = useCallback((patch: Partial<RunDetailState>) => setState((old) => ({ ...old, ...patch })), [])
  // 交付区的两个只读数据源（与对话页舞台同源同投影；本页不重复实现）。
  const artifacts = useRunArtifacts(runId)
  const acceptance = useRunAcceptance(runId)

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

  // S1「三处一致」：对话流 / 舞台任一处决议后，这里也刷新为同一权威态（服务端回流，不本地合并）。
  useEffect(() => {
    return subscribeApprovalDecided((event) => {
      if (event.runId !== runId) return
      void reloadApprovals()
      void reloadOverview()
    })
  }, [runId, reloadApprovals, reloadOverview])

  const decide = async (approvalId: string, approved: boolean) => {
    update({ decidingId: approvalId, toast: null })
    try {
      const decision = await decideRunApproval(runId, approvalId, approved)
      // 广播 ⇒ 对话流 / 舞台同步刷新；本页随后自行 load。
      publishApprovalDecided(runId, approvalId)
      await load()
      // §4.1.6-7：可选 `execution` 存在时把执行结局并入提示；缺省即不追加（既有行为不变）。
      const suffix = decision?.execution ? `（${runApprovalOutcomeLabel(decision.execution.outcome)}）` : ''
      update({ decidingId: null, toast: (approved ? '已通过' : '已驳回') + suffix })
    } catch (error) {
      const mapped = asRunError(error)
      // 409 表示审批已被决议，直接刷新拿到最新状态。
      if (mapped.status === 409) await load()
      update({ decidingId: null, toast: mapped.message })
    }
  }

  // S4 干预成功后：概览 / 事件 / 审批 / 交付全部按**服务端权威态**重取（不做本地乐观更新）。
  const refreshAfterAction = useCallback(async () => {
    await Promise.all([load(), Promise.resolve(artifacts.reload()), Promise.resolve(acceptance.reload())])
  }, [load, artifacts, acceptance])

  const pageError = state.metricsError && state.taskError ? state.metricsError : null
  const currentUserId = import.meta.env.VITE_USER_ID || 'admin'
  const role = import.meta.env.VITE_USER_ROLE || 'super_admin'
  const isInitiator = state.task !== null && state.task.created_by === currentUserId
  // 与对话页同一判定口径：仅 CEO / 超级管理员可决议，发起人不得自审（服务端仍是权威）。
  const canDecide = (role === 'ceo' || role === 'super_admin') && !isInitiator
  // 干预权限：发起人本人或 CEO / 超管；承载任务读不到时**不预判**（避免误伤发起人，服务端仍是权威）。
  const canIntervene = state.task === null || isInitiator || role === 'ceo' || role === 'super_admin'
  const sortedEvents = [...state.events].sort((left, right) => left.sequence - right.sequence)
  const taskLabel = state.task?.title ?? `运行 ${runId}`

  return <>
    <main className="main-content content-history t3 run-detail">
      {/* S3：面包屑 + 回到会话（**只在有来源会话时出现**；从通知等入口进来则不给假按钮） */}
      {originConversationId && (
        <div className="crumbs">
          <button className="text-action" type="button" onClick={() => onOpenConversation?.(originConversationId)}>
            ← 回到会话
          </button>
          <span>对话 / 运行详情</span>
          <span className="page-code">{originConversationId}</span>
        </div>
      )}

      <div className="t3__intro">
        <p className="page-desc">这次运行做了什么、停在哪里、交付了什么，都记在这一页。暂停与取消由你发起，状态一律以服务端记录为准。</p>
        <div className="t3__actions">
          <RunActions
            runId={runId}
            status={state.metrics?.status}
            canOperate={canIntervene}
            onRefresh={refreshAfterAction}
            onNotice={(message) => update({ toast: message })}
          />
          <button className="btn btn--secondary" type="button" disabled={state.loadingOverview} onClick={() => void load()}>
            {state.loadingOverview ? '正在刷新' : '刷新'}
          </button>
        </div>
      </div>

      {pageError && (
        <div className="notice notice-error" role="alert">
          <div><strong>运行详情加载失败</strong><p>{pageError.message}</p></div>
          <button className="text-action" type="button" onClick={() => void reloadOverview()}>重新尝试</button>
        </div>
      )}

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">运行状态</div>
          <div className="metric__value">
            {state.loadingOverview && !state.metrics ? '—' : state.metrics ? <span className={`status-badge status-${state.metrics.status}`}>{runStatusLabel(state.metrics.status)}</span> : '—'}
          </div>
          <div className="metric__hint">由系统在每次推进后回写</div>
        </div>
        <div className="metric">
          <div className="metric__label">步骤完成度</div>
          <div className="metric__value">{state.metrics ? `${state.metrics.completed_step_count}/${state.metrics.step_count}` : '—'}</div>
          <div className="metric__hint">已推进的步骤 / 计划步骤</div>
        </div>
        <div className="metric">
          <div className="metric__label">工具调用</div>
          <div className="metric__value">{state.metrics ? state.metrics.tool_calls : '—'}</div>
          <div className="metric__hint">本次运行发起的调用次数</div>
        </div>
        <div className="metric">
          <div className="metric__label">耗时</div>
          <div className="metric__value">{state.metrics ? `${state.metrics.latency_ms} ms` : '—'}</div>
          <div className="metric__hint">从开始到最近一次记录的时间</div>
        </div>
      </div>

      <section className="card" aria-label="运行信息">
        <div className="card__head">
          <h2>运行信息</h2>
          {state.loadingOverview && <span className="role-note">正在加载…</span>}
        </div>
        <div className="card__body">
          {!state.loadingOverview && !state.metrics && !pageError && state.metricsError && (
            <div className="notice notice-error" role="alert">
              <div><strong>运行概览加载失败</strong><p>{state.metricsError.message}</p></div>
              <button className="text-action" type="button" onClick={() => void reloadOverview()}>重新尝试</button>
            </div>
          )}
          {state.metrics && (
            <div className="kv">
              <div className="kv__item">
                <span className="kv__label">任务</span>
                <span className="kv__value">{taskLabel}</span>
              </div>
              <div className="kv__item">
                <span className="kv__label">开始时间</span>
                <span className="kv__value">{formatLocalTime(state.metrics.started_at)}</span>
              </div>
              <div className="kv__item">
                <span className="kv__label">结束时间</span>
                <span className="kv__value">{state.metrics.finished_at ? formatLocalTime(state.metrics.finished_at) : '—'}</span>
              </div>
              <div className="kv__item">
                <span className="kv__label">结束原因</span>
                <span className="kv__value">{finishReasonLabel(state.metrics.finish_reason)}</span>
              </div>
              <div className="kv__item">
                <span className="kv__label">运行号</span>
                <span className="kv__value page-code">{state.metrics.run_id}</span>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="card" aria-label="交付">
        <div className="card__head">
          <h2>交付</h2>
          {acceptance.acceptance && (
            <span className={`status-badge status-${verdictClass(acceptance.acceptance.verdict)}`}>{verdictLabel(acceptance.acceptance.verdict)}</span>
          )}
        </div>
        <div className="card__body">
          {/* ① 产物清单（只读元数据；与对话页舞台同源） */}
          {artifacts.loading && artifacts.items.length === 0 && (
            <div className="loading-state" role="status"><span className="loading-dot" />正在加载交付物…</div>
          )}
          {!artifacts.loading && artifacts.error && (
            <div className="notice notice-error" role="alert">
              <div><strong>交付物加载失败</strong><p>{artifacts.error.message}</p></div>
              {artifacts.error.retryable && <button className="text-action" type="button" onClick={artifacts.reload}>重新尝试</button>}
            </div>
          )}
          {!artifacts.loading && !artifacts.error && artifacts.items.length === 0 && (
            <p className="stage-hint">本次运行没有交付物。只有真正写文件的步骤（新建 / 覆盖 / 删除）才会登记交付物。</p>
          )}
          {!artifacts.error && artifacts.items.length > 0 && (
            <>
              <ul className="artifact-list">
                {artifacts.items.map((item) => (
                  <li className="artifact-row" key={item.artifact_id}>
                    <span className="artifact-row__path">{item.virtual_path}</span>
                    <span className="artifact-row__kind">{changeKindLabel(item.change_kind)}</span>
                    <span className="artifact-row__bytes">{item.bytes} B</span>
                    <span className="artifact-row__sha" title={item.sha256}>{item.sha256.slice(0, 19)}…</span>
                  </li>
                ))}
              </ul>
              <p className="stage-hint">只登记元数据（路径 / 类型 / 字节 / 摘要），不含文件内容；超过保留期的条目不再返回。</p>
            </>
          )}

          {/* ② 结构判定（三条件，服务端只读运行字段给出；前端只渲染分项，不自行复算） */}
          {acceptance.loading && !acceptance.acceptance && (
            <div className="loading-state" role="status"><span className="loading-dot" />正在读取验收判定…</div>
          )}
          {acceptance.error && (
            <div className="notice notice-error" role="alert">
              <div><strong>验收判定读取失败</strong><p>{acceptance.error.message}</p></div>
              {acceptance.error.retryable && <button className="text-action" type="button" onClick={acceptance.reload}>重新尝试</button>}
            </div>
          )}
          {acceptance.acceptance && (
            <ul className="check-list">
              <CheckItem ok={acceptance.acceptance.checks.steps_complete} label="步骤全部完成">
                {acceptance.acceptance.steps.completed}/{acceptance.acceptance.steps.total} 步已推进
              </CheckItem>
              <CheckItem ok={acceptance.acceptance.checks.no_pending_approvals} label="没有未决审批">
                {acceptance.acceptance.pending_approvals > 0 ? `${acceptance.acceptance.pending_approvals} 项审批仍待决议` : '审批都已决议'}
              </CheckItem>
              <CheckItem ok={acceptance.acceptance.checks.finish_reason_ok} label="正常结束">
                {acceptance.acceptance.finish_reason ? finishReasonLabel(acceptance.acceptance.finish_reason) : '运行尚未结束'}
              </CheckItem>
            </ul>
          )}
          {acceptance.acceptance?.verdict === 'unmet' && (
            <p className="stage-hint">
              未达标：本页不保留原始调用参数，无法在这里直接重做；请回到发起这次运行的对话页使用「一键重做」。
            </p>
          )}
          {!acceptance.acceptance && !acceptance.loading && !acceptance.error && (
            <p className="stage-hint">未取得验收判定，判定以系统记录为准（可稍后重试读取）。</p>
          )}

          {/* ③ 人工验收（S2 写侧）：确认完成 / 打回重做（带原因）→ 确认后出「存成任务」沉淀入口 */}
          <AcceptanceDecisionPanel
            runId={runId}
            runStatus={state.metrics?.status}
            canDecide={canIntervene}
            defaultTitle={state.task?.title}
            onRefresh={refreshAfterAction}
            onNotice={(message) => update({ toast: message })}
          />
        </div>
      </section>

      <section className="card" aria-label="审批">
        <div className="card__head">
          <h2>审批</h2>
          <span className="role-note">{state.approvals.length} 项</span>
        </div>
        <div className="card__body">
          {state.loadingApprovals && <div className="loading-state" role="status"><span className="loading-dot" />正在加载审批…</div>}
          {!state.loadingApprovals && state.approvalsError && (
            <div className="notice notice-error" role="alert">
              <div><strong>审批加载失败</strong><p>{state.approvalsError.message}</p></div>
              <button className="text-action" type="button" onClick={() => void reloadApprovals()}>重新尝试</button>
            </div>
          )}
          {!state.loadingApprovals && !state.approvalsError && state.approvals.length === 0 && (
            <p className="stage-hint">该运行没有审批项；运行内请求人工审批后会展示在这里。</p>
          )}
          {!state.loadingApprovals && !state.approvalsError && state.approvals.length > 0 && (
            <div className="approvals-stack" role="list">
              {state.approvals.map((approval) => (
                <ApprovalCard
                  approval={approval}
                  canDecide={canDecide}
                  deciding={state.decidingId === approval.approval_id}
                  onDecide={(approved) => void decide(approval.approval_id, approved)}
                  key={approval.approval_id}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="card" aria-label="事件时间线">
        <div className="card__head">
          <h2>事件时间线</h2>
          <span className="role-note">{state.events.length} 条</span>
        </div>
        {state.loadingEvents && <div className="loading-state" role="status"><span className="loading-dot" />正在加载事件…</div>}
        {!state.loadingEvents && state.eventsError && (
          <div className="card__body">
            <div className="notice notice-error" role="alert">
              <div><strong>事件加载失败</strong><p>{state.eventsError.message}</p></div>
              <button className="text-action" type="button" onClick={() => void reloadEvents()}>重新尝试</button>
            </div>
          </div>
        )}
        {!state.loadingEvents && !state.eventsError && sortedEvents.length === 0 && (
          <div className="card__body"><p className="stage-hint">暂无事件；运行产生事件后会展示在这里。</p></div>
        )}
        {!state.loadingEvents && !state.eventsError && sortedEvents.length > 0 && (
          <div className="rows" role="list">
            {sortedEvents.map((event) => <EventRow event={event} key={event.cursor} />)}
          </div>
        )}
      </section>
    </main>
    <Toast message={state.toast} />
  </>
}

function verdictLabel(verdict: string): string {
  if (verdict === 'met') return '达标'
  if (verdict === 'unmet') return '未达标'
  return '判定不可用'
}

function verdictClass(verdict: string): string {
  if (verdict === 'met') return 'completed'
  if (verdict === 'unmet') return 'failed'
  return 'reviewing'
}

/** 验收分项：只呈现服务端给出的布尔结论与计数，不在前端重判。 */
function CheckItem({ ok, label, children }: { ok: boolean; label: string; children: ReactNode }) {
  return (
    <li className={`check-item ${ok ? 'is-ok' : 'is-bad'}`}>
      <span className="check-item__mark" aria-hidden="true">{ok ? '✓' : '✗'}</span>
      <span className="check-item__label">{label}（{ok ? '已满足' : '未满足'}）</span>
      {children && <span className="check-item__note">{children}</span>}
    </li>
  )
}

function EventRow({ event }: { event: RunEvent }) {
  const summary = RUN_EVENT_PAYLOAD_FIELDS.map(({ key, label }) => {
    const text = formatPayloadValue(event.payload[key])
    return text ? `${label} ${text}` : ''
  }).filter(Boolean).join(' · ')
  return <div className="row" role="listitem">
    <div className="row__main">
      <span className="row__title">#{event.sequence} {runEventLabel(event.event_type)}</span>
      {summary && <span className="row__sub">{summary}</span>}
    </div>
  </div>
}