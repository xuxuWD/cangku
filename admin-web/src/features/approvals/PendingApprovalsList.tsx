import { relativeTime } from '../../utils/time'
import { resolvePendingApprovalAction, type PendingApprovalDestinations } from './destinations'
import { pendingApprovalDetailText, pendingApprovalKindLabel, type PendingApprovalItem } from './types'

/**
 * 待办行（S5 共用渲染）：首页「等你拍板」与员工页横幅**用同一份**（同源、同数、同落点）。
 * 放在 `.rows` 容器里使用。
 */
export function PendingApprovalRows({
  items,
  destinations,
  max = 4,
}: {
  items: PendingApprovalItem[]
  destinations: PendingApprovalDestinations
  max?: number
}) {
  return (
    <>
      {items.slice(0, max).map((item) => {
        const action = resolvePendingApprovalAction(item, destinations)
        const detail = pendingApprovalDetailText(item)
        return (
          <div className="row" key={`${item.kind}-${item.target_id}-${item.created_at}`}>
            <span className="row__main">
              <span className="row__title">{item.title || pendingApprovalKindLabel(item.kind)}</span>
              <span className="row__sub">
                <span className="badge badge--warn">{pendingApprovalKindLabel(item.kind)}</span>
                {detail ? ` ${detail}` : ''}
              </span>
              {action.note && <span className="row__note">{action.note}</span>}
            </span>
            <span className="row__side">
              <span className="row__time">{relativeTime(item.created_at)}</span>
              {action.run && (
                <button className="btn btn--secondary btn--sm" type="button" onClick={action.run}>
                  {action.label}
                </button>
              )}
            </span>
          </div>
        )
      })}
    </>
  )
}