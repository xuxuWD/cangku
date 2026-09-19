/**
 * 日程面板：**固定渲染"尚未接入"**。
 *
 * 后端**没有日程 / 日历实体**（接口未定义，见 `docs/contracts/my-workbench-api.md` §3），
 * 因此本块**严禁造任何日程数据** —— 不渲染日期、会议、时间条目，也不接受"日程条目数组"。
 * `ScheduleAvailability.backend_entity` 被定死为 `'absent'`，从类型上就塞不进条目。
 *
 * props 保留 `state` / `onRetry`：后续后端落地日程实体时，只需新增 `items` 并把 state 切到 `ready`，
 * 本组件与页面的结构不用重写。
 */
import { EmptyState } from '../../../components'
import type { ContentStateKind } from '../../../components'
import type { ScheduleAvailability } from '../types'
import { PanelCard } from './PanelCard'

export interface SchedulePanelProps {
  /** 后端实体可用性：本轮固定"无实体"。 */
  availability: ScheduleAvailability
  state?: ContentStateKind | 'ready'
  stateDescription?: string
  onRetry?: () => void
}

export function SchedulePanel({ availability, state = 'ready', stateDescription, onRetry }: SchedulePanelProps) {
  return (
    <PanelCard title="日程" state={state} stateDescription={stateDescription} onRetry={onRetry}>
      <EmptyState boxed={false} description={availability.note} />
    </PanelCard>
  )
}