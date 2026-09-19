/**
 * 「文档列表」块：状态标签 + 版本 + 来源 + 复核到期 + 状态机驱动的管理动作。
 *
 * 纪律：
 *  - 四态由 `DataTable` 统一呈现（加载 = 骨架屏，不出现"暂无数据"）；
 *  - 空态文案**必须解释为什么空**（由调用方传入），不显示"0 条"冒充内容；
 *  - 动作按契约 §2 的**合法前置状态**启用；不合法一律 `disabled` + `title` 给原因
 *    （**不静默隐藏**）——`archived` 是终态，发布 / 归档 / 复核全部不可再执行；
 *  - 未知状态**不误标**成已知状态（中性标签 + "未定义状态"），且动作全部禁用。
 */
import { Button, Space, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, StatusTag } from '../../../components'
import type { ContentStateKind, StatusTone } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import {
  DOC_ACTION_LABEL,
  KNOWLEDGE_STATUS_LABEL,
  UNKNOWN_STATUS_TEXT,
  actionDisabledReason,
} from '../types'
import type { DocAction, DocumentStatus, KnowledgeDoc } from '../types'

/** 状态 → 语义色（未知状态走中性标签，不用语义色）。 */
const STATUS_TONE: Record<Exclude<DocumentStatus, 'unknown'>, StatusTone> = {
  draft: 'neutral',
  published: 'success',
  needs_review: 'warning',
  archived: 'neutral',
}

/** 复核到期为空时的如实文案（**不编造时间**）。 */
export const NO_DUE_TEXT = '未设置'

/** 行内四个管理动作（顺序即展示顺序）。 */
const ROW_ACTIONS: readonly DocAction[] = ['publish', 'archive', 'review_approve', 'review_reject']

export interface DocumentPanelProps {
  docs: KnowledgeDoc[]
  state: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry: () => void
  onAction: (action: DocAction, doc: KnowledgeDoc) => void
  /** 列表被单页上限截断时的如实说明。 */
  truncationNote?: string
  /** 正在提交的动作（该行按钮进入 loading / 防重复点击）。 */
  pending?: { document_id: string; action: DocAction } | null
}

function statusTag(status: DocumentStatus) {
  if (status === 'unknown') return <StatusTag tone="neutral">{UNKNOWN_STATUS_TEXT}</StatusTag>
  return <StatusTag tone={STATUS_TONE[status]}>{KNOWLEDGE_STATUS_LABEL[status]}</StatusTag>
}

export function DocumentPanel({
  docs,
  state,
  stateDescription,
  onRetry,
  onAction,
  truncationNote,
  pending = null,
}: DocumentPanelProps) {
  const columns: TableColumnsType<KnowledgeDoc> = [
    { title: '文档标识', dataIndex: 'document_id', key: 'document_id', width: 200 },
    { title: '标题', dataIndex: 'title', key: 'title' },
    { title: '状态', key: 'status', width: 104, render: (_, row) => statusTag(row.status) },
    { title: '版本', dataIndex: 'version', key: 'version', width: 72 },
    {
      title: '来源',
      key: 'source_key',
      width: 112,
      // 未知来源**原样显示**（不编造含义）
      render: (_, row) => <Tag>{row.source_key || '—'}</Tag>,
    },
    {
      title: '复核到期',
      key: 'review_due_at',
      width: 160,
      render: (_, row) =>
        row.review_due_at ? (
          formatDateTime(row.review_due_at)
        ) : (
          <Typography.Text type="secondary">{NO_DUE_TEXT}</Typography.Text>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      render: (_, row) => {
        const busy = pending?.document_id === row.document_id
        return (
          <Space size={tokens.spacing.sm} wrap>
            {ROW_ACTIONS.map((action) => {
              const reason = actionDisabledReason(action, row.status)
              return (
                <Button
                  key={action}
                  size="small"
                  danger={action === 'archive'}
                  disabled={reason !== null || busy}
                  // 禁用原因必须可见（原生提示），不静默隐藏按钮
                  title={reason ?? undefined}
                  loading={busy && pending?.action === action}
                  onClick={() => onAction(action, row)}
                >
                  {DOC_ACTION_LABEL[action]}
                </Button>
              )
            })}
          </Space>
        )
      },
    },
  ]

  // 就绪但一行没有 ⇒ 交给统一的空态（带"为什么空"的说明），不渲染空表格
  const tableState: ContentStateKind | 'ready' = state === 'ready' && docs.length === 0 ? 'empty' : state

  return (
    <div>
      <Typography.Title level={3}>文档列表</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        登记后会以「草稿」存在；发布后进入可检索范围，并按复核周期到期提醒（发布 / 归档 / 复核以服务端判定为准）。
      </Typography.Paragraph>
      {truncationNote && (
        <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.sm, marginBottom: 0 }}>
          {truncationNote}
        </Typography.Paragraph>
      )}
      <DataTable<KnowledgeDoc>
        columns={columns}
        rows={docs}
        rowKey={(row) => row.document_id}
        state={tableState}
        // 加载态一律用组件的骨架屏：绝不把失败说明用在加载态上
        stateDescription={tableState === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
        loadingRows={4}
      />
    </div>
  )
}