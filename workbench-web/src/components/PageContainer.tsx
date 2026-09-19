/**
 * 页面容器：标题 + 描述 + 右上操作区 + 内容，并内置四态切换。
 *
 * 标题层级说明：页面级的**唯一 h1 由应用壳提供**（导航标题，见 `src/app/AppShell.tsx`），
 * 所以这里的标题用 `Typography.Title level={2}`，一页只有一个 h1。
 *
 * 四态：不传 `state`（默认 `ready`）时渲染 `children`；传 loading / empty / error / forbidden
 * 时改为统一四态呈现，避免各页面各写一套。
 */
import type { ReactNode } from 'react'
import { Space, Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'
import { tokens } from '../theme/tokens'

export interface PageContainerProps {
  title?: string
  description?: string
  /** 右上操作区（AntD 组件，不要用 div 模拟按钮）。 */
  extra?: ReactNode
  /** 默认 `ready`：正常渲染 children。 */
  state?: ContentStateKind | 'ready'
  /** 非就绪态的说明文案。 */
  stateDescription?: string
  onRetry?: () => void
  children?: ReactNode
}

export function PageContainer({
  title,
  description,
  extra,
  state = 'ready',
  stateDescription,
  onRetry,
  children,
}: PageContainerProps) {
  const hasHeader = Boolean(title || description || extra)

  return (
    <ProCard bordered={false}>
      {hasHeader && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: tokens.spacing.md,
            marginBottom: tokens.spacing.md,
          }}
        >
          <div>
            {title && <Typography.Title level={2}>{title}</Typography.Title>}
            {description && <Typography.Text type="secondary">{description}</Typography.Text>}
          </div>
          {extra && <Space>{extra}</Space>}
        </div>
      )}

      {state === 'ready' ? (
        children
      ) : (
        <ContentState state={state} description={stateDescription} onRetry={onRetry} boxed={false} />
      )}
    </ProCard>
  )
}