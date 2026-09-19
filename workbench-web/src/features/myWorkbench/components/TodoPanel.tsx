/**
 * 待办面板：站内通知 / 待审批（**样例数据**，未接后端）。
 *
 * 每项含：类型标签（`StatusTag`）+ 标题 + 时间 + "查看"跳转占位（本轮不接路由，只回调）。
 * 四态（loading / empty / error / forbidden）由 `PanelCard` 统一处理，props 可切换。
 */
import type { TableColumnsType } from 'antd'
import { Button, Space } from 'antd'
import { DataTable, EmptyState, StatusTag } from '../../../components'
import type { ContentStateKind, StatusTone } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../format'
import { SAMPLE_DATA_BADGE } from '../services/myWorkbenchService'
import type { TodoItem, TodoKind } from '../types'
import { PanelCard } from './PanelCard'

/** 类型 → 中文标签（受控枚举：不在调用处随手写状态字符串）。 */
const TODO_KIND_LABEL: Record<TodoKind, string> = {
  task_approval: '任务审批',
  plan_proposal: '计划提案',
  run_approval: '运行审批',
  account_registration: '账号注册审批',
  notification_result: '结果通知',
  other: '其他事项',
}

/** 类型 → 语义色（受控枚举，禁止传颜色值）。 */
const TODO_KIND_TONE: Record<TodoKind, StatusTone> = {
  task_approval: 'warning',
  plan_proposal: 'info',
  run_approval: 'warning',
  account_registration: 'info',
  notification_result: 'neutral',
  other: 'neutral',
}

export interface TodoPanelProps {
  items: TodoItem[]
  /** 是否样例数据：为 true 时卡片右上角显示"示例数据（未接后端）"。 */
  sample?: boolean
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
  /** 跳转占位：本轮不接路由，只把点击交回调用方。 */
  onOpen?: (item: TodoItem) => void
  /** 标记已读（只有 `inbox_id` 非空的站内通知可标记；审批没有"已读"概念）。 */
  onMarkRead?: (item: TodoItem) => void
  /** 正在标记已读的条目（同一时刻只允许一条，避免重复提交）。 */
  markingKey?: string | null
}

/** 行键：同一通知 / 审批在合并列表里的唯一标识。 */
export function todoRowKey(item: TodoItem): string {
  return `${item.source}:${item.kind}:${item.target_id}`
}

export function TodoPanel({
  items,
  sample = false,
  state = 'ready',
  stateDescription,
  onRetry,
  onOpen,
  onMarkRead,
  markingKey = null,
}: TodoPanelProps) {
  const columns: TableColumnsType<TodoItem> = [
    {
      title: '类型',
      key: 'kind',
      width: 128,
      render: (_, row) => <StatusTag tone={TODO_KIND_TONE[row.kind]}>{TODO_KIND_LABEL[row.kind]}</StatusTag>,
    },
    { title: '标题', dataIndex: 'title', key: 'title' },
    {
      title: '时间',
      key: 'created_at',
      width: 160,
      render: (_, row) => formatDateTime(row.created_at),
    },
    {
      title: '操作',
      key: 'action',
      width: 176,
      render: (_, row) => (
        <Space size={tokens.spacing.sm}>
          <Button onClick={() => onOpen?.(row)}>查看</Button>
          {onMarkRead && (
            // 审批类待办没有已读概念：按钮**禁用并说明原因**，不静默隐藏
            <Button
              disabled={row.inbox_id === null || markingKey === todoRowKey(row)}
              loading={markingKey === todoRowKey(row)}
              title={row.inbox_id === null ? '审批类待办没有"已读"状态' : undefined}
              onClick={() => onMarkRead(row)}
            >
              标记已读
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <PanelCard
      title="待办"
      extra={sample ? <StatusTag tone="warning">{SAMPLE_DATA_BADGE}</StatusTag> : undefined}
      state={state}
      stateDescription={stateDescription}
      onRetry={onRetry}
    >
      {items.length === 0 ? (
        <EmptyState boxed={false} description="当前没有待办（待审批与未读通知都为空）。" />
      ) : (
        <DataTable<TodoItem> columns={columns} rows={items} rowKey={todoRowKey} />
      )}
    </PanelCard>
  )
}