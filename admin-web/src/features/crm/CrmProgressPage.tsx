import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
import { getProgressSummary } from './api'
import { CrmNotice } from './CrmShared'
import { asCrmError, formatCount, formatCents, formatDays, formatRatio } from './state'
import { HEALTH_BAND_LABELS, crmLabel, type CrmErrorShape, type CrmProgressSummary, type CrmScope } from './types'

export function CrmProgressPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  const [scope, setScope] = useState<CrmScope>('me')
  const [metrics, setMetrics] = useState<CrmProgressSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<CrmErrorShape | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setMetrics(await getProgressSummary(scope))
    } catch (err) {
      setMetrics(null)
      setError(asCrmError(err))
    } finally {
      setLoading(false)
    }
  }, [scope])

  useEffect(() => { void load() }, [load])

  const distribution = metrics?.health_distribution ?? {}
  const targetNoTarget = metrics?.target_note === 'no_target'
  const forbidden = error?.status === 403

  return <main className="main-content t3 crm">
    <div className="t3__intro">
      <p className="page-desc">多维度进度指标：分母为零的指标返回空值（显示「无目标」/「—」），不编造 0；阈值类参考口径取自行业惯例，非本项目数据校准结果。</p>
      <div className="t3__actions">
        <button className="btn btn--secondary" type="button" disabled={loading} onClick={() => void load()}>刷新</button>
      </div>
    </div>

    <div className="toolbar">
      <div className="segment" role="tablist" aria-label="统计范围">
        <button type="button" role="tab" aria-selected={scope === 'me'} className={scope === 'me' ? 'active' : ''} onClick={() => setScope('me')}>我的</button>
        <button type="button" role="tab" aria-selected={scope === 'all'} className={scope === 'all' ? 'active' : ''} onClick={() => setScope('all')}>全量</button>
      </div>
      <span className="role-note">全量口径需要部门负责人 / CEO / 超级管理员岗位，权限由服务端判定。</span>
    </div>

    {loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载进度指标…</div>}

    {!loading && error && <CrmNotice
      tone="error"
      title={scope === 'all' && forbidden ? '当前账号无权查看全量指标' : '进度指标加载失败'}
      action={!forbidden && error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{error.message}</p>
      {scope === 'all' && forbidden && <p>全量口径仅对部门负责人 / CEO / 超级管理员开放；可切换回「我的」。</p>}
    </CrmNotice>}

    {!loading && !error && !metrics && <EmptyState illustration="list" title="暂无进度数据" text="当前范围还没有可统计的客户、商机或合同。">
      <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
    </EmptyState>}

    {!loading && !error && metrics && <>
      <section className="card" aria-label="管线与赢率">
        <div className="card__head"><h2>管线与赢率</h2><span className="badge">{scope === 'all' ? '全量' : '我的'}</span></div>
        <div className="card__body"><div className="metrics">
          <MetricTile label="管线覆盖率" value={metrics.pipeline_coverage === null ? (metrics.pipeline_coverage_note === 'no_target' ? '无目标' : '—') : formatRatio(metrics.pipeline_coverage, 'multiple')} hint={metrics.pipeline_coverage_note === 'no_target' ? '当月目标额为零或未设目标（标注 no_target），不编造分母。' : '进行中商机总额 ÷ 当月目标额；3–5× 仅为行业参考区间。'} />
          <MetricTile label="赢率" value={formatRatio(metrics.win_rate, 'percent')} hint="won ÷（won + lost）；没有已关闭商机时为空值。" />
          <MetricTile label="销售周期" value={formatDays(metrics.sales_cycle_days)} hint="仅统计赢单：closed_at − created_at 的均值。" />
          <MetricTile label="管线账龄" value={formatDays(metrics.pipeline_age_days)} hint="进行中商机 now() − stage_entered_at 的均值。" />
          <MetricTile label="创建速率（近 30 天）" value={formatCount(metrics.creation_rate_30d)} hint="近 30 天新建商机数；0 是真实值。" />
        </div></div>
      </section>

      <section className="card" aria-label="健康分档分布">
        <div className="card__head"><h2>健康分档分布</h2><span className="badge">客户计数</span></div>
        <div className="card__body"><div className="metrics">
          <MetricTile label={crmLabel(HEALTH_BAND_LABELS, 'green')} value={formatCount(distribution.green ?? 0)} hint="健康分 ≥ 80。" />
          <MetricTile label={crmLabel(HEALTH_BAND_LABELS, 'yellow')} value={formatCount(distribution.yellow ?? 0)} hint="健康分 60–79。" />
          <MetricTile label={crmLabel(HEALTH_BAND_LABELS, 'red')} value={formatCount(distribution.red ?? 0)} hint="健康分 < 60。" />
          <MetricTile label="未计算" value={formatCount(distribution.uncomputed ?? 0)} hint="尚未跑过重算任务（不等于 0 分）。" />
        </div></div>
      </section>

      <section className="card" aria-label="续约与回款">
        <div className="card__head"><h2>续约窗口与回款</h2><span className="badge">仅已签署合同</span></div>
        <div className="card__body"><div className="metrics">
          <MetricTile label="续约窗口（未来 90 天）" value={`${formatCount(metrics.renewal_window_count)} 份`} hint={`窗口内合同金额 ${formatCents(metrics.renewal_window_amount_cents)}；到期未续由周期任务置为 expired。`} />
          <MetricTile label="回款进度" value={formatRatio(metrics.payment_progress, 'percent')} hint="Σpaid_cents ÷ Σamount_cents（人工登记口径）；无已签署合同时为空值。" />
          <MetricTile label="已到期未结清" value={`${formatCount(metrics.overdue_contract_count)} 份`} hint="已签署且已过到期日且回款未满。" />
        </div></div>
      </section>

      <section className="card" aria-label="目标达成度">
        <div className="card__head"><h2>目标达成度（当月）</h2><span className="badge">{targetNoTarget ? '无目标' : '有目标'}</span></div>
        <div className="card__body"><div className="metrics">
          <MetricTile label="金额达成度" value={metrics.target_attainment_amount === null ? (targetNoTarget ? '无目标' : '—') : formatRatio(metrics.target_attainment_amount, 'percent')} hint="当月 won 金额 ÷ 当月目标额。" />
          <MetricTile label="单数达成度" value={metrics.target_attainment_count === null ? (targetNoTarget ? '无目标' : '—') : formatRatio(metrics.target_attainment_count, 'percent')} hint="当月 won 单数 ÷ 目标单数。" />
        </div>
        {targetNoTarget && <p className="role-note">当月没有目标记录（或目标值均为 0）：达成度显示「无目标」，不用 0 代替。</p>}
        </div>
      </section>
    </>}
  </main>
}

function MetricTile({ label, value, hint }: { label: string; value: ReactNode; hint: string }) {
  return <div className="metric">
    <div className="metric__label">{label}</div>
    <div className="metric__value">{value}</div>
    <div className="metric__hint">{hint}</div>
  </div>
}