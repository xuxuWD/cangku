/**
 * 最近使用面板：最近会话 / 最近运行（**样例数据**，未接后端）。
 *
 * 四态由 `PanelCard` 统一处理；**加载态与空态必须可区分**：
 * 加载中只出现"正在加载"（不出现"暂无"），加载完成后才可能显示空态文案。
 */
import { Button, List, Space } from 'antd'
import { EmptyState, StatusTag } from '../../../components'
import type { ContentStateKind, StatusTone } from '../../../components'
import { formatDateTime } from '../format'
import { SAMPLE_DATA_BADGE } from '../services/myWorkbenchService'
import { tokens } from '../../../theme/tokens'
import type { RecentItem, RecentKind } from '../types'
import { PanelCard } from './PanelCard'

/** 条目种类 → 标签（受控枚举）。 */
const RECENT_KIND_LABEL: Record<RecentKind, string> = {
  conversation: '会话',
  run: '运行',
}

const RECENT_KIND_TONE: Record<RecentKind, StatusTone> = {
  conversation: 'info',
  run: 'neutral',
}

export interface RecentPanelProps {
  items: RecentItem[]
  /** 是否样例数据：为 true 时卡片右上角显示"示例数据（未接后端）"。 */
  sample?: boolean
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
  /** 跳转占位：本轮不接路由，只把点击交回调用方。 */
  onOpen?: (item: RecentItem) => void
}

export function RecentPanel({ items, sample = false, state = 'ready', stateDescription, onRetry, onOpen }: RecentPanelProps) {
  return (
    <PanelCard
      title="最近使用"
      extra={sample ? <StatusTag tone="warning">{SAMPLE_DATA_BADGE}</StatusTag> : undefined}
      state={state}
      stateDescription={stateDescription}
      onRetry={onRetry}
    >
      {items.length === 0 ? (
        <EmptyState boxed={false} description="暂无最近使用记录。" />
      ) : (
        <List
          dataSource={items}
          rowKey={(item) => `${item.kind}:${item.target_id}`}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="open" onClick={() => onOpen?.(item)}>
                  打开
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={tokens.spacing.sm}>
                    <StatusTag tone={RECENT_KIND_TONE[item.kind]}>{RECENT_KIND_LABEL[item.kind]}</StatusTag>
                    {item.title}
                  </Space>
                }
                description={`最近更新：${formatDateTime(item.updated_at)}`}
              />
            </List.Item>
          )}
        />
      )}
    </PanelCard>
  )
}