import { Icon } from '../../components/Icon'
import { approvalStatusLabel, type RunApproval } from '../runDetail/types'

/**
 * 审批卡（**三处共用**：对话消息流 / 右侧舞台 / 运行详情）。
 *
 * 三处同源：数据都来自 `GET /runs/{run_id}/approvals`（服务端权威态），
 * 决议都走同一端点；按钮隐藏 ≠ 权限（服务端仍会 403）。
 *
 * 两种形态：
 *  * `compact`（已决议）：一条窄卡，只报「已通过 / 已驳回」，避免压在消息流里；
 *  * 默认（待审批）：完整卡（要执行 / 步骤 / 审批号 + 决议按钮）。
 */
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
  const stateClass = approval.status === 'approved' ? 'badge--ok' : approval.status === 'rejected' ? 'badge--err' : 'badge--warn'
  const title = approval.tool ?? approval.step_id ?? approval.approval_id

  const head = (
    <div className="approval-card__head">
      <Icon name={pending ? 'help' : 'check'} size={14} />
      {pending ? `需要你的审批：${title}` : title}
      <span className={`badge ${stateClass}`}>{approvalStatusLabel(approval.status)}</span>
    </div>
  )

  if (compact || !pending) {
    return (
      <article className="approval-card approval-card--done" aria-label="审批项（已处理）">
        {head}
      </article>
    )
  }

  return (
    <article className="approval-card" aria-label="审批项">
      {head}
      <div className="approval-card__body">
        <dl className="approval-card__line">
          <dt>要执行</dt>
          <dd>{approval.tool ?? '—'}</dd>
        </dl>
        <dl className="approval-card__line">
          <dt>步骤</dt>
          <dd>{approval.step_id ?? '—'}</dd>
        </dl>
        <dl className="approval-card__line">
          <dt>审批号</dt>
          <dd>{approval.approval_id}</dd>
        </dl>
      </div>
      {canDecide ? (
        <div className="approval-card__actions">
          <button className="btn btn--primary" type="button" disabled={deciding} onClick={() => onDecide(true)}>
            {deciding ? '处理中…' : '同意并继续'}
          </button>
          <button className="btn btn--danger" type="button" disabled={deciding} onClick={() => onDecide(false)}>
            拒绝
          </button>
        </div>
      ) : (
        <p className="approval-card__hint">
          仅 CEO / 超级管理员可决议，且发起人不得自审——这里只读展示；决议入口由服务端权威判定（按钮藏起来不等于没权限）。
        </p>
      )}
    </article>
  )
}