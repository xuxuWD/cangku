/**
 * 骨架屏列表：加载态与空态**不得混淆**。
 *
 * 纪律：加载中只出现骨架屏（不出现"暂无数据"），加载完成后才可能进入空态。
 * 行数可配；`state` 默认 `loading`，另外三态（empty / error / forbidden）复用统一四态呈现。
 */
import { Skeleton } from 'antd'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'
import { tokens } from '../theme/tokens'

export interface SkeletonListProps {
  /** 骨架行数，默认 3。 */
  rows?: number
  /** 要呈现的状态，默认 `loading`。 */
  state?: ContentStateKind
  /** 非加载态的说明文案。 */
  stateDescription?: string
  /** `error` 态的重试回调。 */
  onRetry?: () => void
  /** 是否套卡片外壳，默认 true。 */
  boxed?: boolean
}

export function SkeletonList({ rows = 3, state = 'loading', stateDescription, onRetry, boxed = true }: SkeletonListProps) {
  if (state !== 'loading') {
    return (
      <ContentState
        state={state}
        description={stateDescription}
        onRetry={onRetry}
        boxed={boxed}
      />
    )
  }

  const content = (
    <div>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} active title={false} paragraph={{ rows: 1 }} />
      ))}
    </div>
  )

  if (!boxed) return content
  return <div style={{ padding: `${tokens.spacing.md}px 0` }}>{content}</div>
}