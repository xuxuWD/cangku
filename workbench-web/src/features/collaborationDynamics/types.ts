/**
 * 协同动态类型 —— 与服务端 `GET /api/v1/collaboration-dynamics` 契约一致。
 *
 * **来源**：由 `admin-web/src/features/collaborationDynamics/types.ts` 合并移植（字段逐字保留）。
 */
export type CollaborationDynamicStatus = 'queued' | 'pending_approval' | 'cancelled'

export interface CollaborationDynamic {
  event_id: string
  aggregate_id: string
  action: string
  title: string
  employee_key: string
  status: CollaborationDynamicStatus
  tenant_id: string
  project_id: string | null
  created_by: string
  occurred_at: string
}

/** 状态 → 中文标签（唯一来源；未知状态由 `dynamicStatusLabel` 兜底，不留空白标签）。 */
export const COLLABORATION_DYNAMIC_STATUS_LABELS: Record<CollaborationDynamicStatus, string> = {
  queued: '排队中',
  pending_approval: '等待审批',
  cancelled: '已取消',
}

export function dynamicStatusLabel(status: string): string {
  return COLLABORATION_DYNAMIC_STATUS_LABELS[status as CollaborationDynamicStatus] ?? '未知状态'
}

/** 状态 → 语义色枚举（`StatusTag` 的受控取值，不在调用处写颜色）。 */
export function dynamicStatusTone(status: string): 'info' | 'warning' | 'neutral' {
  if (status === 'pending_approval') return 'warning'
  if (status === 'queued') return 'info'
  return 'neutral'
}
