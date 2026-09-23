/**
 * 审批卡（**三处共用**：对话消息流 / 舞台 / 运行详情）。
 *
 * **来源**：由 `admin-web/src/features/stage/ApprovalCard.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS（12 处 className）+ admin-web 自有的 `Icon` 组件，
 * 换成 **AntD `Button` / `Descriptions` / `StatusTag` + `@ant-design/icons`**，符合 ADR-0003。
 *
 * **三处同源**：数据都来自 `GET /runs/{run_id}/approvals`（服务端权威态），决议走同一端点；
 * **按钮隐藏 ≠ 权限** —— 服务端仍会 `403` 兜底。
 *
 * 两种形态：
 *  * `compact`（或已决议）：一条窄卡，只报「已通过 / 已驳回」，避免压在消息流里；
 *  * 默认（待审批）：完整卡（要执行 / 步骤 / 审批号 + 决议按钮）。
 */
import { Button, Descriptions, Space, Typography } from 'antd'
import { CheckCircleOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { StatusTag } from '../../components'
import { approvalStatusLabel } from '../runDetail/types'
import type { RunApproval } from '../runDetail/types'

/** 审批状态 → 语义色（受控枚举，不在调用处写颜色）。 */
function approvalTone(status: string): 'success' | 'danger' | 'warning' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  return 'warning'
}

const NOT_DECIDABLE_HINT =
  '仅 CEO / 超级管理员可决议，且发起人不得自审——这里只读展示；决议入口由服务端权威判定（按钮藏起来不等于没权限）。'

export function ApprovalCard({
  approval,
  canDecide,
  deciding,
  onDecide,
  compact = false,
}: {
  approval: RunApproval
  canDecide: boolean
  deciding: boolean
  onDecide: (approved: boolean) => void
  compact?: boolean
}) {
  const pending = approval.status === 'pending'
  const title = approval.tool ?? approval.step_id ?? approval.approval_id

  const head = (
    <Space wrap size="small">
      {pending ? <QuestionCircleOutlined /> : <CheckCircleOutlined />}
      <Typography.Text>{pending ? `需要你的审批：${title}` : title}</Typography.Text>
      <StatusTag tone={approvalTone(approval.status)}>{approvalStatusLabel(approval.status)}</StatusTag>
    </Space>
  )

  if (compact || !pending) {
    return <article aria-label="审批项（已处理）">{head}</article>
  }

  return (
    <article aria-label="审批项">
      {head}
      <Descriptions
        column={1}
        size="small"
        items={[
          { key: 'tool', label: '要执行', children: approval.tool ?? '—' },
          { key: 'step', label: '步骤', children: approval.step_id ?? '—' },
          { key: 'id', label: '审批号', children: approval.approval_id },
        ]}
      />
      {canDecide ? (
        <Space>
          <Button type="primary" disabled={deciding} onClick={() => onDecide(true)}>
            {deciding ? '处理中…' : '同意并继续'}
          </Button>
          <Button danger disabled={deciding} onClick={() => onDecide(false)}>
            拒绝
          </Button>
        </Space>
      ) : (
        <Typography.Text type="secondary">{NOT_DECIDABLE_HINT}</Typography.Text>
      )}
    </article>
  )
}
