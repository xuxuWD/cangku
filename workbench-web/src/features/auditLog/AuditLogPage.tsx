/**
 * 审计日志（第 10 轮建立 · **按矩阵 §3「审计：查询」分档**）。
 *
 * 一页两块：① 筛选 + 记录列表（分页）② 详情抽屉（只读）。
 * 四态：加载 / 空 / 错误（可重试）/ 无权限。
 *
 * **视图按能力分流**（口径 = `permission-matrix.md` §3）：
 *  - `audit.scope.tenant`（`department_lead` / `ceo` / `super_admin`）⇒ **本租户视图**：
 *    可筛选任意操作人；空态区分"没有记录"与"筛选未命中"；
 *  - `audit.view`（`employee`）⇒ **我的操作视图**：**不渲染"操作人"筛选项**（服务端强制自限），
 *    并给出"只显示你自己的记录（服务端强制）"的如实说明；
 *  - 都没有（`customer_admin`）⇒ 整页无权限态 + 原因，且**不请求任何数据**。
 *
 * 纪律：
 *  - 本页**只做呈现**：真正的范围判定在服务端（`employee` 的 `actor_id` 由服务端注入，传他人 ⇒ 403）；
 *  - 时间参数一律 `toISOString()`（`Z` 形态）—— 实测 naive ⇒ 422、URL 里字面 `+00:00` ⇒ 422；
 *  - 写侧无任何入口（审计是**追加型不可变日志**），导出**后端零实现** ⇒ 只给说明、不放按钮；
 *  - 空 / 错误 / 无权限三态分别呈现，**不得**把失败说成"没有记录"。
 */
import { useState } from 'react'
import { Alert, Button, DatePicker, Form, Input, Select, Space, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { hasCapability, useSession } from '../../app/session'
import { ContentState, DataTable, PageContainer } from '../../components'
import type { ContentStateKind } from '../../components'
import { tokens } from '../../theme/tokens'
import { formatDateTime } from '../../utils/format'
import { usePanelData } from '../../utils/panelData'
import { AuditDetailDrawer, NOT_SET_TEXT } from './components/AuditDetailDrawer'
import {
  AUDIT_EXPORT_NOT_CONNECTED_NOTE,
  AUDITS_EMPTY_NOTE,
  AUDITS_LIMIT,
  AUDITS_NO_MATCH_NOTE,
  AUDIT_PERMISSION_REASON,
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  MY_AUDITS_EMPTY_NOTE,
  MY_AUDITS_NO_MATCH_NOTE,
  SAMPLE_DATA_BADGE,
  SAMPLE_DESCRIPTION,
  SELF_SCOPE_NOTE,
  fetchAuditActions,
  fetchAudits,
  isConnected,
} from './services/auditService'
import { isBlankQuery } from './types'
import type { AuditActionCatalog, AuditPage, AuditQuery, AuditRecord } from './types'

/** 空条件（首次进入页面即用它取数）。 */
export const BLANK_QUERY: AuditQuery = { actions: [] }

const EMPTY_PAGE: AuditPage = { sample: true, items: [], total: 0, limit: 0, offset: 0 }
const EMPTY_CATALOG: AuditActionCatalog = { sample: true, items: [], total: 0 }

/** 默认每页条数（后端 `limit` 上限 200）。 */
export const DEFAULT_PAGE_SIZE = 50

/** 只用到 `toISOString()`：不 import `dayjs` 类型（它只是 antd 的传递依赖，未在 package.json 声明）。 */
interface IsoLike {
  toISOString(): string
}

interface FilterValues {
  actions?: string[]
  target_type?: string
  target_id?: string
  actor_id?: string
  range?: [IsoLike | null, IsoLike | null] | null
}

function toIso(value: IsoLike | null | undefined): string | undefined {
  return value ? value.toISOString() : undefined
}

/** 各块的非就绪文案（唯一来源在此，组件不另写一套）。 */
const LIST_STATE_TEXT: Record<Exclude<ContentStateKind, 'loading'>, string> = {
  empty: AUDITS_EMPTY_NOTE,
  error: '审计记录加载失败，请稍后重试。',
  forbidden: '无权限查看审计记录。',
}

/** 「审计日志」页（按能力分档渲染）。 */
export function AuditLogPage() {
  const role = useSession((state) => state.role)
  const canView = hasCapability(role, 'audit.view')
  const tenantWide = hasCapability(role, 'audit.scope.tenant')

  if (!canView) {
    return (
      <PageContainer
        title="审计日志"
        description="查看本租户的操作记录（员工仅本人相关）。"
      >
        {/* 无任何审计能力（如 customer_admin）：整页无权限态 + 原因，不请求数据、不渲染筛选控件 */}
        <ContentState state="forbidden" description={AUDIT_PERMISSION_REASON} />
      </PageContainer>
    )
  }

  return <AuditBoard tenantWide={tenantWide} showExportNote={role === 'super_admin'} />
}

interface AuditBoardProps {
  /** 是否"本租户全量"档（`employee` 为 `false` ⇒ 不渲染操作人筛选）。 */
  tenantWide: boolean
  /** 是否提示"审计导出尚未接入"（矩阵把导出给 `super_admin`，其余角色不提）。 */
  showExportNote: boolean
}

function AuditBoard({ tenantWide, showExportNote }: AuditBoardProps) {
  const connected = isConnected()
  const [form] = Form.useForm<FilterValues>()
  const [applied, setApplied] = useState<AuditQuery>(BLANK_QUERY)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [detail, setDetail] = useState<AuditRecord | null>(null)

  const offset = (page - 1) * pageSize
  const audits = usePanelData(
    () => fetchAudits(applied, { limit: pageSize, offset }),
    EMPTY_PAGE,
    [JSON.stringify(applied), page, pageSize],
  )
  const catalog = usePanelData(() => fetchAuditActions(), EMPTY_CATALOG)

  const blank = isBlankQuery(applied)
  const state: ContentStateKind | 'ready' =
    audits.state === 'ready' && audits.data.items.length === 0 ? 'empty' : audits.state
  const stateDescription =
    state === 'empty'
      ? tenantWide
        ? blank
          ? AUDITS_EMPTY_NOTE
          : AUDITS_NO_MATCH_NOTE
        : blank
          ? MY_AUDITS_EMPTY_NOTE
          : MY_AUDITS_NO_MATCH_NOTE
      : state === 'loading' || state === 'ready'
        ? undefined
        : LIST_STATE_TEXT[state]

  const handleSearch = (values: FilterValues) => {
    const [from, to] = values.range ?? [null, null]
    setApplied({
      actions: values.actions ?? [],
      target_type: values.target_type?.trim() || undefined,
      target_id: values.target_id?.trim() || undefined,
      // 操作人筛选仅"本租户全量"档渲染；`employee` 即便手改请求也由服务端强制为本人（传他人 ⇒ 403）
      actor_id: tenantWide ? values.actor_id?.trim() || undefined : undefined,
      since: toIso(from),
      until: toIso(to),
    })
    setPage(1)
  }

  const handleReset = () => {
    form.resetFields()
    setApplied(BLANK_QUERY)
    setPage(1)
  }

  const columns: TableColumnsType<AuditRecord> = [
    {
      title: '发生时间',
      key: 'occurred_at',
      width: 160,
      render: (_, row) => (row.occurred_at ? formatDateTime(row.occurred_at) : NOT_SET_TEXT),
    },
    { title: '动作', dataIndex: 'action', key: 'action', width: 240 },
    {
      title: '操作人',
      key: 'actor_id',
      width: 160,
      render: (_, row) => row.actor_id ?? NOT_SET_TEXT,
    },
    {
      title: '目标',
      key: 'target',
      width: 240,
      // 目标类型 / 标识**原样显示**（不编造含义）；两者都缺时给"未记录"
      render: (_, row) =>
        row.target_type || row.target_id ? `${row.target_type ?? ''}:${row.target_id ?? ''}` : NOT_SET_TEXT,
    },
    {
      title: '手机号（已脱敏）',
      key: 'phone_masked',
      width: 150,
      render: (_, row) => row.phone_masked ?? NOT_SET_TEXT,
    },
    {
      title: '操作',
      key: 'action_detail',
      width: 96,
      render: (_, row) => (
        <Button size="small" onClick={() => setDetail(row)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <PageContainer
      title="审计日志"
      description={
        tenantWide
          ? '查看本租户的操作记录（只读、不可修改）；可按动作、目标、操作人与时间范围筛选。'
          : '查看你自己的操作记录（只读、不可修改）；范围由服务端按岗位限定，不能查看他人记录。'
      }
    >
      <Space direction="vertical" size={tokens.spacing.lg} style={{ width: '100%' }}>
        {connected ? (
          <Alert type="info" showIcon message={CONNECTED_NOTICE} description={CONNECTED_DESCRIPTION} />
        ) : (
          <Alert type="warning" showIcon message={SAMPLE_DATA_BADGE} description={SAMPLE_DESCRIPTION} />
        )}

        {!tenantWide && <Alert type="info" showIcon message={SELF_SCOPE_NOTE} />}
        {showExportNote && <Alert type="info" showIcon message={AUDIT_EXPORT_NOT_CONNECTED_NOTE} />}

        <Form<FilterValues> form={form} layout="inline" onFinish={handleSearch}>
          <Form.Item label="动作" name="actions">
            <Select
              mode="multiple"
              style={{ minWidth: 260 }}
              placeholder="按动作筛选（可多选）"
              options={catalog.data.items.map((item) => ({ value: item, label: item }))}
              disabled={catalog.state !== 'ready' && catalog.data.items.length === 0}
            />
          </Form.Item>
          <Form.Item label="目标类型" name="target_type">
            <Input placeholder="例如 skill / knowledge" style={{ width: 180 }} maxLength={64} />
          </Form.Item>
          <Form.Item label="目标标识" name="target_id">
            <Input placeholder="例如 summarize@1.0.0" style={{ width: 200 }} maxLength={128} />
          </Form.Item>
          {tenantWide && (
            <Form.Item label="操作人" name="actor_id">
              <Input placeholder="账号标识" style={{ width: 180 }} maxLength={64} />
            </Form.Item>
          )}
          <Form.Item label="时间范围" name="range">
            <DatePicker.RangePicker showTime allowClear />
          </Form.Item>
          <Form.Item>
            <Space size={tokens.spacing.sm}>
              <Button type="primary" htmlType="submit">
                查询
              </Button>
              <Button onClick={handleReset}>重置</Button>
            </Space>
          </Form.Item>
        </Form>

        <div>
          <Typography.Title level={3}>记录列表</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: tokens.spacing.sm }}>
            审计记录为追加型日志：不可编辑、不可删除；时间范围按本地时区选择后会以带时区的标准格式提交。
          </Typography.Paragraph>
          <DataTable<AuditRecord>
            columns={columns}
            rows={audits.data.items}
            rowKey={(row) => row.record_id}
            state={state}
            stateDescription={stateDescription}
            onRetry={audits.reload}
            loadingRows={5}
            pagination={{
              page,
              pageSize,
              total: audits.data.total,
              onChange: (nextPage, nextSize) => {
                setPage(nextPage)
                setPageSize(nextSize)
              },
            }}
          />
          {audits.state === 'ready' && (
            <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.sm }}>
              {/* 命中总数必须可见（2026-09-20 走查发现：原来只在超 200 条时才提示，140 条时用户看不到总数） */}
              {audits.data.total > audits.data.items.length
                ? `共 ${audits.data.total} 条记录，本页显示 ${audits.data.items.length} 条（单页上限 ${AUDITS_LIMIT} 条，请用分页查看）。`
                : `共 ${audits.data.total} 条记录。`}
            </Typography.Paragraph>
          )}
        </div>

        <AuditDetailDrawer record={detail} onClose={() => setDetail(null)} />
      </Space>
    </PageContainer>
  )
}