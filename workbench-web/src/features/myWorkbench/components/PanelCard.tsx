/**
 * 面板卡片：四块共用的外框（标题 + 右上角 + 四态）。
 *
 * 为什么抽出来：四块卡片各写一遍标题 / 右角 / 四态就是同一件事做四遍。
 * 四态**只在这里处理一次**（loading / empty / error / forbidden），面板只管"就绪时长什么样"。
 * 卡片表面用 ProCard，不覆盖 AntD 样式；间距与圆角一律取令牌。
 */
import type { ReactNode } from 'react'
import { ProCard } from '@ant-design/pro-components'
import { ContentState } from '../../../components'
import type { ContentStateKind } from '../../../components'

export interface PanelCardProps {
  title: string
  /** 卡片右上角（例如"示例数据（未接后端）"标识）。 */
  extra?: ReactNode
  /** 默认 `ready`：正常渲染 children。 */
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
  children?: ReactNode
}

export function PanelCard({
  title,
  extra,
  state = 'ready',
  stateDescription,
  onRetry,
  children,
}: PanelCardProps) {
  // 加载中一律用统一加载文案：**绝不能**把"加载失败"之类的失败说明用在加载态上
  // （那会让"还在转圈"看起来像"已经出错"）。失败说明只在 error / forbidden 时使用。
  const description = state === 'loading' ? undefined : stateDescription

  return (
    <ProCard bordered={false} title={title} extra={extra}>
      {state === 'ready' ? (
        children
      ) : (
        <ContentState state={state} description={description} onRetry={onRetry} boxed={false} />
      )}
    </ProCard>
  )
}