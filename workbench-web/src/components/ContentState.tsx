/**
 * 四态占位组件：loading / empty / error / forbidden —— 全站四态的唯一出口。
 *
 * 纪律：任何数据区域都必须显式给出这四种状态，禁止用"一直转圈"或空白页糊弄。
 * 第 1 轮由 8 个占位页复用；第 2 轮的组件库（PageContainer / DataTable / SkeletonList /
 * FormDrawer / DangerConfirm / PermissionGuard）都在它之上拼装，不各写一套。
 */
import type { ReactNode } from 'react'
import { Button, Empty, Result, Space, Spin, Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { tokens } from '../theme/tokens'

export type ContentStateKind = 'loading' | 'empty' | 'error' | 'forbidden'

/** 四态的**统一文案**（唯一来源，各组件不要另写一套）。 */
export const CONTENT_STATE_TEXT: Record<ContentStateKind, string> = {
  loading: '正在加载，请稍候…',
  empty: '暂无内容。',
  error: '加载失败，请稍后再试。',
  forbidden: '你没有查看该内容的权限。',
}

export interface ContentStateProps {
  state: ContentStateKind
  /** 覆盖默认说明文案。 */
  description?: string
  /** 仅 `error` 态使用：重试回调；不传则不渲染重试按钮。 */
  onRetry?: () => void
  /** 主操作区（空态主按钮、无权限的"申请权限"入口等）。 */
  action?: ReactNode
  /**
   * 是否套一层卡片外壳（默认 true，页面级区域用）。
   * 嵌进弹层 / 表格内部时传 false，避免"卡片套卡片"。
   */
  boxed?: boolean
}

export function ContentState({ state, description, onRetry, action, boxed = true }: ContentStateProps) {
  const text = description ?? CONTENT_STATE_TEXT[state]
  const retryButton = onRetry ? (
    <Button type="primary" onClick={onRetry}>
      重试
    </Button>
  ) : null

  const body = (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: `${tokens.spacing.xl}px 0`,
        textAlign: 'center',
      }}
    >
      {state === 'loading' && (
        <div
          role="status"
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: tokens.spacing.md }}
        >
          <Spin size="large" />
          <Typography.Text type="secondary">{text}</Typography.Text>
        </div>
      )}

      {state === 'empty' && (
        <div
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: tokens.spacing.md }}
        >
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />
          {action}
        </div>
      )}

      {state === 'error' && (
        <Result
          status="error"
          title="出错了"
          subTitle={text}
          extra={retryButton || action ? <Space>{retryButton}{action}</Space> : undefined}
        />
      )}

      {state === 'forbidden' && (
        <Result status="403" title="无访问权限" subTitle={text} extra={action ?? undefined} />
      )}
    </div>
  )

  if (!boxed) return body
  return (
    <ProCard bordered={false} style={{ minHeight: 240 }}>
      {body}
    </ProCard>
  )
}