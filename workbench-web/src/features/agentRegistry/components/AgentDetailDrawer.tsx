/**
 * 详情抽屉（管理侧，**只读**）：基础信息 + 创建信息 + 使用统计 + 能力包。
 *
 * 只读态由组件库的 `FormDrawer readOnly` 提供（表单禁用、只留"关闭"、不做未保存确认）；
 * 能力包复用员工侧同一份 `CapabilityPack`（同一实体、同一岗位模板，不复制第二套渲染）。
 */
import { Descriptions, Form, Typography } from 'antd'
import { FormDrawer, StatusTag } from '../../../components'
import { CapabilityPack } from '../../myAgents/components/CapabilityPack'
import { formatDateTime } from '../../../utils/format'
import { tokens } from '../../../theme/tokens'
import type { RegistryRow } from '../types'
import { AGENT_STATUS_LABEL, AGENT_STATUS_TONE } from '../types'
import { LastRunCell, UsageCell } from './cells'

export interface AgentDetailDrawerProps {
  open: boolean
  agent: RegistryRow | null
  onClose: () => void
  width?: number
}

export function AgentDetailDrawer({ open, agent, onClose, width = 560 }: AgentDetailDrawerProps) {
  const [form] = Form.useForm()

  return (
    <FormDrawer
      open={open}
      title="数字员工详情（只读）"
      form={form}
      readOnly
      onClose={onClose}
      onSubmit={() => {}}
      width={width}
    >
      {agent && (
        <>
          <Descriptions
            size="small"
            column={1}
            bordered
            style={{ marginBottom: tokens.spacing.md }}
            items={[
              { key: 'agent_key', label: '员工标识', children: agent.agent_key },
              { key: 'name', label: '名称', children: agent.name },
              { key: 'description', label: '工作范围', children: agent.description },
              { key: 'role_key', label: '所属岗位', children: `${agent.template.name}（${agent.role_key}）` },
              { key: 'created_by', label: '创建者', children: agent.created_by },
              {
                key: 'status',
                label: '状态',
                children: (
                  <StatusTag tone={AGENT_STATUS_TONE[agent.status]}>{AGENT_STATUS_LABEL[agent.status]}</StatusTag>
                ),
              },
              { key: 'created_at', label: '创建时间', children: formatDateTime(agent.created_at) },
              {
                key: 'last_run_at',
                label: '最近使用',
                // 状态保真：没有运行记录就如实说明，不显示 0、不显示成功态
                children: <LastRunCell row={agent} />,
              },
              { key: 'usage', label: '使用统计', children: <UsageCell usage={agent.usage} /> },
            ]}
          />

          <Typography.Title level={4}>能力包</Typography.Title>
          <CapabilityPack template={agent.template} />
          <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.md }}>
            本抽屉为管理侧只读视图：能力包由所属岗位模板继承，改能力属"换岗 / 升级模板"，不在本页进行。
          </Typography.Paragraph>
        </>
      )}
    </FormDrawer>
  )
}