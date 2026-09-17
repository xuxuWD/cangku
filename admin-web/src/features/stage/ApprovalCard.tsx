import { approvalStatusLabel, type RunApproval } from '../runDetail/types'

/**
 * 审批卡（内联于对话流，也用于舞台审批面板）。
 * 三条判据（P2c-1 §2.5）：决议入口唯一（既有 run 审批接口）、无本地乐观更新（服务端回流）、
 * 卡类型由结构字段判定。**按钮隐藏 ≠ 权限**：服务端仍会 403。
 */
export function ApprovalCard({
  approval,
  canDecide,
  deciding,
  onDecide,
}: {
  approval: RunApproval
  canDecide: boolean
  deciding: boolean
  onDecide: (approved: boolean) => void
}) {
  const pending = approval.status === 'pending'
  return (
    <article className="approval-card" aria-label="审批项">
      <div className="approval-card__head">
        <strong>{approval.tool ?? approval.step_id ?? approval.approval_id}</strong>
        <span className={`status-badge status-${approval.status}`}>{approvalStatusLabel(approval.status)}</span>
      </div>
      <div className="approval-card__meta">
        <span className="ws-code">{approval.approval_id}</span>
        {approval.step_id && <span>步骤 {approval.step_id}</span>}
        {approval.tool && <span>工具 {approval.tool}</span>}
      </div>
      {pending && canDecide && (
        <div className="approval-card__actions">
          <button className="button primary" type="button" disabled={deciding} onClick={() => onDecide(true)}>
            通过
          </button>
          <button className="button" type="button" disabled={deciding} onClick={() => onDecide(false)}>
            驳回
          </button>
        </div>
      )}
      {pending && !canDecide && (
        <p className="approval-card__hint">
          仅 CEO / 超级管理员可决议，且发起人不得自审——这里只读展示，服务端同样是权威。
        </p>
      )}
    </article>
  )
}