/**
 * 能力包（岗位模板继承来的 6 项）—— 创建预览与详情共用同一处渲染，避免两边各写一套。
 *
 * 6 项 = `role-templates.md` §1 能力包字段去掉「岗位键（选岗位就定了）」「使命（已在上方展示）」
 * 「org_ref（预留位，本期不填）」后的**继承字段**。
 * 硬提示：能力**自动继承自岗位，不可放大**（模板只授予、不放大）。
 */
import { Alert, Descriptions } from 'antd'
import type { AutonomyLevel, RoleTemplate } from '../types'
import { formatBudgetCents } from '../../../utils/format'
import { tokens } from '../../../theme/tokens'

/** 自治档中文名（逐字对齐 `role-templates.md` §3.5 表格括号里的中文注释）。 */
export const AUTONOMY_LABEL: Record<AutonomyLevel, string> = {
  approval_for_all: '谨慎',
  approval_for_risky: '平衡',
  full_auto: '全自动',
}

/** 预览 / 详情里的固定提示文案。 */
export const INHERIT_NOTICE = '能力自动继承自岗位，不可放大'

export interface CapabilityPackProps {
  template: RoleTemplate
}

export function CapabilityPack({ template }: CapabilityPackProps) {
  const items = [
    { key: 'skills', label: '默认 Skill', children: template.skills.join('、') },
    { key: 'tools', label: '工具 / MCP 面', children: template.tools.join('、') },
    { key: 'knowledge_scopes', label: '知识库范围', children: template.knowledge_scopes.join('、') },
    {
      key: 'memory_policy',
      label: '记忆策略',
      children: `scope 上限：${template.memory_policy.scope}；可写入：${template.memory_policy.write_categories.join('、')}`,
    },
    {
      key: 'autonomy_level',
      label: '自治档',
      children: `${AUTONOMY_LABEL[template.autonomy_level]}（${template.autonomy_level}）`,
    },
    { key: 'budget_cents', label: '单任务预算上限', children: formatBudgetCents(template.budget_cents) },
  ]

  return (
    <div>
      <Descriptions size="small" column={1} bordered items={items} />
      <Alert
        type="info"
        showIcon
        message={INHERIT_NOTICE}
        description="能力包与所选岗位模板逐字段相等；模板只授予、不放大，超出本人权限的能力会在服务端被裁掉。"
        style={{ marginTop: tokens.spacing.md }}
      />
    </div>
  )
}