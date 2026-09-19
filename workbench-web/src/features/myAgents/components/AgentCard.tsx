/**
 * 数字员工卡片（**非表格**：PRD 明确要求卡片式列表）。
 *
 * - 头像用 AntD `Avatar` 的首字母，**不引用任何图片文件**；
 * - 能力标签（Skill 数 / 知识范围 / 自治档）全部取自岗位模板（继承而来）；
 * - 状态保真：无运行记录显示「暂无运行记录 / 未验证」，**不显示 0、不显示成功态**；
 * - 权限呈现：不可管理的卡片**不隐藏操作**，而是禁用 + 给出原因。
 */
import { Avatar, Button, Space, Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { StatusTag } from '../../../components'
import { formatDateTime } from '../../../utils/format'
import { tokens } from '../../../theme/tokens'
import type { AgentItem, AgentStatus } from '../types'
import { runsPresence } from '../types'
import { AUTONOMY_LABEL } from './CapabilityPack'

/** 目录状态中文名：这是**已配置的目录状态**（后端 `status`），不是数据结论，故可用语义色。 */
const STATUS_LABEL: Record<AgentStatus, string> = { active: '已启用', disabled: '已停用' }

/** 归属中文名。 */
const OWNERSHIP_LABEL: Record<AgentItem['ownership'], string> = { mine: '我创建的', shared: '共享给我的' }

export interface AgentCardProps {
  agent: AgentItem
  /** 是否可管理（配置 / 停用）。由归属 + 能力决定，卡片只负责呈现。 */
  manageable: boolean
  /** 不可管理时的原因（必须可见，不允许静默隐藏入口）。 */
  manageDeniedReason?: string
  onStartTask?: (agent: AgentItem) => void
  onOpenDetail?: (agent: AgentItem) => void
  onConfigure?: (agent: AgentItem) => void
  onRequestDisable?: (agent: AgentItem) => void
}

export function AgentCard({
  agent,
  manageable,
  manageDeniedReason,
  onStartTask,
  onOpenDetail,
  onConfigure,
  onRequestDisable,
}: AgentCardProps) {
  const { template } = agent

  return (
    <ProCard bordered>
      <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
        <Space size={tokens.spacing.md} align="center">
          <Avatar size="large">{agent.name.slice(0, 1)}</Avatar>
          <Space direction="vertical" size={tokens.spacing.sm}>
            <Typography.Text strong>{agent.name}</Typography.Text>
            <Space size={tokens.spacing.sm}>
              <StatusTag tone={agent.status === 'active' ? 'success' : 'neutral'}>
                {STATUS_LABEL[agent.status]}
              </StatusTag>
              <StatusTag tone={agent.ownership === 'mine' ? 'info' : 'neutral'}>
                {OWNERSHIP_LABEL[agent.ownership]}
              </StatusTag>
            </Space>
          </Space>
        </Space>

        <Typography.Text type="secondary">
          所属岗位：{template.name}（{agent.role_key}）
        </Typography.Text>

        {/* 能力标签：全部来自岗位模板（继承），不是卡片里写死的 */}
        <Space size={tokens.spacing.sm} wrap>
          <StatusTag tone="info">Skill {template.skills.length} 个</StatusTag>
          <StatusTag tone="info">知识范围 {template.knowledge_scopes.length} 个</StatusTag>
          <StatusTag tone="neutral">自治档：{AUTONOMY_LABEL[template.autonomy_level]}</StatusTag>
        </Space>

        {/* 状态保真：没有运行记录就如实说"暂无 / 未验证"，不给 0、不给成功态 */}
        {agent.last_run_at === null ? (
          <Space size={tokens.spacing.sm}>
            <StatusTag presence={runsPresence(agent)} />
            <Typography.Text type="secondary">暂无运行记录</Typography.Text>
          </Space>
        ) : (
          <Typography.Text type="secondary">最近使用：{formatDateTime(agent.last_run_at)}</Typography.Text>
        )}

        <Space size={tokens.spacing.sm} wrap>
          <Button size="small" type="primary" onClick={() => onStartTask?.(agent)}>
            发起任务
          </Button>
          <Button size="small" onClick={() => onOpenDetail?.(agent)}>
            查看详情
          </Button>
          <Button size="small" disabled={!manageable} onClick={() => onConfigure?.(agent)}>
            配置
          </Button>
          <Button size="small" danger disabled={!manageable} onClick={() => onRequestDisable?.(agent)}>
            停用
          </Button>
        </Space>

        {!manageable && manageDeniedReason && (
          <Typography.Text type="secondary">{manageDeniedReason}</Typography.Text>
        )}
      </Space>
    </ProCard>
  )
}