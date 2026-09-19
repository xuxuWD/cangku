/**
 * 「最近变更」块（**只读**）：知识范围绑定的变更留痕（`old → new` 两列 + 操作者 + 时间）。
 *
 * 口径：
 *  - 只读 —— 本块不提供任何写入入口；
 *  - 空态是**真实语义**（确实没有变更过），文案为「暂无变更记录」，**不得**标成加载失败；
 *  - 不展示 `tenant_id`（租户标识无界面价值）；`actor_id` 是不透明账号标识（非手机号 / 非凭据）。
 */
import { Space, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { formatDateTime } from '../../../utils/format'
import { BINDING_TYPE_LABEL } from '../types'
import type { KnowledgeAuditEntry } from '../types'

/** 变更前后的空集文案（空数组 ≠ 没有记录）。 */
export const EMPTY_SET_TEXT = '（无）'

export interface AuditPanelProps {
  items: KnowledgeAuditEntry[]
  state: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry: () => void
}

/** 标识集合 → 只读呈现（空集合写「（无）」，不写 "0"）。 */
function IdSet({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <Typography.Text type="secondary">{EMPTY_SET_TEXT}</Typography.Text>
  return (
    <Space size={4} wrap>
      {ids.map((id) => (
        <Tag key={id}>{id}</Tag>
      ))}
    </Space>
  )
}

export function AuditPanel({ items, state, stateDescription, onRetry }: AuditPanelProps) {
  const columns: TableColumnsType<KnowledgeAuditEntry> = [
    {
      title: '对象',
      key: 'object',
      width: 200,
      render: (_, row) => `${BINDING_TYPE_LABEL[row.binding_type]}「${row.binding_key}」`,
    },
    {
      title: '变更前',
      key: 'old',
      render: (_, row) => <IdSet ids={row.old_knowledge_base_ids} />,
    },
    {
      title: '变更后',
      key: 'new',
      render: (_, row) => <IdSet ids={row.new_knowledge_base_ids} />,
    },
    { title: '操作者', dataIndex: 'actor_id', key: 'actor_id', width: 176 },
    {
      title: '时间',
      key: 'occurred_at',
      width: 160,
      render: (_, row) => formatDateTime(row.occurred_at),
    },
  ]

  const tableState: ContentStateKind | 'ready' = state === 'ready' && items.length === 0 ? 'empty' : state

  return (
    <div>
      <Typography.Title level={3}>最近变更</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        知识范围的每次变更都会在这里留痕（只读，最多展示最近 20 条）。
      </Typography.Paragraph>
      <DataTable<KnowledgeAuditEntry>
        columns={columns}
        rows={items}
        rowKey={(row) => `${row.binding_type}:${row.binding_key}:${row.occurred_at}`}
        state={tableState}
        stateDescription={tableState === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
      />
    </div>
  )
}