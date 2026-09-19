/**
 * 组件库统一出口（第 2 轮）。
 *
 * 口径：这里的组件是**基于 AntD 的业务组合组件** —— 不重写 Button / Table，不做样式覆盖，
 * 颜色与圆角一律走 `src/theme/tokens.ts` 下发的 ConfigProvider 令牌。
 */
export { ContentState, CONTENT_STATE_TEXT } from './ContentState'
export type { ContentStateKind, ContentStateProps } from './ContentState'

export { DATA_PRESENCE_DESCRIPTION, DATA_PRESENCE_LABEL, presenceDescription, presenceLabel } from './dataPresence'
export type { DataPresence } from './dataPresence'

export { PageContainer } from './PageContainer'
export type { PageContainerProps } from './PageContainer'

export { DataTable } from './DataTable'
export type { DataTablePagination, DataTableProps } from './DataTable'

export { StatCard } from './StatCard'
export type { StatCardProps, StatCardTrend } from './StatCard'

export { StatusTag } from './StatusTag'
export type { StatusTagProps, StatusTone } from './StatusTag'

export { EmptyState } from './EmptyState'
export type { EmptyStateProps } from './EmptyState'

export { SkeletonList } from './SkeletonList'
export type { SkeletonListProps } from './SkeletonList'

export { FormDrawer } from './FormDrawer'
export type { FormDrawerProps } from './FormDrawer'

export { PermissionGuard } from './PermissionGuard'
export type { PermissionGuardProps } from './PermissionGuard'

export { DangerConfirm } from './DangerConfirm'
export type { DangerConfirmProps } from './DangerConfirm'