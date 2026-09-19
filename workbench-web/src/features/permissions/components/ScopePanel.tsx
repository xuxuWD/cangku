/**
 * 范围块（「角色知识范围」与「数字员工知识范围」共用的表格）—— 两块只有文案与标识列名不同，
 * 抽成一个组件，避免"同一件事做两遍"。
 *
 * 纪律：
 *  - 四态与空态由 `DataTable` 统一呈现（加载 = 骨架屏，不出现"暂无数据"）；
 *  - 空态文案**必须解释为什么空**（由调用方传入），绝不显示"0 条绑定"冒充内容；
 *  - 未绑定 ≠ 0 条：行内如实写「尚未绑定任何知识库」。
 */
import { Button, Space, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { DataTable, StatusTag } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { DIRECTORY_STATUS_LABEL } from '../types'
import type { ScopeRow } from '../types'

/** 未绑定的固定文案（**不得**写成"0 条"）。 */
export const NO_BINDING_TEXT = '尚未绑定任何知识库'

export interface ScopePanelProps {
  title: string
  description: string
  /** 标识列名（「岗位标识」/「员工标识」）。 */
  keyColumnTitle: string
  rows: ScopeRow[]
  state: ContentStateKind | 'ready'
  /** 非就绪态的说明（空态 = 为什么空；错误 / 无权限各自说清）。 */
  stateDescription?: string
  onRetry: () => void
  onEdit: (row: ScopeRow) => void
}

export function ScopePanel({
  title,
  description,
  keyColumnTitle,
  rows,
  state,
  stateDescription,
  onRetry,
  onEdit,
}: ScopePanelProps) {
  const columns: TableColumnsType<ScopeRow> = [
    { title: keyColumnTitle, dataIndex: 'binding_key', key: 'binding_key', width: 200 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 200 },
    {
      title: '状态',
      key: 'status',
      width: 96,
      render: (_, row) => (
        <StatusTag tone={row.status === 'active' ? 'success' : 'neutral'}>
          {DIRECTORY_STATUS_LABEL[row.status]}
        </StatusTag>
      ),
    },
    {
      title: '知识范围',
      key: 'knowledge_base_ids',
      render: (_, row) =>
        row.knowledge_base_ids.length === 0 ? (
          <Typography.Text type="secondary">{NO_BINDING_TEXT}</Typography.Text>
        ) : (
          <Space size={4} wrap>
            {row.knowledge_base_ids.map((id) => (
              <Tag key={id}>{id}</Tag>
            ))}
          </Space>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, row) => (
        <Button size="small" onClick={() => onEdit(row)}>
          编辑范围
        </Button>
      ),
    },
  ]

  // 就绪但一行没有 ⇒ 交给统一的空态（带"为什么空"的说明），不渲染空表格
  const tableState: ContentStateKind | 'ready' = state === 'ready' && rows.length === 0 ? 'empty' : state

  return (
    <div>
      <Typography.Title level={3}>{title}</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {description}
      </Typography.Paragraph>
      <DataTable<ScopeRow>
        columns={columns}
        rows={rows}
        rowKey={(row) => `${row.binding_type}:${row.binding_key}`}
        state={tableState}
        // 加载态一律用组件的骨架屏：绝不把失败说明用在加载态上
        stateDescription={tableState === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
      />
    </div>
  )
}