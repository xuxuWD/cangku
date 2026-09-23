/**
 * 右侧舞台（P2c-1 §2.2；P2c-2 增终端输出 / 文件改动）：运行概览 / 收尾检查 / 过程时间线 /
 * 终端输出 / 文件改动 / 产物登记 / 参与者 / 审批。
 *
 * **来源**：由 `admin-web/src/features/stage/StagePanel.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（**70 处 className**，是 stage 包里最大的一块）换成 **AntD + 项目组件库**，
 * 符合 ADR-0003。**逐模块归属照搬**（用户 2026-09-23 裁决：不改成"交给壳的右栏"）。
 *
 * **纯展示组件** —— 数据由页面的 `useRunOverview` / `useRunApprovals` / `useRunStream` 等提供
 * （单一来源）。纪律：**无数据即空态，不摆假面板**（终端 / diff 面板由帧驱动，无数据即不渲染）。
 *
 * ⚠️ 每一块都保留 `<section aria-label>`：AntD `Card` 渲染 `<div>`，拿不到 `region` 角色
 * （这条在移植中已踩到两次，见 `ToolOutputPanels` / `ArtifactPanel` 的注释）。
 */
import { Alert, Button, Card, Descriptions, Space, Typography } from 'antd'
import { EmptyState, SkeletonList, StatusTag } from '../../components'
import { formatDateTime } from '../../utils/format'
import { conversationModeLabel } from '../conversation/types'
import type { RunStream } from '../conversation/useRunStream'
import { RunActions } from '../runDetail/RunActions'
import { finishReasonLabel, runStatusLabel } from '../runDetail/types'
import type { RunApproval } from '../runDetail/types'
import { ApprovalCard } from './ApprovalCard'
import { ArtifactPanel } from './ArtifactPanel'
import { ParticipantPanel } from './ParticipantPanel'
import type { CollaborationPanelState } from './ParticipantPanel'
import { ProcessTimeline } from './ProcessTimeline'
import { FileDiffPanel, TerminalOutputPanel } from './ToolOutputPanels'
import type { RunAcceptanceState } from './useRunAcceptance'
import type { RunApprovalsState } from './useRunApprovals'
import type { RunArtifactsState } from './useRunArtifacts'
import type { RunOverviewState } from './useRunOverview'

/** 运行状态 / 判定 → 语义色（受控枚举，不在调用处写颜色）。 */
function runStatusTone(status: string): 'success' | 'danger' | 'warning' | 'neutral' | 'info' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'neutral'
  if (status === 'paused') return 'warning'
  return 'info'
}

/** 区块外壳：统一「标题 + 右上角附注 + 内容」的长相，并保证 `region` 角色。 */
function PanelSection({
  label,
  title,
  extra,
  children,
}: {
  label: string
  title: string
  extra?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section aria-label={label}>
      <Card
        size="small"
        title={
          <Space>
            <span>{title}</span>
            {extra}
          </Space>
        }
      >
        {children}
      </Card>
    </section>
  )
}

/**
 * 收尾检查（P2c-4 §2.5）：运行终态后展示「进度档 + 未决审批 + 结束原因 + 会话模式 + 产物数」，
 * 并给出**服务端的结构判定结论「达标 / 未达标」**（三条件全满足＝达标）。
 *
 * 纪律：判定由服务端给出（**不调模型、不改运行状态**），前端只渲染结论与分项、**不自行复算**；
 * 未达标时提供**一键重做** —— 仅当本页仍持有原结构化调用时可用；原件已不在（刷新 / 跨页）时
 * **如实告知**「请重新输入」，不假装能重放。
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
  const tone = verdict === 'met' ? 'success' : verdict === 'unmet' ? 'danger' : 'warning'
  const unmet = verdict === 'unmet'

  return (
    <PanelSection label="收尾检查" title="收尾检查" extra={<StatusTag tone={tone}>{badge}</StatusTag>}>
      <Descriptions
        column={1}
        size="small"
        items={[
          { key: 'steps', label: '进度档', children: `${metrics.completed_step_count}/${metrics.step_count} 步` },
          { key: 'pending', label: '未决审批', children: String(pending) },
          { key: 'finish', label: '结束原因', children: finishReasonLabel(metrics.finish_reason) },
          { key: 'mode', label: '会话模式', children: mode ? conversationModeLabel(mode) : '—' },
          { key: 'artifacts', label: '产物', children: `${artifactCount} 项` },
        ]}
      />

      {acceptance.loading && !acceptance.acceptance && <SkeletonList rows={1} state="loading" boxed={false} />}
      {acceptance.error && (
        <Alert
          type="error"
          showIcon
          message="结构判定读取失败"
          description={acceptance.error.message}
          action={
            acceptance.error.retryable ? (
              <Button size="small" onClick={acceptance.reload}>
                重新尝试
              </Button>
            ) : undefined
          }
        />
      )}
      {acceptance.acceptance && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {`结构判定（按运行记录逐项核对，不改动运行）：步骤完成${
            acceptance.acceptance.checks.steps_complete ? '✓' : '✗'
          } · 无未决审批${acceptance.acceptance.checks.no_pending_approvals ? '✓' : '✗'} · 正常终态${
            acceptance.acceptance.checks.finish_reason_ok ? '✓' : '✗'
          }`}
        </Typography.Paragraph>
      )}
      {!acceptance.acceptance && !acceptance.loading && !acceptance.error && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {`未取得结构判定：${
            stepsDone && pending === 0 && metrics.status !== 'failed'
              ? '本地展示口径看似完成，但判定以服务端为准（请重试读取）。'
              : '未达标迹象已出现，判定以服务端为准（请重试读取）。'
          }`}
        </Typography.Paragraph>
      )}

      {unmet && redoAvailable && onRedo && (
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Button onClick={onRedo}>一键重做</Button>
          <Typography.Text type="secondary">
            重做 = 重新发出本页仍保留的那次调用（算一次新的运行，不改动原运行）；判定与重做都不会自动重跑。
          </Typography.Text>
        </Space>
      )}
      {unmet && !redoAvailable && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          未达标：原始调用内容没有留存（安全口径，消息只保存脱敏摘要），已无法一键重做——请重新输入调用后再次发送。
        </Typography.Paragraph>
      )}
    </PanelSection>
  )
}

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
  artifacts: RunArtifactsState
  acceptance: RunAcceptanceState
  mode?: string
  redoAvailable?: boolean
  onRedo?: () => void
  canDecide: boolean
  /** 窄屏抽屉是否展开（宽屏由布局强制展示该面板）。 */
  expanded?: boolean
  onOpenRunDetail?: (runId: string) => void
  canIntervene?: boolean
  onNotice?: (message: string) => void
  /** 未传入（如运行详情页复用舞台）⇒ 不渲染该区块（零破坏）。 */
  collaboration?: CollaborationPanelState
}) {
  const { metrics, loading, error } = overview
  const pendingCount = approvals.items.filter((item) => item.status === 'pending').length

  return (
    <aside aria-label="右侧舞台" data-expanded={expanded ? 'true' : 'false'}>
      <PanelSection
        label="运行概览"
        title="运行概览"
        extra={metrics ? <Typography.Text type="secondary">{runStatusLabel(metrics.status)}</Typography.Text> : undefined}
      >
        {!runId && (
          <EmptyState
            boxed={false}
            description="暂无运行"
            action={<Typography.Text type="secondary">发起一次结构化工具调用后，这里会显示本次运行的概览、过程与审批。</Typography.Text>}
          />
        )}
        {runId && loading && !metrics && <SkeletonList rows={2} state="loading" boxed={false} />}
        {runId && !loading && error && (
          <Alert
            type="error"
            showIcon
            message="运行概览加载失败"
            description={error.message}
            action={
              error.retryable ? (
                <Button size="small" onClick={overview.reload}>
                  重新尝试
                </Button>
              ) : undefined
            }
          />
        )}
        {runId && metrics && (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Descriptions
              column={1}
              size="small"
              items={[
                {
                  key: 'status',
                  label: '运行状态',
                  children: <StatusTag tone={runStatusTone(metrics.status)}>{runStatusLabel(metrics.status)}</StatusTag>,
                },
                { key: 'steps', label: '步骤完成度', children: `${metrics.completed_step_count}/${metrics.step_count}` },
                { key: 'tools', label: '工具调用', children: String(metrics.tool_calls) },
                { key: 'latency', label: '耗时', children: `${metrics.latency_ms} ms` },
                { key: 'started', label: '开始时间', children: formatDateTime(metrics.started_at) },
                { key: 'finished', label: '结束时间', children: metrics.finished_at ? formatDateTime(metrics.finished_at) : '—' },
              ]}
            />
            {/* S4：干预动作贴着运行状态（终态自动不渲染；**可见性 ≠ 权限**，服务端仍是权威）。 */}
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
          </Space>
        )}
      </PanelSection>

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

      <PanelSection
        label="过程时间线"
        title="过程"
        extra={stream.lastSeq > 0 ? <Typography.Text type="secondary">{`最新序号 ${stream.lastSeq}`}</Typography.Text> : undefined}
      >
        <ProcessTimeline frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />
      </PanelSection>

      <TerminalOutputPanel frames={stream.frames} />
      <FileDiffPanel frames={stream.frames} />
      <ArtifactPanel runId={runId} artifacts={artifacts} onOpenRunDetail={onOpenRunDetail} />

      {collaboration && <ParticipantPanel collaboration={collaboration} />}

      <PanelSection
        label="审批"
        title="审批"
        extra={
          approvals.items.length > 0 ? (
            <Typography.Text type="secondary">{`${pendingCount} 项待批`}</Typography.Text>
          ) : undefined
        }
      >
        {!runId && (
          <EmptyState
            boxed={false}
            description="暂无审批"
            action={<Typography.Text type="secondary">本次会话还没有可关联的运行。</Typography.Text>}
          />
        )}
        {runId && approvals.loading && approvals.items.length === 0 && (
          <SkeletonList rows={2} state="loading" boxed={false} />
        )}
        {runId && approvals.error && (
          <Alert
            type="error"
            showIcon
            message="审批项加载失败"
            description={approvals.error.message}
            action={
              approvals.error.retryable ? (
                <Button size="small" onClick={approvals.reload}>
                  重新尝试
                </Button>
              ) : undefined
            }
          />
        )}
        {runId && !approvals.loading && !approvals.error && approvals.items.length === 0 && (
          <EmptyState
            boxed={false}
            description="没有审批项"
            action={<Typography.Text type="secondary">本次运行未请求人工审批。</Typography.Text>}
          />
        )}
        {runId &&
          approvals.items.map((approval) => (
            <ApprovalCard
              key={approval.approval_id}
              approval={approval}
              canDecide={canDecide}
              deciding={approvals.decidingId === approval.approval_id}
              onDecide={(approved) => void approvals.decide(approval.approval_id, approved)}
            />
          ))}
        {runId && onOpenRunDetail && (
          <Button type="link" size="small" onClick={() => onOpenRunDetail(runId)}>
            在运行详情中打开
          </Button>
        )}
      </PanelSection>
    </aside>
  )
}
