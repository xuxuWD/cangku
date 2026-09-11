import { useEffect, useState } from 'react'
import { ApiError, approveItem, rejectItem, SessionExpiredError } from './api'
import {
  APPROVABLE_ROLES,
  DEFAULT_APPROVAL_ROLE,
  ROLE_LABELS,
  type PendingApproval,
  type PendingApprovalCounts,
} from './types'
import { usePendingApprovals } from './usePendingApprovals'

export const KIND_LABELS: Record<PendingApproval['kind'], string> = {
  task_approval: '任务审批',
  plan_proposal: '计划提案',
  account_registration: '账号注册',
  run_approval: '运行审批',
}

interface ApprovalsPageProps {
  onSessionExpired?: () => void
  onCountsChange?: (counts: PendingApprovalCounts) => void
}

function keyOf(item: PendingApproval): string {
  return `${item.kind}:${item.target_id}`
}

function detailSummary(item: PendingApproval): string {
  const parts: string[] = []
  if (typeof item.detail.risk_level === 'string') parts.push(`风险：${item.detail.risk_level}`)
  if (typeof item.detail.employee_key === 'string') parts.push(`岗位：${item.detail.employee_key}`)
  if (typeof item.detail.step_count === 'number') parts.push(`步骤数：${item.detail.step_count}`)
  if (typeof item.detail.position === 'string') parts.push(`岗位：${item.detail.position}`)
  return parts.join(' · ')
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function ApprovalsPage({ onSessionExpired, onCountsChange }: ApprovalsPageProps) {
  const { items, counts, loading, error, refresh } = usePendingApprovals(onSessionExpired)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [rejectTarget, setRejectTarget] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  // 账号注册审批必须由审批人指定角色；未选择时用最小权限的默认值。
  const [roleChoice, setRoleChoice] = useState<Record<string, string>>({})

  useEffect(() => {
    onCountsChange?.(counts)
  }, [counts, onCountsChange])

  async function runAction(item: PendingApproval, action: () => Promise<unknown>, successText: string) {
    setBusyKey(keyOf(item))
    setNotice(null)
    try {
      await action()
      setNotice(successText)
      await refresh()
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        onSessionExpired?.()
        return
      }
      setNotice(err instanceof ApiError ? err.message : '操作失败，请稍后重试。')
    } finally {
      setBusyKey(null)
    }
  }

  function handleApprove(item: PendingApproval, role?: string) {
    void runAction(
      item,
      () => approveItem(item, role ? { role } : {}),
      `已通过：${item.title}`
    )
  }

  function handleConfirmReject(item: PendingApproval) {
    const trimmed = reason.trim()
    if (!trimmed) return
    void runAction(item, () => rejectItem(item, trimmed), `已驳回：${item.title}`).then(() => {
      setRejectTarget(null)
      setReason('')
    })
  }

  return (
    <section className="approvals">
      {notice ? (
        <p className="approvals__notice" role="status">
          {notice}
        </p>
      ) : null}

      {error ? (
        <div className="approvals__error" role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => void refresh()}>
            重试
          </button>
        </div>
      ) : null}

      {loading && items.length === 0 ? <p className="approvals__loading">加载中…</p> : null}
      {!loading && !error && items.length === 0 ? <p className="approvals__empty">暂无待办</p> : null}

      <ul className="approvals__list">
        {items.map((item) => {
          const itemKey = keyOf(item)
          const busy = busyKey === itemKey
          const rejectable = item.kind !== 'task_approval'
          const isRegistration = item.kind === 'account_registration'
          const selectedRole = roleChoice[itemKey] ?? DEFAULT_APPROVAL_ROLE
          const summary = detailSummary(item)
          return (
            <li key={itemKey} className="approval-card">
              <div className="approval-card__head">
                <span className="approval-card__kind">{KIND_LABELS[item.kind]}</span>
                <span className="approval-card__time">{formatTime(item.created_at)}</span>
              </div>
              <h2 className="approval-card__title">{item.title}</h2>
              <p className="approval-card__meta">请求人：{item.requested_by ?? '系统'}</p>
              {summary ? <p className="approval-card__detail">{summary}</p> : null}
              {isRegistration ? (
                <div className="approval-card__role">
                  <label htmlFor={`role-${itemKey}`}>分配角色</label>
                  <select
                    id={`role-${itemKey}`}
                    value={selectedRole}
                    disabled={busy}
                    onChange={(event) =>
                      setRoleChoice((prev) => ({ ...prev, [itemKey]: event.target.value }))
                    }
                  >
                    {APPROVABLE_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABELS[role]}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <div className="approval-card__actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleApprove(item, isRegistration ? selectedRole : undefined)}
                >
                  通过
                </button>
                {rejectable ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setRejectTarget(itemKey)
                      setReason('')
                    }}
                  >
                    驳回
                  </button>
                ) : null}
              </div>
              {rejectTarget === itemKey ? (
                <div className="approval-card__reject">
                  <label htmlFor={`reason-${itemKey}`}>驳回原因</label>
                  <input
                    id={`reason-${itemKey}`}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                  <button type="button" disabled={busy || reason.trim() === ''} onClick={() => handleConfirmReject(item)}>
                    确认驳回
                  </button>
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
