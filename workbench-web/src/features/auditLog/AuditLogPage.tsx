import { ContentState } from '../../components/ContentState'

/** 审计日志（占位页，第 1 轮只搭壳，不接业务数据）。 */
export function AuditLogPage() {
  return <ContentState state="empty" description="「审计日志」尚未接入（第 6 轮实现）。" />
}