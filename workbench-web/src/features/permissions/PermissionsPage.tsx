import { ContentState } from '../../components/ContentState'

/** 权限配置（占位页，第 1 轮只搭壳，不接业务数据）。 */
export function PermissionsPage() {
  return <ContentState state="empty" description="「权限配置」尚未接入（第 5 轮实现）。" />
}