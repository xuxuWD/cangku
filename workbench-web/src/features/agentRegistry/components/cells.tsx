/**
 * 列 / 详情共用的单元格渲染器（同一件事只在渲染一次，表格与抽屉都从这里取）。
 *
 * **状态保真（硬要求）**：未验证 / 样本不足 / 未配置时**不渲染任何数字**，
 * 只给受控枚举标签 + 一句说明 —— 绝不允许出现 `0%` 或"成功"这类结论。
 */
import { Space, Typography } from 'antd'
import { StatusTag } from '../../../components'
import type { DataPresence } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime, formatPercent } from '../../../utils/format'
import type { AgentUsageStats, RegistryRow, RegistrySharedFields } from '../types'
import { AGENT_STATUS_LABEL, AGENT_STATUS_TONE, lastRunPresence, usagePresence } from '../types'

/** 非就绪态的一句说明（就绪态不显示）。 */
const PRESENCE_EXPLAIN: Partial<Record<DataPresence, string>> = {
  unverified: '暂无运行统计',
  insufficient_sample: '暂无运行（成功率无从计算）',
  not_configured: '成功率未配置',
}

/** 状态单元格：`StatusTag` 只接受受控枚举（`AGENT_STATUS_TONE`），不接受颜色值。 */
export function StatusCell({ row }: { row: RegistryRow }) {
  return <StatusTag tone={AGENT_STATUS_TONE[row.status]}>{AGENT_STATUS_LABEL[row.status]}</StatusTag>
}

/** 使用统计单元格：就绪才给数字；否则只给受控枚举标签 + 说明。 */
export function UsageCell({ usage }: { usage: AgentUsageStats }) {
  const presence = usagePresence(usage)

  if (presence !== 'ready') {
    return (
      <Space size={tokens.spacing.sm}>
        <StatusTag presence={presence} />
        <Typography.Text type="secondary">{PRESENCE_EXPLAIN[presence]}</Typography.Text>
      </Space>
    )
  }

  // `usagePresence` 判为 ready ⇒ 两字段必非空；这里显式收窄类型（防御性空返回，绝不渲染数字）。
  if (usage.run_count === null || usage.success_rate === null) return null

  return <Typography.Text>{`${usage.run_count} 次 · 成功率 ${formatPercent(usage.success_rate)}`}</Typography.Text>
}

/** 最近使用单元格：无运行记录 ⇒ "未验证 + 暂无运行记录"（不显示 0、不显示成功态）。 */
export function LastRunCell({ row }: { row: RegistrySharedFields }) {
  if (row.last_run_at === null) {
    return (
      <Space size={tokens.spacing.sm}>
        <StatusTag presence={lastRunPresence(row)} />
        <Typography.Text type="secondary">暂无运行记录</Typography.Text>
      </Space>
    )
  }
  return <Typography.Text>{formatDateTime(row.last_run_at)}</Typography.Text>
}