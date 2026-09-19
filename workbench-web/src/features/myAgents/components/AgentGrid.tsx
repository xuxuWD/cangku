/**
 * 数字员工卡片网格：按归属分区（「我创建的」/「共享给我的」/「归属无法判定」）。
 *
 * 分区的意义不只是排版：非本人创建（或归属无法判定）的员工**不能**配置 / 停用，
 * 所以各块的可操作性不同 —— 卡片上禁用 + 给原因，而不是把入口藏起来。
 */
import { Col, Row, Typography } from 'antd'
import { CAPABILITY_LABEL, roleLabel, useSession } from '../../../app/session'
import { tokens } from '../../../theme/tokens'
import { OWNERSHIP_UNKNOWN_NOTE } from '../services/myAgentsService'
import type { AgentItem } from '../types'
import { AgentCard } from './AgentCard'

export interface AgentGridProps {
  /** 我创建的（可管理）。 */
  mine: AgentItem[]
  /** 他人创建、共享给我的（默认不可管理）。 */
  shared: AgentItem[]
  /** 归属**无法判定**的行（后端不下发当前用户标识，也没有共享实体）：按"他人创建"同口径处理。 */
  unknown?: AgentItem[]
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
  unknown = [],
  manageShared,
  onStartTask,
  onOpenDetail,
  onConfigure,
  onRequestDisable,
}: AgentGridProps) {
  const role = useSession((current) => current.role)

  /** 共享卡片能否管理：要么具备管理能力，否则一律禁用并说明原因。 */
  const sharedManageable = Boolean(manageShared)
  const deniedReason = `该员工由他人创建并共享给你；只有创建者或具备「${CAPABILITY_LABEL['agent.manage']}」能力的角色（当前角色：${roleLabel(role)}）可以配置或停用。`

  const renderCards = (agents: AgentItem[], section: 'mine' | 'shared' | 'unknown') => (
    <Row gutter={[tokens.spacing.md, tokens.spacing.lg]}>
      {agents.map((agent) => (
        <Col key={agent.agent_key} xs={24} md={12} xl={8}>
          <AgentCard
            agent={agent}
            manageable={section === 'mine' || sharedManageable}
            manageDeniedReason={
              section === 'mine'
                ? undefined
                : section === 'shared'
                  ? sharedManageable
                    ? undefined
                    : deniedReason
                  : sharedManageable
                    ? undefined
                    : OWNERSHIP_UNKNOWN_NOTE
            }
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

      {unknown.length > 0 && (
        <section style={{ marginTop: tokens.spacing.lg }}>
          <Typography.Title level={3}>归属无法判定（{unknown.length}）</Typography.Title>
          <Typography.Paragraph type="secondary">{OWNERSHIP_UNKNOWN_NOTE}</Typography.Paragraph>
          {renderCards(unknown, 'unknown')}
        </section>
      )}
    </div>
  )
}