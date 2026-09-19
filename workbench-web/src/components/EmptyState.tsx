/**
 * 空态组件：统一文案 + 可选主操作按钮。
 *
 * 默认渲染空态（文案由 `ContentState` 的统一文案提供，不在各处另写）；
 * 也可以传入其它四态（loading / error / forbidden）复用同一套呈现，
 * 这样页面上"没数据"这件事只有一种长相。
 */
import type { ReactNode } from 'react'
import { Button } from 'antd'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'

export interface EmptyStateProps {
  /** 说明文案；不传用统一空态文案。 */
  description?: string
  /** 主操作按钮文案；与 `onAction` 成对使用。 */
  actionText?: string
  onAction?: () => void
  /** 需要更复杂的操作区时直接给节点（与 `actionText` 二选一）。 */
  action?: ReactNode
  /** 要呈现的状态，默认 `empty`。 */
  state?: ContentStateKind
  /** `error` 态的重试回调。 */
  onRetry?: () => void
  /** 是否套卡片外壳，默认 true。 */
  boxed?: boolean
}

export function EmptyState({
  description,
  actionText,
  onAction,
  action,
  state = 'empty',
  onRetry,
  boxed = true,
}: EmptyStateProps) {
  const primaryAction =
    action ??
    (actionText ? (
      <Button type="primary" onClick={onAction}>
        {actionText}
      </Button>
    ) : undefined)

  return (
    <ContentState
      state={state}
      description={description}
      onRetry={onRetry}
      action={primaryAction}
      boxed={boxed}
    />
  )
}