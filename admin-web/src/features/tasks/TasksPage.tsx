import type { AppView } from '../../app/AppShell'
import { Segmented } from '../../components/ui/Segmented'
import { ContentHistoryPage } from '../contentHistory/ContentHistoryPage'
import { ContentWorkbenchPage } from '../contentWorkbench/ContentWorkbenchPage'

/** 任务视图的两个页签（URL 口径：`?view=workbench` = 任务；`?view=workbench&tab=history` = 历史草稿）。 */
export type TasksTab = 'tasks' | 'history'

/**
 * 任务（UI v2 §3.2：`workbench` + `history` **两页签合并**——同一件事不再两个入口）。
 *
 * 纪律：
 *  * 页签状态**由 URL 决定**（可深链、可后退），本组件不私存状态；
 *  * 老深链 `?view=history` 保留为别名（App 的 `routeFromLocation` 映射到本页的 history 页签），
 *    批 1 的深链契约（G-01/02/03）不得破坏；
 *  * 带着具体草稿（`?task=<id>`）进来时一律落在「任务」页签（要打开的就是那条草稿）。
 */
export function TasksPage({
  taskId,
  tab = 'tasks',
  onChangeTab,
  onOpenTask,
  onNavigate,
}: {
  taskId?: string
  tab?: TasksTab
  onChangeTab?: (tab: TasksTab) => void
  onOpenTask?: (taskId: string) => void
  onNavigate?: (view: AppView) => void
}) {
  const activeTab: TasksTab = taskId ? 'tasks' : tab

  return (
    <main className="main-content tasks">
      <div className="tasks__bar">
        <Segmented
          label="任务视图"
          value={activeTab}
          options={[
            { value: 'tasks', label: '任务' },
            { value: 'history', label: '历史草稿' },
          ]}
          onChange={(next) => onChangeTab?.(next)}
        />
      </div>

      {activeTab === 'tasks' ? (
        <ContentWorkbenchPage taskId={taskId} onNavigate={onNavigate} />
      ) : (
        <ContentHistoryPage onOpenTask={(id) => onOpenTask?.(id)} onCreateTask={() => onChangeTab?.('tasks')} />
      )}
    </main>
  )
}