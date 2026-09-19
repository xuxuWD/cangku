/**
 * 指标区（5 张卡）：全部（含草稿）/ 已启用 / 已停用 / 草稿 / 最近 7 天有运行。
 *
 * 为什么把「草稿」单独成卡：样例里存在 `draft` 行（后端枚举尚未定义，见契约 §2），
 * 若只给「总数 / 启用 / 停用」，评审者会看到 `总数 ≠ 启用 + 停用` 而误读成"少统计了 1 个"。
 * 单独成卡后 **全部 = 启用 + 停用 + 草稿** 一眼可验证；总数卡的标签也写明"全部（含草稿）"。
 *
 * **状态保真（硬要求）**：运行口径拿不到数据时，最后一张卡必须显示「未验证」，
 * **不得显示 `0`**，也不得给出成功率（见 `docs/contracts/agent-registry-api.md` §5）。
 */
import { Col, Row } from 'antd'
import { ContentState, StatCard } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import type { RegistryStatsSummary } from '../types'
import { ranLast7dPresence } from '../types'

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

  return (
    <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
      {/* 5 张等宽自适应：宽屏一行排满，窄屏自动换行（5 不是 24 的整数因子，故用 flex 列） */}
      <Col flex="1 1 192px">
        <StatCard label="全部（含草稿）" value={stats.total} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        <StatCard label="已启用" value={stats.active} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        <StatCard label="已停用" value={stats.disabled} unit="个" />
      </Col>
      <Col flex="1 1 192px">
        <StatCard label="草稿" value={stats.draft} unit="个" />
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