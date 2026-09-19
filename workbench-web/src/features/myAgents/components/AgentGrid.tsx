/**
 * 数字员工卡片网格：按归属分区（「我创建的」/「共享给我的」）。
 *
 * 分区的意义不只是排版：共享给我的员工**不能**配置 / 停用，
 * 所以两块的可操作性不同 —— 卡片上禁用 + 给原因，而不是把入口藏起来。
 */
import { Col, Row, Typography } from 'antd'
import { CAPABILITY_LABEL, ROLE_LABEL, useSession } from '../../../app/session'
import { tokens } from '../../../theme/tokens'
import type { AgentItem } from '../types'
import { AgentCard } from './AgentCard'

export interface AgentGridProps {
  /** 我创建的（可管理）。 */
  mine: AgentItem[]
  /** 他人创建、共享给我的（默认不可管理）。 */
  shared: AgentItem[]
  /** 是否是"仅我创建的"视图之外还能管理他人员工的角色（具备 `agent.manage`）。 */
  manageShared?: boolean
  onStartTask?: (agent: AgentItem) => void
  onOpenDetail?: (agent: AgentItem) => void
  onConfigure?: (agent: AgentItem) => void
  onRequestDisable?: (agent: AgentItem) => void
}

export function AgentGrid({
  mine,
  shared,
  manageShared,
  onStartTask,
  onOpenDetail,
  onConfigure,
  onRequestDisable,
}: AgentGridProps) {
  const role = useSession((current) => current.role)

  /** 共享卡片能否管理：要么具备管理能力，否则一律禁用并说明原因。 */
  const sharedManageable = Boolean(manageShared)
  const deniedReason = `该员工由他人创建并共享给你；只有创建者或具备「${CAPABILITY_LABEL['agent.manage']}」能力的角色（当前角色：${ROLE_LABEL[role]}）可以配置或停用。`

  const renderCards = (agents: AgentItem[], section: 'mine' | 'shared') => (
    <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
      {agents.map((agent) => (
        <Col key={agent.agent_key} xs={24} md={12} xl={8}>
          <AgentCard
            agent={agent}
            manageable={section === 'mine' || sharedManageable}
            manageDeniedReason={section === 'shared' && !sharedManageable ? deniedReason : undefined}
            onStartTask={onStartTask}
            onOpenDetail={onOpenDetail}
            onConfigure={onConfigure}
            onRequestDisable={onRequestDisable}
          />
        </Col>
      ))}
    </Row>
  )

  return (
    <div>
      {mine.length > 0 && (
        <section>
          <Typography.Title level={3}>我创建的（{mine.length}）</Typography.Title>
          {renderCards(mine, 'mine')}
        </section>
      )}

      {shared.length > 0 && (
        <section style={{ marginTop: tokens.spacing.lg }}>
          <Typography.Title level={3}>共享给我的（{shared.length}）</Typography.Title>
          {renderCards(shared, 'shared')}
        </section>
      )}
    </div>
  )
}