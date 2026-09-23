/**
 * 用量与费用 —— 由 `admin-web/src/features/billing/UsageBillingPage.tsx` 合并移植。
 *
 * **移植口径（如实登记）**：
 *  - 业务能力**等价保留**：累计用量 / 累计费用 两项汇总、数据导出闭环
 *    （申请 → 轮询作业状态 → 列出导出包 → 下载）、以及两块各自的四态；
 *  - 呈现层换成 **AntD + 项目组件库**；传输层换成全前端唯一请求层；
 *  - 金额格式化**保留原实现**（整数分运算、负值正确加符号）—— 见 `state.ts` 的说明，
 *    基座 `formatBudgetCents` 对负值不适用；
 *  - **403 / 404 与"加载失败"分开呈现**：404 = 本租户未登记（常见态，不是故障）。
 *
 * 纪律：
 *  - 数字只在**取数成功后**展示；加载中与失败时显示占位，**不留误导性的 0**；
 *  - 等生成**只认服务端作业状态**，不做本地乐观插入（列表一律重新取数）；
 *  - 载荷**只进文件**，不渲染到页面上（避免把整包数据摊进界面）；
 *  - 超时按「仍在生成」如实告知，**不得**说成失败。
 */
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Space, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { ContentState, DataTable, PageContainer, StatCard } from '../../components'
import { formatDateTime } from '../../utils/format'
import {
  BillingError,
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  EXPORT_HINT,
  EXPORT_PACKAGE_LIMIT,
  NOT_REGISTERED_NOTE,
  SAMPLE_DATA_BADGE,
  SAMPLE_DESCRIPTION,
  fetchExportPackage,
  fetchExportPackages,
  fetchLifecycleJob,
  fetchUsage,
  isConnected,
  requestExport,
} from './services/billingService'
import { formatCents, isPackageExpired } from './state'
import type { ExportPackageSummary, ExportRequestPhase, LifecycleJob, UsageSummary } from './types'

/** 导出包由后台周期任务生成：申请后即时查一次，未完成则每 3 秒复查，最多 40 次（约 2 分钟）。 */
const EXPORT_POLL_INTERVAL_MS = 3000
const EXPORT_POLL_MAX_ATTEMPTS = 40

interface UsageState {
  usage: UsageSummary | null
  loading: boolean
  error: BillingError | null
}

interface ExportState {
  packages: ExportPackageSummary[]
  total: number
  loading: boolean
  error: BillingError | null
  phase: ExportRequestPhase
  jobId: string | null
  requestError: BillingError | null
  downloadingId: string | null
  downloadError: BillingError | null
  /** 阶段性如实说明（生成完成 / 下载已触发），非报错。 */
  notice: string | null
}

const INITIAL_USAGE: UsageState = { usage: null, loading: true, error: null }
const INITIAL_EXPORT: ExportState = {
  packages: [],
  total: 0,
  loading: true,
  error: null,
  phase: 'idle',
  jobId: null,
  requestError: null,
  downloadingId: null,
  downloadError: null,
  notice: null,
}

/** 把任意异常规整成 `BillingError`（非本层错误按通用失败处理，不吞异常语义）。 */
function asError(error: unknown, scope: 'usage' | 'export'): BillingError {
  if (error instanceof BillingError) return error
  const message = error instanceof Error ? error.message : '请求失败，请稍后重试。'
  return new BillingError(message, 'failed', 0, scope)
}

export function UsageBillingPage() {
  const connected = isConnected()
  const [usageState, setUsageState] = useState<UsageState>(INITIAL_USAGE)
  const [exportState, setExportState] = useState<ExportState>(INITIAL_EXPORT)

  const loadUsage = useCallback(async () => {
    setUsageState((old) => ({ ...old, loading: true, error: null }))
    try {
      const usage = await fetchUsage()
      setUsageState({ usage, loading: false, error: null })
    } catch (error) {
      setUsageState({ usage: null, loading: false, error: asError(error, 'usage') })
    }
  }, [])

  const loadExports = useCallback(async () => {
    setExportState((old) => ({ ...old, loading: true, error: null }))
    try {
      const page = await fetchExportPackages(EXPORT_PACKAGE_LIMIT, 0)
      setExportState((old) => ({ ...old, packages: page.items, total: page.total, loading: false, error: null }))
    } catch (error) {
      setExportState((old) => ({ ...old, packages: [], total: 0, loading: false, error: asError(error, 'export') }))
    }
  }, [])

  useEffect(() => { void loadUsage() }, [loadUsage])
  useEffect(() => { void loadExports() }, [loadExports])

  const submitExport = useCallback(async () => {
    setExportState((old) => ({ ...old, phase: 'requesting', requestError: null, notice: null }))
    try {
      const job: LifecycleJob = await requestExport()
      setExportState((old) => ({ ...old, phase: 'waiting', jobId: job.job_id, requestError: null }))
    } catch (error) {
      setExportState((old) => ({ ...old, phase: 'failed', jobId: null, requestError: asError(error, 'export') }))
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
        const job = await fetchLifecycleJob(jobId)
        if (!active) return
        if (job.status === 'completed') {
          setExportState((old) => ({ ...old, phase: 'done', jobId: null, notice: '导出包已生成，可在下方下载' }))
          await loadExports()
          return
        }
      } catch {
        // 单次查询失败**不打断等待**：下一拍继续；超过上限按「仍在生成」如实告知（不谎报失败）
      }
      if (!active) return
      if (attempt + 1 >= EXPORT_POLL_MAX_ATTEMPTS) {
        setExportState((old) => ({ ...old, phase: 'timeout', jobId: null }))
        return
      }
      timer = window.setTimeout(() => { void tick(attempt + 1) }, EXPORT_POLL_INTERVAL_MS)
    }
    void tick(0)
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [exportState.phase, exportState.jobId, loadExports])

  const download = useCallback(async (packageId: string) => {
    setExportState((old) => ({ ...old, downloadingId: packageId, downloadError: null, notice: null }))
    try {
      const detail = await fetchExportPackage(packageId)
      // 载荷**只进文件**：页面上不渲染内容（避免把整包数据摊进界面）
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
      setExportState((old) => ({ ...old, downloadingId: null, downloadError: asError(error, 'export') }))
    }
  }, [])

  const usage = usageState.usage
  const notRegistered = usageState.error?.status === 404
  const usageForbidden = usageState.error?.status === 403
  const isEmpty = usage !== null && usage.units === 0 && usage.cost_cents === 0

  // 404 / 403 一律按「未配置 / 无权限」呈现，**不显示成 0**（状态保真）
  const statPresence = notRegistered ? 'not_configured' : 'ready'
  const statState = usageState.loading
    ? 'loading'
    : usageState.error && !notRegistered
      ? usageForbidden
        ? 'forbidden'
        : 'error'
      : 'ready'

  const requesting = exportState.phase === 'requesting' || exportState.phase === 'waiting'
  const exportListReady = !exportState.loading && !exportState.error
  const exportButtonLabel =
    exportState.phase === 'requesting'
      ? '正在申请…'
      : exportState.phase === 'waiting'
        ? '等待生成…'
        : exportState.phase === 'timeout'
          ? '刷新导出包'
          : '申请导出'

  const exportAction = () => {
    if (exportState.phase === 'timeout') {
      void loadExports()
      return
    }
    void submitExport()
  }

  const exportColumns: TableColumnsType<ExportPackageSummary> = [
    {
      title: '导出包',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (_value, item) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{`生成于 ${formatDateTime(item.created_at)}`}</Typography.Text>
          <Typography.Text type="secondary">{`有效期至 ${formatDateTime(item.expires_at)}`}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'expired',
      width: 100,
      render: (_value, item) =>
        isPackageExpired(item.expires_at) ? <Typography.Text type="warning">已过期</Typography.Text> : <Typography.Text>可下载</Typography.Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_value, item) =>
        isPackageExpired(item.expires_at) ? null : (
          <Button
            size="small"
            loading={exportState.downloadingId === item.package_id}
            onClick={() => void download(item.package_id)}
          >
            下载
          </Button>
        ),
    },
  ]

  return (
    <PageContainer
      title="用量与费用"
      description="本租户的累计用量与累计费用，数据来自追加式用量账本（含冲正记录）。本页只读，不提供冲正、额度调整或计费口径变更入口。"
      extra={
        <Button onClick={() => void loadUsage()} disabled={usageState.loading}>
          {usageState.loading ? '正在刷新' : '刷新'}
        </Button>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {connected ? (
          <Alert type="success" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
        ) : (
          SAMPLE_DATA_BADGE !== '' && (
            <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
          )
        )}

        <Space size="middle" wrap>
          <StatCard
            label="累计用量"
            value={usage?.units}
            presence={statPresence}
            state={statState}
            onRetry={() => void loadUsage()}
          />
          <StatCard
            label="累计费用"
            value={usage ? formatCents(usage.cost_cents) : undefined}
            presence={statPresence}
            state={statState}
            onRetry={() => void loadUsage()}
          />
        </Space>
        <Typography.Text type="secondary">
          累计用量为服务端账本记录的原始单位；累计费用以整数分记账，发生过冲正时可能为负。
        </Typography.Text>

        {/* 未登记（404）不是故障，与"加载失败"分开呈现 —— 且不给"重试"（重试也不会变） */}
        {!usageState.loading && notRegistered && (
          <Alert type="info" showIcon message={'本租户尚未登记用量账本'} description={NOT_REGISTERED_NOTE} />
        )}
        {!usageState.loading && usageState.error && !notRegistered && (
          <ContentState
            state={usageForbidden ? 'forbidden' : 'error'}
            description={usageState.error.message}
            onRetry={usageForbidden ? undefined : () => void loadUsage()}
            boxed={false}
          />
        )}
        {!usageState.loading && !usageState.error && usage && isEmpty && (
          <ContentState
            state="empty"
            description="暂无用量记录：有计量事件写入账本后，这里会显示累计用量与费用。"
            boxed={false}
          />
        )}

        <Typography.Title level={3}>数据导出</Typography.Title>
        <Typography.Text type="secondary">{EXPORT_HINT}</Typography.Text>
        {/* 尚未交付的部分**如实说明**，不留"看起来有但其实没有"的空位 */}
        <Typography.Text type="secondary">
          尚未交付：模型清单（模型由部署配置决定，没有可下钻的模型维度）、按时间 / 模型 / 任务的花费明细、预算与告警、冲正入口、租户删除申请与保留策略设置，均属下一期范围。
        </Typography.Text>

        <Space>
          <Button type="primary" disabled={requesting} onClick={exportAction}>
            {exportButtonLabel}
          </Button>
          {exportListReady && exportState.total > 0 && (
            <Typography.Text type="secondary">{`共 ${exportState.total} 个导出包`}</Typography.Text>
          )}
        </Space>

        {exportState.phase === 'waiting' && (
          <Alert type="info" showIcon message="导出包正在后台生成（周期任务处理，通常很快）…" />
        )}
        {exportState.phase === 'timeout' && (
          <Alert
            type="warning"
            showIcon
            message="导出仍在后台生成"
            description="等待已超过约 2 分钟。这通常说明后台周期任务尚未跑完，不是失败；可点「刷新导出包」查看最新结果。"
          />
        )}
        {exportState.phase === 'failed' && exportState.requestError && (
          <Alert
            type="error"
            showIcon
            message="导出申请没有提交成功"
            description={exportState.requestError.message}
            action={
              exportState.requestError.failure !== 'forbidden' ? (
                <Button size="small" onClick={() => void submitExport()}>重新尝试</Button>
              ) : undefined
            }
          />
        )}
        {exportState.notice && exportState.phase !== 'failed' && (
          <Alert type="success" showIcon message={exportState.notice} closable onClose={() => setExportState((old) => ({ ...old, notice: null }))} />
        )}
        {exportState.downloadError && (
          <Alert type="error" showIcon message="下载没有完成" description={exportState.downloadError.message} />
        )}

        <DataTable<ExportPackageSummary>
          columns={exportColumns}
          rows={exportState.packages}
          rowKey={(row) => row.package_id}
          state={
            exportState.loading
              ? 'loading'
              : exportState.error
                ? exportState.error.failure === 'forbidden'
                  ? 'forbidden'
                  : 'error'
                : exportState.packages.length === 0
                  ? 'empty'
                  : 'ready'
          }
          stateDescription={
            exportState.error
              ? exportState.error.message
              : '暂无导出包：申请导出后由后台生成，生成完成即可在这里下载（7 天内有效）。'
          }
          onRetry={exportState.error?.failure === 'forbidden' ? undefined : () => void loadExports()}
        />
      </Space>
    </PageContainer>
  )
}
