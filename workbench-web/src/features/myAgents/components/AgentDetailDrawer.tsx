/**
 * 数字员工详情抽屉。
 *
 * - `mode = 'view'`：**只读态**（`FormDrawer readOnly`），用于「查看详情」；
 * - `mode = 'edit'`：用于「配置」，可改名称与工作范围（`agent_key` 与能力包不可改 ——
 *   能力由岗位模板继承，改能力属"换岗 / 升级模板"，本轮不做）。
 */
import { useEffect } from 'react'
import { Descriptions, Form, Input, Space, Typography } from 'antd'
import { FormDrawer, StatusTag } from '../../../components'
import { formatDateTime } from '../../../utils/format'
import { tokens } from '../../../theme/tokens'
import type { AgentItem, UpdateAgentInput } from '../types'
import { runsPresence } from '../types'
import { AUTONOMY_LABEL, CapabilityPack } from './CapabilityPack'

export interface AgentDetailDrawerProps {
  open: boolean
  agent: AgentItem | null
  mode?: 'view' | 'edit'
  onClose: () => void
  /** `mode = 'edit'` 时生效。 */
  onSubmit?: (input: UpdateAgentInput) => void | Promise<void>
}

interface DetailFormValues {
  name?: string
  description?: string
}

export function AgentDetailDrawer({ open, agent, mode = 'view', onClose, onSubmit }: AgentDetailDrawerProps) {
  const [form] = Form.useForm<DetailFormValues>()
  const readOnly = mode === 'view'

  // 打开（或换员工）时回填表单：只在抽屉可见时写值，避免表单未挂载时的无效调用。
  useEffect(() => {
    if (open && agent) form.setFieldsValue({ name: agent.name, description: agent.description })
  }, [open, agent, form])

  const handleSubmit = async () => {
    if (!agent || readOnly) return
    const values = form.getFieldsValue()
    await onSubmit?.({
      agent_key: agent.agent_key,
      name: values.name ?? agent.name,
      description: values.description ?? agent.description,
    })
  }

  return (
    <FormDrawer
      open={open}
      title={readOnly ? '数字员工详情（只读）' : '配置数字员工'}
      form={form}
      readOnly={readOnly}
      onClose={onClose}
      onSubmit={handleSubmit}
      submitText="保存"
      width={560}
    >
      {agent && (
        <>
          <Descriptions
            size="small"
            column={1}
            bordered
            style={{ marginBottom: tokens.spacing.md }}
            items={[
              { key: 'agent_key', label: '标识', children: agent.agent_key },
              {
                key: 'role_key',
                label: '所属岗位',
                children: agent.template
                  ? `${agent.template.name}（${agent.role_key}）`
                  : `${agent.role_key}（模板未接入）`,
              },
              {
                key: 'status',
                label: '状态',
                children: (
                  <StatusTag tone={agent.status === 'active' ? 'success' : 'neutral'}>
                    {agent.status === 'active' ? '已启用' : '已停用'}
                  </StatusTag>
                ),
              },
              {
                key: 'ownership',
                label: '归属',
                children:
                  agent.ownership === 'mine'
                    ? '我创建的'
                    : agent.ownership === 'shared'
                      ? '共享给我的（他人创建）'
                      : '归属未判定（后端未下发当前用户标识，也没有「共享」实体）',
              },
              {
                key: 'created_at',
                label: '创建时间',
                // 后端视图模型允许为空：为空时如实写"未提供"，**不编造时间**
                children: agent.created_at ? formatDateTime(agent.created_at) : '未提供',
              },
              {
                key: 'last_run_at',
                label: '最近使用',
                // 状态保真：没有运行记录就如实说明，不显示 0、不显示成功态
                children:
                  agent.last_run_at === null ? (
                    <Space size={tokens.spacing.sm}>
                      <StatusTag presence={runsPresence(agent)} />
                      <Typography.Text type="secondary">暂无运行记录</Typography.Text>
                    </Space>
                  ) : (
                    formatDateTime(agent.last_run_at)
                  ),
              },
            ]}
          />

          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="工作范围" rules={[{ required: true, message: '请填写工作范围' }]}>
            <Input.TextArea rows={3} />
          </Form.Item>

          <Typography.Title level={4}>能力包</Typography.Title>
          {agent.template ? (
            <>
              <CapabilityPack template={agent.template} />
              <Typography.Paragraph type="secondary" style={{ marginTop: tokens.spacing.md }}>
                自治档：{AUTONOMY_LABEL[agent.template.autonomy_level]}；能力包按所属岗位从项目级目录
                （role-templates.md）解析，后端未下发模板字段，本页不可直接编辑。
              </Typography.Paragraph>
            </>
          ) : (
            <Typography.Paragraph type="secondary">
              能力包未接入：该岗位键不在项目级目录里，后端也不下发岗位模板，本批不展示能力包，也不以样例模板冒充。
            </Typography.Paragraph>
          )}
        </>
      )}
    </FormDrawer>
  )
}