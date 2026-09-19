/**
 * 指标卡：标签 + 数值 + 单位 + 趋势。
 *
 * **状态保真（硬要求）**：数据非就绪时必须显示"未配置 / 样本不足 / 未验证"，
 * **绝不能**渲染成 `0`，也不能带上趋势（不得给人"已成功"的错觉）；没数值时显示"暂无"。
 * 四态（loading / empty / error / forbidden）通过 `state` 切换，复用统一四态呈现。
 */
import { ArrowDownOutlined, ArrowUpOutlined, MinusOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { ContentState } from './ContentState'
import type { ContentStateKind } from './ContentState'
import type { DataPresence } from './dataPresence'
import { presenceLabel } from './dataPresence'
import { tokens } from '../theme/tokens'

/** 趋势：方向 + 文案（文案由调用方给，组件不编造结论）。 */
export interface StatCardTrend {
  direction: 'up' | 'down' | 'flat'
  text: string
}

export interface StatCardProps {
  /** 指标名。 */
  label: string
  /** 数值或文本值；不传按"暂无"处理（不会显示 0）。 */
  value?: number | string
  /** 单位（非就绪态不显示）。 */
  unit?: string
  /** 趋势（数据非就绪时不显示）。 */
  trend?: StatCardTrend
  /** 数据可用性，默认 `ready`。 */
  presence?: DataPresence
  /** 数据态，默认 `ready`。 */
  state?: ContentStateKind | 'ready'
  /** 非就绪态的说明文案。 */
  stateDescription?: string
  onRetry?: () => void
}

const TREND_TYPE: Record<StatCardTrend['direction'], 'success' | 'danger' | 'secondary'> = {
  up: 'success',
  down: 'danger',
  flat: 'secondary',
}

function TrendMark({ trend }: { trend: StatCardTrend }) {
  const icon =
    trend.direction === 'up' ? <ArrowUpOutlined /> : trend.direction === 'down' ? <ArrowDownOutlined /> : <MinusOutlined />
  return (
    <Typography.Text type={TREND_TYPE[trend.direction]}>
      {icon} {trend.text}
    </Typography.Text>
  )
}

export function StatCard({
  label,
  value,
  unit,
  trend,
  presence = 'ready',
  state = 'ready',
  stateDescription,
  onRetry,
}: StatCardProps) {
  if (state !== 'ready') {
    return (
      <ProCard bordered={false}>
        <Typography.Text type="secondary">{label}</Typography.Text>
        <ContentState state={state} description={stateDescription} onRetry={onRetry} boxed={false} />
      </ProCard>
    )
  }

  const placeholder = presenceLabel(presence)
  const hasValue = value !== undefined && value !== null && value !== ''
  // 保真三态优先于数值：非就绪时展示占位文案，而不是 0。
  const display = placeholder ?? (hasValue ? String(value) : '暂无')

  return (
    <ProCard bordered={false}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: tokens.spacing.sm }}>
        <Typography.Text strong style={{ fontSize: tokens.fontSize.xl, lineHeight: tokens.lineHeight }}>
          {display}
        </Typography.Text>
        {!placeholder && hasValue && unit && <Typography.Text type="secondary">{unit}</Typography.Text>}
      </div>
      {!placeholder && hasValue && trend && <TrendMark trend={trend} />}
    </ProCard>
  )
}