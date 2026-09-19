/**
 * 从岗位模板创建数字员工（DE-01）。
 *
 * 三步：① 选岗位（6 个模板，来自 `role-templates.md`）② **继承能力预览**（6 项，逐项来自所选模板对象）
 * ③ 填名称与工作范围 → 提交。
 * 预览处必须写明「能力自动继承自岗位，不可放大」（由 `CapabilityPack` 给出固定提示）。
 *
 * 说明：「工作范围」→ 请求字段 `description`（沿用后端既有字段名，见契约 §3）。
 */
import { Form, Input, Select } from 'antd'
import { FormDrawer } from '../../../components'
import type { ContentStateKind } from '../../../components'
import type { CreateAgentInput, RoleKey, RoleTemplate } from '../types'
import { CapabilityPack } from './CapabilityPack'

export interface CreateAgentDrawerProps {
  open: boolean
  /** 岗位模板列表（本轮为样例数据；加载态由 `state` 表达）。 */
  templates: RoleTemplate[]
  onClose: () => void
  /** 提交回调（校验通过后调用；收到的就是表单里的名称与模板键）。 */
  onSubmit: (input: CreateAgentInput) => void | Promise<void>
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

interface CreateFormValues {
  role_key?: RoleKey
  name?: string
  description?: string
}

export function CreateAgentDrawer({
  open,
  templates,
  onClose,
  onSubmit,
  state = 'ready',
  stateDescription,
  onRetry,
}: CreateAgentDrawerProps) {
  const [form] = Form.useForm<CreateFormValues>()
  // 预览与"未保存改动"都读表单当前值，避免另存一份状态导致两份真相。
  const roleKey = Form.useWatch('role_key', form)
  const name = Form.useWatch('name', form)
  const description = Form.useWatch('description', form)
  const picked: RoleTemplate | undefined = templates.find((template) => template.role_key === roleKey)

  const handleClose = () => {
    form.resetFields()
    onClose()
  }

  const handleSubmit = () => {
    const values = form.getFieldsValue()
    // 必填校验已由 FormDrawer 先行完成，这里只是收窄类型。
    if (!values.role_key || !values.name) return
    return onSubmit({ name: values.name, role_key: values.role_key, description: values.description ?? '' })
  }

  return (
    <FormDrawer
      open={open}
      title="从岗位模板创建数字员工"
      form={form}
      dirty={Boolean(roleKey || name || description)}
      onClose={handleClose}
      onSubmit={handleSubmit}
      submitText="创建"
      state={state}
      stateDescription={stateDescription}
      onRetry={onRetry}
      width={560}
    >
      <Form.Item
        name="role_key"
        label="岗位模板"
        rules={[{ required: true, message: '请选择岗位模板' }]}
        extra={picked ? picked.mission : '选岗位即自动继承该岗位的能力包（Skill / 工具面 / 知识库范围 / 自治档 / 预算）。'}
      >
        <Select
          placeholder="请选择岗位模板"
          options={templates.map((template) => ({
            value: template.role_key,
            label: `${template.name}（${template.role_key}）`,
          }))}
        />
      </Form.Item>

      <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
        <Input placeholder="例如：内容运营助手" />
      </Form.Item>

      <Form.Item name="description" label="工作范围" rules={[{ required: true, message: '请填写工作范围' }]}>
        <Input.TextArea rows={3} placeholder="例如：负责选题、草稿与发布前准备。" />
      </Form.Item>

      {picked && <CapabilityPack template={picked} />}
    </FormDrawer>
  )
}