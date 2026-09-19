/**
 * 四态占位组件：loading / empty / error / forbidden。
 *
 * 纪律：任何数据区域都必须显式给出这四种状态，禁止用"一直转圈"或空白页糊弄。
 * 第 1 轮由 8 个占位页复用；后续接真实数据时仍是全站唯一的四态出口。
 */
import { Button, Empty, Result, Spin, Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { tokens } from '../theme/tokens'

export type ContentStateKind = 'loading' | 'empty' | 'error' | 'forbidden'

/** 未传 `description` 时的默认文案。 */
const DEFAULT_TEXT: Record<ContentStateKind, string> = {
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
}

export function ContentState({ state, description, onRetry }: ContentStateProps) {
  const text = description ?? DEFAULT_TEXT[state]

  return (
    <ProCard bordered={false} style={{ minHeight: 240 }}>
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

        {state === 'empty' && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />}

        {state === 'error' && (
          <Result
            status="error"
            title="出错了"
            subTitle={text}
            extra={
              onRetry ? (
                <Button type="primary" onClick={onRetry}>
                  重试
                </Button>
              ) : undefined
            }
          />
        )}

        {state === 'forbidden' && <Result status="403" title="无访问权限" subTitle={text} />}
      </div>
    </ProCard>
  )
}