import type { RunStream } from '../conversation/useRunStream'
import { conversationModeLabel } from '../conversation/types'
import type { RunApproval } from '../runDetail/types'
import { finishReasonLabel, runStatusLabel } from '../runDetail/types'
import { RunActions } from '../runDetail/RunActions'
import { formatLocalTime } from '../../utils/time'
import { ApprovalCard } from './ApprovalCard'
import { ArtifactPanel } from './ArtifactPanel'
import { ParticipantPanel, type CollaborationPanelState } from './ParticipantPanel'
import { ProcessTimeline } from './ProcessTimeline'
import { FileDiffPanel, TerminalOutputPanel } from './ToolOutputPanels'
import type { RunAcceptanceState } from './useRunAcceptance'
import type { RunApprovalsState } from './useRunApprovals'
import type { RunArtifactsState } from './useRunArtifacts'
import type { RunOverviewState } from './useRunOverview'

/**
 * 收尾检查（P2c-4 §2.5）：运行终态后展示「进度档 + 未决审批 + 结束原因 + 会话模式 + 产物数」，
 * 并给出**服务端的结构判定结论「达标 / 未达标」**（三条件全满足＝达标）。
 *
 * 纪律：判定由服务端给出（**不调模型、不改运行状态**），前端只渲染结论与分项、**不自行复算**；
 * 未达标时提供**一键重做**——仅当本页仍持有原结构化调用时可用（新幂等键 = 一次新的正常调用，
 * 与原运行无状态耦合）；原件已不在（刷新 / 跨页）时**如实告知**「请重新输入」，不假装能重放。
 */
function WrapUpCheck({
  metrics,
  approvals,
  acceptance,
  mode,
  artifactCount,
  redoAvailable,
  onRedo,
}: {
  metrics: NonNullable<RunOverviewState['metrics']>
  approvals: RunApproval[]
  acceptance: RunAcceptanceState
  mode: string | undefined
  artifactCount: number
  redoAvailable: boolean
  onRedo?: () => void
}) {
  const finished = metrics.status === 'completed' || metrics.status === 'failed' || Boolean(metrics.finished_at)
  if (!finished) return null
  const pending = approvals.filter((item) => item.status === 'pending').length
  const stepsDone = metrics.step_count === 0 || metrics.completed_step_count >= metrics.step_count
  const verdict = acceptance.acceptance?.verdict ?? null
  const badge = verdict === 'met' ? '达标' : verdict === 'unmet' ? '未达标' : '判定不可用'
  const badgeClass = verdict === 'met' ? 'completed' : verdict === 'unmet' ? 'failed' : 'reviewing'
  const unmet = verdict === 'unmet'
  return (
    <section className="history-panel stage-panel" aria-label="收尾检查">
      <div className="panel-header">
        <h2>收尾检查</h2>
        <span className={`status-badge status-${badgeClass}`}>{badge}</span>
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
          <div className="run-detail__item">
            <span className="run-detail__label">会话模式</span>
            <span className="run-detail__value">{mode ? conversationModeLabel(mode) : '—'}</span>
          </div>
          <div className="run-detail__item">
            <span className="run-detail__label">产物</span>
            <span className="run-detail__value">{artifactCount} 项</span>
          </div>
        </div>

        {acceptance.loading && !acceptance.acceptance && (
          <div className="loading-state" role="status"><span className="loading-dot" />正在读取结构判定…</div>
        )}
        {acceptance.error && (
          <div className="notice notice-error" role="alert">
            <div><strong>结构判定读取失败</strong><p>{acceptance.error.message}</p></div>
            {acceptance.error.retryable && (
              <button className="text-action" type="button" onClick={acceptance.reload}>重新尝试</button>
            )}
          </div>
        )}
        {acceptance.acceptance && (
          <p className="stage-hint">
            结构判定（按运行记录逐项核对，不改动运行）：步骤完成
            {acceptance.acceptance.checks.steps_complete ? '✓' : '✗'} · 无未决审批
            {acceptance.acceptance.checks.no_pending_approvals ? '✓' : '✗'} · 正常终态
            {acceptance.acceptance.checks.finish_reason_ok ? '✓' : '✗'}
          </p>
        )}
        {!acceptance.acceptance && !acceptance.loading && !acceptance.error && (
          <p className="stage-hint">
            未取得结构判定：{stepsDone && pending === 0 && metrics.status !== 'failed'
              ? '本地展示口径看似完成，但判定以服务端为准（请重试读取）。'
              : '未达标迹象已出现，判定以服务端为准（请重试读取）。'}
          </p>
        )}

        {unmet && redoAvailable && onRedo && (
          <>
            <div className="panel-body">
              <button className="button" type="button" onClick={onRedo}>一键重做</button>
            </div>
            <p className="stage-hint">
              重做 = 重新发出本页仍保留的那次调用（算一次新的运行，不改动原运行）；判定与重做都不会自动重跑。
            </p>
          </>
        )}
        {unmet && !redoAvailable && (
          <p className="stage-hint">
            未达标：原始调用内容没有留存（安全口径，消息只保存脱敏摘要），已无法一键重做——请重新输入调用后再次发送。
          </p>
        )}
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
  artifacts,
  acceptance,
  mode,
  redoAvailable = false,
  onRedo,
  canDecide,
  expanded = false,
  onOpenRunDetail,
  canIntervene = false,
  onNotice,
  collaboration,
}: {
  runId?: string
  stream: RunStream
  overview: RunOverviewState
  approvals: RunApprovalsState
  /** 产物登记（P2c-3；由页面的 `useRunArtifacts` 提供，纯展示）。 */
  artifacts: RunArtifactsState
  /** 结构判定（P2c-4；由页面的 `useRunAcceptance` 提供，纯展示）。 */
  acceptance: RunAcceptanceState
  /** 会话模式（P2c-4；来自会话详情，纯展示）。 */
  mode?: string
  /** 一键重做是否可用（= 本页仍持有原结构化调用；刷新 / 跨页后不可用）。 */
  redoAvailable?: boolean
  onRedo?: () => void
  canDecide: boolean
  /** 窄屏抽屉是否展开（宽屏由 CSS 强制展示该面板）。 */
  expanded?: boolean
  onOpenRunDetail?: (runId: string) => void
  /** S4：是否展示干预动作（暂停 / 恢复 / 取消）——由页面的运行概览推得，服务端仍是权威。 */
  canIntervene?: boolean
  /** S4：干预成功后的提示出口（页面 Toast）；失败提示由动作组件就地展示。 */
  onNotice?: (message: string) => void
  /**
   * 参与者与分享（P2c-6；由页面提供数据与增删回调，本组件只呈现）。
   * 未传入（如运行详情页复用舞台）⇒ 不渲染该区块（零破坏）。
   */
  collaboration?: CollaborationPanelState
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
            {/* S4：干预动作贴着运行状态（终态自动不渲染；可见性≠权限，服务端仍是权威）。 */}
            <RunActions
              runId={runId}
              status={metrics.status}
              canOperate={canIntervene}
              onRefresh={() => {
                overview.reload()
                approvals.reload()
                acceptance.reload()
              }}
              onNotice={onNotice}
            />
          </div>
        )}
      </section>

      {metrics && (
        <WrapUpCheck
          metrics={metrics}
          approvals={approvals.items}
          acceptance={acceptance}
          mode={mode}
          artifactCount={artifacts.items.length}
          redoAvailable={redoAvailable}
          onRedo={onRedo}
        />
      )}

      <section className="history-panel stage-panel" aria-label="过程时间线">
        <div className="panel-header">
          <h2>过程</h2>
          {stream.lastSeq > 0 && <span>最新序号 {stream.lastSeq}</span>}
        </div>
        <ProcessTimeline frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />
      </section>

      <TerminalOutputPanel frames={stream.frames} />
      <FileDiffPanel frames={stream.frames} />
      <ArtifactPanel runId={runId} artifacts={artifacts} onOpenRunDetail={onOpenRunDetail} />

      {collaboration && <ParticipantPanel collaboration={collaboration} />}

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