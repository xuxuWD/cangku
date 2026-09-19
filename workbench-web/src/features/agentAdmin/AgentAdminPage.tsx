// 待清理项（第 5 轮）：本占位页已被 features/agentRegistry（数字员工注册中心，AD-01）取代，
// 应用壳 PAGES 里的 `agent-admin` 已指向新模块，此处不再被引用；按清理纪律**留待下次统一清理**（未删除）。
import { ContentState } from '../../components/ContentState'

/** 数字员工管理（占位页，第 1 轮只搭壳，不接业务数据；已被 features/agentRegistry 取代）。 */
export function AgentAdminPage() {
  return <ContentState state="empty" description="「数字员工管理」尚未接入（第 5 轮实现）。" />
}