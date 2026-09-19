/**
 * 指标区（5 张卡）：全部 / 已启用 / 已停用 / 草稿 / 最近 7 天有运行。
 *
 * 为什么把「草稿」单独成卡：样例里存在 `draft` 行，若只给「总数 / 启用 / 停用」，
 * 评审者会看到 `总数 ≠ 启用 + 停用` 而误读成"少统计了 1 个"。单独成卡后一眼可验证。
 * **后端没有 `draft` 枚举** ⇒ http 模式下 `draft = null`，该卡显示「未验证」且总数卡标签改为「全部」
 * （不写"含草稿"，也不写 `0` —— `0` 会被读成"确实没有草稿"，而事实是"后端没有这个概念"）。
 *
 * **状态保真（硬要求）**：口径拿不到数据时如实显示「未验证」，**不得显示 `0`**，也不得给出成功率。
 */
import { Col, Row } from 'antd'
import { ContentState, StatCard } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import type { RegistryStatsSummary } from '../types'
import { draftPresence, ranLast7dPresence } from '../types'

export interface RegistryStatsProps {
  stats: RegistryStatsSummary
  /** 默认 `ready`；非 ready 时整个指标区换成统一四态。 */
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

export function RegistryStats({ stats, state = 'ready', stateDescription, onRetry }: RegistryStatsProps) {
  if (state !== 'ready') {
    // 加载中一律用统一加载文案，绝不把失败说明用在加载态上。
    return (
      <ContentState
        state={state}
        description={state === 'loading' ? undefined : stateDescription}
        onRetry={onRetry}
        boxed={false}
      />
    )
  }

  const draftReady = draftPresence(stats) === 'ready'

  return (
    <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
      {/* 5 张等宽自适应：宽屏一行排满，窄屏自动换行（5 不是 24 的整数因子，故用 flex 列） */}
      <Col flex="1 1 192px">
        <StatCard label={draftReady ? '全部（含草稿）' : '全部'} value={stats.total} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        <StatCard label="已启用" value={stats.active} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        <StatCard label="已停用" value={stats.disabled} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        {/* 草稿口径：后端无该枚举时如实显示"未验证"（StatCard 会隐藏数值与单位） */}
        <StatCard
          label="草稿"
          value={stats.draft ?? undefined}
          unit="个"
          presence={draftPresence(stats)}
        />
      </Col>
      <Col flex="1 1 192px">
        {/* 运行口径：拿不到数据就如实显示"未验证"（StatCard 会隐藏数值与单位） */}
        <StatCard
          label="最近 7 天有运行"
          value={stats.ran_last_7d ?? undefined}
          unit="个"
          presence={ranLast7dPresence(stats)}
        />
      </Col>
    </Row>
  )
}