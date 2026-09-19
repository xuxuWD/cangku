/**
 * 筛选栏：岗位 / 状态 / 创建者 / 名称搜索 + 查询 / 重置。
 *
 * 口径：条件**不在这里过滤**，而是**原样透传**给适配层（`onChange(next)` → 页面 → 服务端语义查询）；
 * 因此"看到的就是服务端返回的" —— 不存在前端过滤假象。
 * 采用"填条件 → 查询"一次提交的形态：一次带上全部参数调用同一个适配层函数，避免逐字段半成品查询。
 */
import { Button, Form, Input, Select, Space } from 'antd'
import { ContentState } from '../../../components'
import type { ContentStateKind } from '../../../components'
import { tokens } from '../../../theme/tokens'
import type { RoleTemplate } from '../../myAgents/types'
import type { RegistryAgentStatus, RegistryFilters } from '../types'

/** 状态选项（受控枚举，含后端未定义的 `draft` —— 见契约 §2）。 */
const STATUS_OPTIONS: { label: string; value: RegistryAgentStatus }[] = [
  { label: '已启用', value: 'active' },
  { label: '已停用', value: 'disabled' },
  { label: '草稿', value: 'draft' },
]

interface FilterFormValues {
  role_key?: string
  status?: RegistryAgentStatus
  created_by?: string
  keyword?: string
}

export interface RegistryFiltersProps {
  filters: RegistryFilters
  /** 岗位选项：复用项目级唯一的 6 个岗位模板（真源 `role-templates.md`）。 */
  templates: RoleTemplate[]
  onChange: (next: RegistryFilters) => void
  onReset: () => void
  /** 默认 `ready`；非 ready（如模板字典加载中）时整条筛选栏换成统一四态。 */
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

export function RegistryFilters({
  filters,
  templates,
  onChange,
  onReset,
  state = 'ready',
  stateDescription,
  onRetry,
}: RegistryFiltersProps) {
  const [form] = Form.useForm<FilterFormValues>()

  if (state !== 'ready') {
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
    <Form
      form={form}
      layout="inline"
      initialValues={filters}
      onFinish={(values: FilterFormValues) => {
        // 空字符串一律转成 undefined：避免把"没填"当成"筛选空串"发给服务端。
        onChange({
          role_key: (values.role_key as RegistryFilters['role_key']) || undefined,
          status: values.status || undefined,
          created_by: values.created_by?.trim() || undefined,
          keyword: values.keyword?.trim() || undefined,
        })
      }}
    >
      <Form.Item label="岗位" name="role_key">
        <Select
          allowClear
          placeholder="全部岗位"
          style={{ minWidth: 160 }}
          options={templates.map((template) => ({
            value: template.role_key,
            label: `${template.name}（${template.role_key}）`,
          }))}
        />
      </Form.Item>

      <Form.Item label="状态" name="status">
        <Select allowClear placeholder="全部状态" style={{ minWidth: 120 }} options={STATUS_OPTIONS} />
      </Form.Item>

      <Form.Item label="创建者" name="created_by">
        <Input placeholder="创建者标识（模糊）" allowClear />
      </Form.Item>

      <Form.Item label="名称" name="keyword">
        <Input placeholder="名称关键字（模糊）" allowClear />
      </Form.Item>

      <Form.Item>
        <Space size={tokens.spacing.sm}>
          <Button type="primary" htmlType="submit">
            查询
          </Button>
          <Button
            onClick={() => {
              form.resetFields()
              onReset()
            }}
          >
            重置
          </Button>
        </Space>
      </Form.Item>
    </Form>
  )
}