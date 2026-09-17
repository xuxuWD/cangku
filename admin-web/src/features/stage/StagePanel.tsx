import type { RunStream } from '../conversation/useRunStream'
import type { RunApproval } from '../runDetail/types'
import { finishReasonLabel, runStatusLabel } from '../runDetail/types'
import { formatLocalTime } from '../../utils/time'
import { ApprovalCard } from './ApprovalCard'
import { ProcessTimeline } from './ProcessTimeline'
import { FileDiffPanel, TerminalOutputPanel } from './ToolOutputPanels'
import type { RunApprovalsState } from './useRunApprovals'
import type { RunOverviewState } from './useRunOverview'

/** 收尾检查（**展示型**）：只标记「已完成 / 未完成」，不改变运行状态、不强制退回（§2.5）。 */
function WrapUpCheck({ metrics, approvals }: { metrics: NonNullable<RunOverviewState['metrics']>; approvals: RunApproval[] }) {
  const finished = metrics.status === 'completed' || metrics.status === 'failed' || Boolean(metrics.finished_at)
  if (!finished) return null
  const pending = approvals.filter((item) => item.status === 'pending').length
  const stepsDone = metrics.step_count === 0 || metrics.completed_step_count >= metrics.step_count
  const complete = stepsDone && pending === 0 && metrics.status !== 'failed'
  return (
    <section className="history-panel stage-panel" aria-label="收尾检查">
      <div className="panel-header">
        <h2>收尾检查</h2>
        <span className={`status-badge status-${complete ? 'completed' : 'failed'}`}>{complete ? '已完成' : '未完成'}</span>
      </div>
      <div className="panel-body">
        <div className="run-detail__grid">
          <div className="run-detail__item">
            <span className="run-detail__label">进度档</span>
            <span className="run-detail__value">
              {metrics.completed_step_count}/{metrics.step_count} 步
            </span>
          </div>
          <div className="run-detail__item">
            <span className="run-detail__label">未决审批</span>
            <span className="run-detail__value">{pending}</span>
          </div>
          <div className="run-detail__item">
            <span className="run-detail__label">结束原因</span>
            <span className="run-detail__value">{finishReasonLabel(metrics.finish_reason)}</span>
          </div>
        </div>
        <p className="stage-hint">只做展示，不改变运行状态（结构判定与一键重做在 P2c-4 提供）。</p>
      </div>
    </section>
  )
}

/**
 * 右侧舞台（P2c-1 §2.2；P2c-2 增终端输出 / 文件改动）：运行概览 / 收尾检查 / 过程时间线 /
 * 终端输出 / 文件改动 / 审批。纯展示组件——数据由页面的
 * `useRunOverview` / `useRunApprovals` / `useRunStream` 提供（单一来源）。
 * 纪律：无数据即空态，**不摆假面板**（终端 / diff 面板由帧数据驱动，无数据即不渲染）。
 */
export function StagePanel({
  runId,
  stream,
  overview,
  approvals,
  canDecide,
  expanded = false,
  onOpenRunDetail,
}: {
  runId?: string
  stream: RunStream
  overview: RunOverviewState
  approvals: RunApprovalsState
  canDecide: boolean
  /** 窄屏抽屉是否展开（宽屏由 CSS 强制展示该面板）。 */
  expanded?: boolean
  onOpenRunDetail?: (runId: string) => void
}) {
  const { metrics, loading, error } = overview
  const pendingCount = approvals.items.filter((item) => item.status === 'pending').length

  return (
    <aside className={`conversation-stage ${expanded ? 'conversation-stage--open' : ''}`} aria-label="右侧舞台">
      <section className="history-panel stage-panel" aria-label="运行概览">
        <div className="panel-header">
          <h2>运行概览</h2>
          {metrics && <span>{runStatusLabel(metrics.status)}</span>}
        </div>
        {!runId && (
          <div className="empty-state">
            <strong>暂无运行</strong>
            <span>发起一次结构化工具调用后，这里会显示本次运行的概览、过程与审批。</span>
          </div>
        )}
        {runId && loading && !metrics && (
          <div className="loading-state" role="status">
            <span className="loading-dot" />
            正在加载运行概览…
          </div>
        )}
        {runId && !loading && error && (
          <div className="notice notice-error" role="alert">
            <div>
              <strong>运行概览加载失败</strong>
              <p>{error.message}</p>
            </div>
            {error.retryable && (
              <button className="text-action" type="button" onClick={overview.reload}>
                重新尝试
              </button>
            )}
          </div>
        )}
        {runId && metrics && (
          <div className="panel-body">
            <div className="run-detail__grid">
              <div className="run-detail__item">
                <span className="run-detail__label">运行状态</span>
                <span className={`status-badge status-${metrics.status}`}>{runStatusLabel(metrics.status)}</span>
              </div>
              <div className="run-detail__item">
                <span className="run-detail__label">步骤完成度</span>
                <span className="run-detail__value">
                  {metrics.completed_step_count}/{metrics.step_count}
                </span>
              </div>
              <div className="run-detail__item">
                <span className="run-detail__label">工具调用</span>
                <span className="run-detail__value">{metrics.tool_calls}</span>
              </div>
              <div className="run-detail__item">
                <span className="run-detail__label">耗时</span>
                <span className="run-detail__value">{metrics.latency_ms} ms</span>
              </div>
              <div className="run-detail__item">
                <span className="run-detail__label">开始时间</span>
                <span className="run-detail__value">{formatLocalTime(metrics.started_at)}</span>
              </div>
              <div className="run-detail__item">
                <span className="run-detail__label">结束时间</span>
                <span className="run-detail__value">{metrics.finished_at ? formatLocalTime(metrics.finished_at) : '—'}</span>
              </div>
            </div>
          </div>
        )}
      </section>

      {metrics && <WrapUpCheck metrics={metrics} approvals={approvals.items} />}

      <section className="history-panel stage-panel" aria-label="过程时间线">
        <div className="panel-header">
          <h2>过程</h2>
          {stream.lastSeq > 0 && <span>最新序号 {stream.lastSeq}</span>}
        </div>
        <ProcessTimeline frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />
      </section>

      <TerminalOutputPanel frames={stream.frames} />
      <FileDiffPanel frames={stream.frames} />

      <section className="history-panel stage-panel" aria-label="审批">
        <div className="panel-header">
          <h2>审批</h2>
          {approvals.items.length > 0 && <span>{pendingCount} 项待批</span>}
        </div>
        {!runId && (
          <div className="empty-state">
            <strong>暂无审批</strong>
            <span>本次会话还没有可关联的运行。</span>
          </div>
        )}
        {runId && approvals.loading && approvals.items.length === 0 && (
          <div className="loading-state" role="status">
            <span className="loading-dot" />
            正在加载审批项…
          </div>
        )}
        {runId && approvals.error && (
          <div className="notice notice-error" role="alert">
            <div>
              <strong>审批项加载失败</strong>
              <p>{approvals.error.message}</p>
            </div>
            {approvals.error.retryable && (
              <button className="text-action" type="button" onClick={approvals.reload}>
                重新尝试
              </button>
            )}
          </div>
        )}
        {runId && !approvals.loading && !approvals.error && approvals.items.length === 0 && (
          <div className="empty-state">
            <strong>没有审批项</strong>
            <span>本次运行未请求人工审批。</span>
          </div>
        )}
        {runId && approvals.items.map((approval) => (
          <ApprovalCard
            key={approval.approval_id}
            approval={approval}
            canDecide={canDecide}
            deciding={approvals.decidingId === approval.approval_id}
            onDecide={(approved) => void approvals.decide(approval.approval_id, approved)}
          />
        ))}
        {runId && onOpenRunDetail && (
          <div className="panel-body">
            <button className="text-action" type="button" onClick={() => onOpenRunDetail(runId)}>
              在运行详情中打开
            </button>
          </div>
        )}
      </section>
    </aside>
  )
}