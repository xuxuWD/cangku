import { useState } from 'react'
import {
  isConversationOwner,
  memberPermissionLabel,
  type ConversationMember,
  type MemberPermission,
} from '../conversation/types'
import { formatLocalTime } from '../../utils/time'

/**
 * 参与者与分享（P2c-6 §2.16 呈现层，纯展示 + 本地表单态）：
 * **参与者名单 + 最近活动时间**（＝会话 `updated_at`，**非实时在线态**）。
 *
 * 纪律：
 *  * 名单数据一律来自服务端（`GET .../members`），不在前端造名字；
 *  * 只有**发起人**（`is_owner` 且成员号＝当前账号）能增删成员——被分享者是只读视角；
 *  * 「已读内容不可撤回」必须如实告知（撤销只影响对方**新**的读取 / 发言请求）。
 */
export interface CollaborationPanelState {
  items: ConversationMember[]
  /** 服务端返回的**命中总数**（`> items.length` ⇒ 本页之外还有成员，如实告知，不谎报为全部）。 */
  total: number
  lastActivityAt: string | null
  loading: boolean
  error: string | null
  sharing: boolean
  onAdd: (memberId: string, permission: MemberPermission) => void
  onRemove: (memberId: string) => void
}

export function ParticipantPanel({ collaboration }: { collaboration: CollaborationPanelState }) {
  const [memberId, setMemberId] = useState('')
  const [permission, setPermission] = useState<MemberPermission>('read')
  const { items, total, lastActivityAt, loading, error, sharing, onAdd, onRemove } = collaboration
  const canShare = isConversationOwner(items)
  const owner = items.find((item) => item.is_owner)
  const knownTotal = Math.max(total, items.length)

  return (
    <section className="history-panel stage-panel" aria-label="参与者与分享">
      <div className="panel-header">
        <h2>参与者</h2>
        {/* 分页口径：只显示本页时如实标注「已显示前 N 人」（不静默截断）。 */}
        <span>{knownTotal} 人{items.length < knownTotal ? `（已显示前 ${items.length} 人）` : ''}</span>
      </div>
      <div className="panel-body">
        <div className="history-meta">
          <span>最近活动：{formatLocalTime(lastActivityAt ?? undefined)}</span>
        </div>
        <p className="stage-hint">
          参与者名单与「最近活动」都是非实时快照（不做实时在线态，也不做协同编辑）。
        </p>

        {loading && items.length === 0 && (
          <div className="loading-state" role="status"><span className="loading-dot" />正在加载参与者…</div>
        )}
        {error && (
          <div className="notice notice-error" role="alert">
            <div><strong>参与者加载失败</strong><p>{error}</p></div>
          </div>
        )}

        {items.map((item) => (
          <div className="history-row" key={item.member_id}>
            <div className="history-row-main">
              <strong>{item.display_name}</strong>
              <div className="history-meta">
                <span className={`status-badge ${item.is_owner ? 'status-reviewing' : 'status-active'}`}>
                  {memberPermissionLabel(item.permission)}
                </span>
                {item.role && <span className="ws-code">{item.role}</span>}
                {!item.is_owner && item.created_at && <span>加入于 {formatLocalTime(item.created_at)}</span>}
              </div>
            </div>
            {canShare && !item.is_owner && (
              <button
                className="text-action"
                type="button"
                disabled={sharing}
                aria-label={`撤销 ${item.display_name}`}
                onClick={() => onRemove(item.member_id)}
              >
                撤销
              </button>
            )}
          </div>
        ))}

        {canShare ? (
          <div className="ws-field">
            <label htmlFor="participant-member-id">成员账号</label>
            <input
              id="participant-member-id"
              type="text"
              value={memberId}
              maxLength={128}
              placeholder="输入对方账号 ID（本租户已审批账号）"
              onChange={(event) => setMemberId(event.target.value)}
            />
            <label htmlFor="participant-permission">成员权限</label>
            <select
              id="participant-permission"
              aria-label="成员权限"
              value={permission}
              onChange={(event) => setPermission(event.target.value as MemberPermission)}
            >
              <option value="read">仅查看（read）</option>
              <option value="write">可发言（write）</option>
            </select>
            <button
              className="button"
              type="button"
              disabled={sharing || memberId.trim().length === 0}
              onClick={() => onAdd(memberId.trim(), permission)}
            >
              添加成员
            </button>
            <small className="ws-field-hint">
              仅按账号 ID 点名（本租户、已审批、非客户管理员）；被分享者只能读，授予「可发言」后才能发言，
              且一律以其本人身份走既有权限与审批闸门。撤销后对方新的读取会被拒绝；已读内容不可撤回。
            </small>
          </div>
        ) : (
          <p className="stage-hint">
            你正在查看{owner ? `由 ${owner.display_name} 分享` : '他人分享'}的会话：只有发起人可以增删成员。
          </p>
        )}
      </div>
    </section>
  )
}