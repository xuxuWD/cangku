/**
 * 「可检索文档」块：检索谓词守卫白名单出口（只返回 `published` 且未过复核期的文档），**只读**。
 *
 * 为什么单独成块：文档列表里"已发布"不等于"可被检索"（过期后会被扫描置为待复核并从白名单移除），
 * 本块直接显示**服务端认定的可检索范围**，避免让人误以为"列表里是已发布就一定能搜到"。
 *
 * 「扫描到期文档」是契约 §1 声明的管理动作（`POST /review-scan`，幂等）：把已过期文档置为待复核。
 */
import { Alert, Button, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import type { KnowledgeDoc } from '../types'
import { NO_DUE_TEXT } from './DocumentPanel'

/** 本块固定说明（界面必须写明"为什么这里可能比文档列表少"）。 */
export const ELIGIBLE_DESCRIPTION = '当前可被检索的文档（已发布且未过复核期）'

export interface EligiblePanelProps {
  items: KnowledgeDoc[]
  state: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry: () => void
  onScan: () => void
  scanPending?: boolean
  /** 扫描结果 / 失败的就地提示（服务端回读值，不本地猜）。 */
  scanNote?: string | null
}

export function EligiblePanel({
  items,
  state,
  stateDescription,
  onRetry,
  onScan,
  scanPending = false,
  scanNote = null,
}: EligiblePanelProps) {
  const columns: TableColumnsType<KnowledgeDoc> = [
    { title: '文档标识', dataIndex: 'document_id', key: 'document_id', width: 200 },
    { title: '标题', dataIndex: 'title', key: 'title' },
    {
      title: '复核到期',
      key: 'review_due_at',
      width: 176,
      render: (_, row) =>
        row.review_due_at ? (
          formatDateTime(row.review_due_at)
        ) : (
          <Typography.Text type="secondary">{NO_DUE_TEXT}</Typography.Text>
        ),
    },
  ]

  const tableState: ContentStateKind | 'ready' = state === 'ready' && items.length === 0 ? 'empty' : state

  return (
    <div>
      <Typography.Title level={3}>可检索文档</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {ELIGIBLE_DESCRIPTION}
      </Typography.Paragraph>
      {scanNote && (
        <Alert type="info" showIcon message={scanNote} style={{ marginTop: tokens.spacing.sm }} />
      )}
      <div style={{ marginTop: tokens.spacing.sm, marginBottom: tokens.spacing.sm }}>
        {/* 到期扫描：幂等管理动作；结果用服务端返回值如实说明 */}
        <Button size="small" loading={scanPending} onClick={onScan}>
          扫描到期文档
        </Button>
        <Typography.Text type="secondary" style={{ marginLeft: tokens.spacing.sm }}>
          把已过复核期的文档置为「待复核」；重复执行不会重复置位。
        </Typography.Text>
      </div>
      <DataTable<KnowledgeDoc>
        columns={columns}
        rows={items}
        rowKey={(row) => row.document_id}
        state={tableState}
        stateDescription={tableState === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
      />
    </div>
  )
}