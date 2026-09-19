/**
 * 「治理指标」块（**只读**）：四数 + 新鲜度比率。
 *
 * 口径（契约 §1 实测）：
 *  - `freshness_ratio = published / total`，**分母含 draft 与 archived** ⇒ 界面必须如实写明，
 *    否则读者会把 33.3% 误读成"发布成功率只有三分之一"；
 *  - 指标全为 0 时**照实显示 0**（这是真实值），但要说清原因（`METRICS_ZERO_NOTE`），
 *    不用"没有数据"式含糊文案。
 */
import { Col, Row, Typography } from 'antd'
import { ContentState, StatCard } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatPercent } from '../../../utils/format'
import { METRICS_ZERO_NOTE } from '../services/knowledgeService'
import type { GovernanceMetrics } from '../types'

export interface MetricsPanelProps {
  metrics: GovernanceMetrics
  state: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

/** 指标口径的唯一说明文案（界面必须显示）。 */
export const FRESHNESS_NOTE = '新鲜度比率 = 已发布 ÷ 已登记总数（分母为全部已登记文档，含草稿与已归档）。'

export function MetricsPanel({ metrics, state, stateDescription, onRetry }: MetricsPanelProps) {
  const title = <Typography.Title level={3}>治理指标</Typography.Title>

  if (state !== 'ready') {
    return (
      <div>
        {title}
        <ContentState
          state={state}
          description={state === 'loading' ? undefined : stateDescription}
          onRetry={onRetry}
          boxed={false}
        />
      </div>
    )
  }

  return (
    <div>
      {title}
      <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
        <Col flex="1 1 176px">
          <StatCard label="已发布" value={metrics.published} unit="篇" />
        </Col>
        <Col flex="1 1 176px">
          <StatCard label="待复核" value={metrics.needs_review} unit="篇" />
        </Col>
        <Col flex="1 1 176px">
          <StatCard label="已归档" value={metrics.archived} unit="篇" />
        </Col>
        <Col flex="1 1 176px">
          <StatCard label="已登记总数" value={metrics.total} unit="篇" />
        </Col>
        <Col flex="1 1 176px">
          <StatCard label="新鲜度比率" value={formatPercent(metrics.freshness_ratio)} />
        </Col>
      </Row>
      <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.sm, marginBottom: 0 }}>
        {FRESHNESS_NOTE}
        {metrics.total === 0 ? ` ${METRICS_ZERO_NOTE}` : ''}
      </Typography.Paragraph>
    </div>
  )
}