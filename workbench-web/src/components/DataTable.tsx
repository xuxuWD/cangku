/**
 * 表格封装：直接用 AntD `Table`（**不改样式、不写覆盖 CSS**），只补四态、分页与列定义泛型。
 *
 * 四态：`state` 切换 loading / empty / error / forbidden，空态与错误态文案可区分；
 * 加载中显示骨架行而不是"暂无数据"，避免加载与空态混淆。
 *
 * **状态保真（硬要求）**：`presence` 非 `ready` 时，按"未配置 / 样本不足 / 未验证"
 * 如实展示，不渲染表格、不把缺失数据显示成 `0`。
 */
import type { ReactNode } from 'react'
import { Table } from 'antd'
import type { TableColumnsType } from 'antd'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'
import { SkeletonList } from './SkeletonList'
import type { DataPresence } from './dataPresence'
import { presenceDescription } from './dataPresence'

/** 分页（服务端分页语义：`rows` 是当前页数据，翻页只回调，不在前端切片）。 */
export interface DataTablePagination {
  page: number
  pageSize: number
  total: number
  onChange: (page: number, pageSize: number) => void
}

export interface DataTableProps<T> {
  /** 列定义：直接用 AntD 的泛型列类型，避免自造一套。 */
  columns: TableColumnsType<T>
  rows: T[]
  /** 行主键。 */
  rowKey: (row: T) => string
  /** 数据态，默认 `ready`。 */
  state?: ContentStateKind | 'ready'
  /** 数据可用性，默认 `ready`；非就绪时不渲染表格。 */
  presence?: DataPresence
  /** 空态 / 错误态的自定义说明文案。 */
  stateDescription?: string
  onRetry?: () => void
  /** 需要分页时传入；不传则用 AntD 默认分页（单页时自动隐藏）。 */
  pagination?: DataTablePagination
  /** 加载态骨架行数，默认 3。 */
  loadingRows?: number
  emptyAction?: ReactNode
}

export function DataTable<T extends object>({
  columns,
  rows,
  rowKey,
  state = 'ready',
  presence = 'ready',
  stateDescription,
  onRetry,
  pagination,
  loadingRows = 3,
  emptyAction,
}: DataTableProps<T>) {
  // ① 加载中：骨架行，不出现"暂无数据"。
  if (state === 'loading') {
    return <SkeletonList rows={loadingRows} state="loading" boxed={false} />
  }

  // ② 错误 / 无权限：与空态文案明显不同。
  if (state === 'error' || state === 'forbidden') {
    return <ContentState state={state} description={stateDescription} onRetry={onRetry} boxed={false} />
  }

  // ③ 状态保真：非就绪态不讲数值故事。
  const presenceText = presenceDescription(presence)
  if (presenceText || state === 'empty') {
    return (
      <ContentState
        state="empty"
        description={presenceText ?? stateDescription}
        action={emptyAction}
        boxed={false}
      />
    )
  }

  return (
    <Table<T>
      columns={columns}
      dataSource={rows}
      rowKey={rowKey}
      pagination={
        pagination
          ? {
              current: pagination.page,
              pageSize: pagination.pageSize,
              total: pagination.total,
              showSizeChanger: false,
              onChange: pagination.onChange,
            }
          : { pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }
      }
    />
  )
}