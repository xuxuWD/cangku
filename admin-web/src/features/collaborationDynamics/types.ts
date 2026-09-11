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

export const COLLABORATION_DYNAMIC_STATUS_LABELS: Record<CollaborationDynamic['status'], string> = {
  queued: '排队中',
  pending_approval: '等待审批',
  cancelled: '已取消',
}
