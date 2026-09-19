import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { EmptyState } from '../../components/ui/EmptyState'
import { formatLocalTime } from '../../utils/time'
import { getExportPackage, getLifecycleJob, getUsageSummary, listExportPackages, requestExport } from './api'
import { asBillingError, asExportError, formatCents, initialBillingState, initialExportState, isPackageExpired } from './state'
import type { BillingState, ExportSectionState } from './types'

// 导出包由后台周期任务生成（beat 间隔默认 30 秒）：申请后按作业状态确认，
// 首次即时查一次，未完成则每 3 秒复查，最多 40 次（约 2 分钟）后如实告知「仍在生成」。
const EXPORT_POLL_INTERVAL_MS = 3000
const EXPORT_POLL_MAX_ATTEMPTS = 40

export function UsageBillingPage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<BillingState>(initialBillingState)
  const [exportState, setExportState] = useState<ExportSectionState>(initialExportState)

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const usage = await getUsageSummary()
      setState({ usage, loading: false, error: null })
    } catch (error) {
      setState({ usage: null, loading: false, error: asBillingError(error) })
    }
  }, [])

  const loadExports = useCallback(async () => {
    setExportState((old) => ({ ...old, loading: true, error: null }))
    try {
      const page = await listExportPackages()
      setExportState((old) => ({ ...old, packages: page.items, total: page.total, loading: false, error: null }))
    } catch (error) {
      setExportState((old) => ({ ...old, packages: [], total: 0, loading: false, error: asExportError(error) }))
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => { void loadExports() }, [loadExports])

  const submitExport = useCallback(async () => {
    setExportState((old) => ({ ...old, phase: 'requesting', requestError: null, notice: null }))
    try {
      const job = await requestExport()
      setExportState((old) => ({ ...old, phase: 'waiting', jobId: job.job_id, requestError: null }))
    } catch (error) {
      setExportState((old) => ({ ...old, phase: 'failed', jobId: null, requestError: asExportError(error) }))
    }
  }, [])

  // 等生成：只认服务端的作业状态，不做本地乐观插入（列表一律重新取数）。
  useEffect(() => {
    if (exportState.phase !== 'waiting' || !exportState.jobId) return
    const jobId = exportState.jobId
    let active = true
    let timer: number | undefined
    const tick = async (attempt: number) => {
      try {
        const job = await getLifecycleJob(jobId)
        if (!active) return
        if (job.status === 'completed') {
          setExportState((old) => ({ ...old, phase: 'done', jobId: null, notice: '导出包已生成，可在下方下载' }))
          await loadExports()
          return
        }
      } catch {
        // 单次查询失败不打断等待：下一拍继续；超过上限按「仍在生成」如实告知。
      }
      if (!active) return
      if (attempt + 1 >= EXPORT_POLL_MAX_ATTEMPTS) {
        setExportState((old) => ({ ...old, phase: 'timeout', jobId: null }))
        return
      }
      timer = window.setTimeout(() => { void tick(attempt + 1) }, EXPORT_POLL_INTERVAL_MS)
    }
    void tick(0)
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer) }
  }, [exportState.phase, exportState.jobId, loadExports])

  const download = useCallback(async (packageId: string) => {
    setExportState((old) => ({ ...old, downloadingId: packageId, downloadError: null, notice: null }))
    try {
      const detail = await getExportPackage(packageId)
      // 载荷只进文件：页面上不渲染内容（避免把整包数据摊进界面）。
      const blob = new Blob([JSON.stringify(detail.payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `租户数据导出-${packageId}.json`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      setExportState((old) => ({ ...old, downloadingId: null, notice: '导出包已开始下载，文件保存在本机下载目录' }))
    } catch (error) {
      setExportState((old) => ({ ...old, downloadingId: null, downloadError: asExportError(error) }))
    }
  }, [])

  const usage = state.usage
  const isEmpty = usage !== null && usage.units === 0 && usage.cost_cents === 0
  const notRegistered = state.error?.status === 404
  // 数字只在拿到服务端汇总后展示；加载中与出错时一律显示占位符，不留误导性的 0。
  const showTotals = !state.loading && usage !== null

  const requesting = exportState.phase === 'requesting' || exportState.phase === 'waiting'
  const exportListReady = !exportState.loading && !exportState.error
  const exportButtonLabel = exportState.phase === 'requesting'
    ? '正在申请…'
    : exportState.phase === 'waiting'
      ? '等待生成…'
      : exportState.phase === 'timeout'
        ? '刷新导出包'
        : '申请导出'

  const exportAction = () => {
    if (exportState.phase === 'timeout') { void loadExports(); return }
    void submitExport()
  }

  return <>
    <main className="main-content content-history usage-billing t3">
      <div className="t3__intro">
        <p className="page-desc">本租户的累计用量与累计费用，数据来自追加式用量账本（含冲正记录）。本页只读，不提供冲正、额度调整或计费口径变更入口。</p>
        <div className="t3__actions">
          <button className="btn btn--secondary" type="button" disabled={state.loading} onClick={() => void load()}>{state.loading ? '正在刷新' : '刷新'}</button>
        </div>
      </div>

      <div className="metrics">
        <div className="metric">
          <div className="metric__label">累计用量</div>
          <div className="metric__value">{showTotals ? usage.units : '—'}</div>
          <div className="metric__hint">服务端用量账本记录的累计原值</div>
        </div>
        <div className="metric">
          <div className="metric__label">累计费用</div>
          <div className="metric__value">{showTotals ? formatCents(usage.cost_cents) : '—'}</div>
          <div className="metric__hint">整数分记账，发生过冲正时累计可能为负</div>
        </div>
      </div>

      <section className="card" aria-label="用量与费用">
        <div className="card__head"><h2>用量账本</h2>{usage && <span className="page-code">{usage.tenant_id}</span>}</div>

        {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载用量与费用…</div>}

        {!state.loading && notRegistered && <div className="card__body">
          <div className="notice" role="status">
            <div>
              <strong>本租户尚未登记用量账本</strong>
              <p>商业化模块里还没有本租户的登记记录，因此没有可展示的用量与费用。这通常说明当前环境尚未初始化商业化数据，<b>不是故障</b>；已登记租户即使没有任何计量事件也会返回 0。</p>
            </div>
          </div>
        </div>}

        {!state.loading && state.error && !notRegistered && <div className="card__body">
          <div className="notice notice-error" role="alert">
            <div>
              <strong>{state.error.status === 403 ? '暂时无法查看用量与费用' : '用量与费用加载失败'}</strong>
              <p>{state.error.message}</p>
            </div>
            {state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
          </div>
        </div>}

        {!state.loading && !state.error && usage && !isEmpty && <div className="rows" role="list">
          <div className="row" role="listitem">
            <div className="row__main">
              <strong className="row__title">用量口径</strong>
              <span className="row__sub">账本记录的原始单位，页面不做业务含义解释。</span>
            </div>
          </div>
          <div className="row" role="listitem">
            <div className="row__main">
              <strong className="row__title">费用口径</strong>
              <span className="row__sub">账本以整数分记账；发生过冲正时累计可能为负。</span>
            </div>
          </div>
        </div>}

        {!state.loading && !state.error && usage && isEmpty && (
          <EmptyState illustration="list" title="暂无用量记录" text="有计量事件写入账本后，这里会显示累计用量与费用。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
          </EmptyState>
        )}
      </section>

      <section className="card" aria-label="数据导出">
        <div className="card__head"><h2>数据导出</h2>{exportListReady && exportState.total > 0 && <span className="page-code">共 {exportState.total} 个导出包</span>}</div>

        <div className="card__body">
          <p className="page-desc">导出本租户在平台里的配置与业务记录，内容经过脱敏（不含密码、登录凭据与客户原文）。申请后由后台生成导出包，<b>生成完成后才能在下方下载</b>；导出包自生成起 7 天内有效，过期后不可下载。包内会如实标注三类情况：尚未交付的数据类别、本次没读到（与「确实没有」区分开）、以及超过单类条数上限时「取了多少 / 共多少」。</p>
          <div className="t3__actions">
            <button
              className="btn btn--secondary"
              type="button"
              disabled={requesting}
              onClick={exportAction}
            >{exportButtonLabel}</button>
          </div>

          {exportState.phase === 'requesting' && <div className="loading-state" role="status"><span className="loading-dot" />正在提交导出申请…</div>}
          {exportState.phase === 'waiting' && <div className="loading-state" role="status"><span className="loading-dot" />导出包正在后台生成（周期任务处理，通常很快）…</div>}
          {exportState.phase === 'timeout' && <div className="notice" role="status">
            <div>
              <strong>导出仍在后台生成</strong>
              <p>等待已超过约 2 分钟。这通常说明后台周期任务尚未跑完，<b>不是失败</b>；可点「刷新导出包」查看最新结果。</p>
            </div>
          </div>}
          {exportState.phase === 'failed' && exportState.requestError && <div className="notice notice-error" role="alert">
            <div>
              <strong>导出申请没有提交成功</strong>
              <p>{exportState.requestError.message}</p>
            </div>
            {exportState.requestError.retryable && <button className="text-action" type="button" onClick={() => void submitExport()}>重新尝试</button>}
          </div>}
          {exportState.notice && exportState.phase !== 'failed' && <div className="notice" role="status"><div><strong>{exportState.notice}</strong></div></div>}
          {exportState.downloadError && <div className="notice notice-error" role="alert">
            <div>
              <strong>下载没有完成</strong>
              <p>{exportState.downloadError.message}</p>
            </div>
          </div>}
        </div>

        {exportState.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载导出包…</div>}

        {!exportState.loading && exportState.error && <div className="card__body">
          <div className="notice notice-error" role="alert">
            <div>
              <strong>导出包列表加载失败</strong>
              <p>{exportState.error.message}</p>
            </div>
            {exportState.error.retryable && <button className="text-action" type="button" onClick={() => void loadExports()}>重新尝试</button>}
          </div>
        </div>}

        {exportListReady && exportState.packages.length === 0 && (
          <EmptyState illustration="list" title="暂无导出包" text="申请导出后，由后台生成；生成完成即可在这里下载（7 天内有效）。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void loadExports()}>刷新导出包</button>
          </EmptyState>
        )}

        {exportListReady && exportState.packages.length > 0 && <div className="rows" role="list">
          {exportState.packages.map((item) => {
            const expired = isPackageExpired(item.expires_at)
            const downloading = exportState.downloadingId === item.package_id
            return <div className="row" role="listitem" key={item.package_id}>
              <div className="row__main">
                <strong className="row__title">{`生成于 ${formatLocalTime(item.created_at)}`}</strong>
                <span className="row__sub">{`有效期至 ${formatLocalTime(item.expires_at)}`}</span>
              </div>
              {expired
                ? <span className="badge badge--warn">已过期</span>
                : <button className="btn btn--secondary btn--sm" type="button" disabled={downloading} onClick={() => void download(item.package_id)}>{downloading ? '正在下载…' : '下载'}</button>}
            </div>
          })}
        </div>}
      </section>

      <p className="page-desc">尚未交付的部分如实说明：模型清单（当前模型由部署配置决定，没有可下钻的模型维度）、按时间 / 模型 / 任务的花费明细、预算与告警、冲正入口、租户删除申请与保留策略设置，都属于下一期范围；导出包中尚未接线的数据类别会随包标注，不做假装有数据的填充。</p>
    </main>
  </>
}