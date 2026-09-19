/**
 * 快捷入口：4 个常用入口 + 2 个管理类入口（入口目录为前端静态定义，见契约 §4）。
 *
 * **关键演示**：管理类入口对无权限角色**渲染为禁用 + 原因提示**，而不是静默隐藏 ——
 * "隐藏按钮"不是权限控制，也让人以为功能不存在；真正能不能调用，由服务端判定。
 */
import { Button, Space, Typography } from 'antd'
import { EmptyState } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { CAPABILITY_LABEL, hasCapability, ROLE_LABEL, useSession } from '../../../app/session'
import { tokens } from '../../../theme/tokens'
import type { QuickActionItem } from '../types'
import { PanelCard } from './PanelCard'

export interface QuickActionsProps {
  actions: QuickActionItem[]
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
  /** 入口调用（本轮不接路由 / 后端，只回调）。 */
  onRun?: (action: QuickActionItem) => void
}

export function QuickActions({ actions, state = 'ready', stateDescription, onRetry, onRun }: QuickActionsProps) {
  const role = useSession((current) => current.role)

  return (
    <PanelCard title="快捷入口" state={state} stateDescription={stateDescription} onRetry={onRetry}>
      {actions.length === 0 ? (
        <EmptyState boxed={false} description="暂无可用的快捷入口。" />
      ) : (
        <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
          {actions.map((action) => {
            // 无能力要求 = 所有角色可用；有要求则按本地能力桩判定（真实判定在服务端）。
            const allowed = action.capability === null || hasCapability(role, action.capability)
            const requirement = action.capability

            return (
              <div
                key={action.key}
                style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm }}
              >
                <Button disabled={!allowed} onClick={() => onRun?.(action)}>
                  {action.label}
                </Button>
                {!allowed && requirement && (
                  <Typography.Text type="secondary">
                    需要「{CAPABILITY_LABEL[requirement]}」权限，当前角色「{ROLE_LABEL[role]}」不可用（入口保留以便申请）。
                  </Typography.Text>
                )}
              </div>
            )
          })}
        </Space>
      )}
    </PanelCard>
  )
}