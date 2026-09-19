import { pendingApprovalRunId, type PendingApprovalItem } from './types'

/**
 * 待办的下落（S5「点开直达审批」）。
 * 纪律：**只给真实存在的目的地**；没有处理入口的类型一律返回 `note` 如实说明，
 * 不渲染按钮、不假装可点（点了没反应不算通过）。
 */
export interface PendingApprovalDestinations {
  onOpenTask?: (taskId: string) => void
  onOpenRun?: (runId: string) => void
}

export interface PendingApprovalAction {
  label: string
  run?: () => void
  note?: string
}

export function resolvePendingApprovalAction(
  item: PendingApprovalItem,
  destinations: PendingApprovalDestinations,
): PendingApprovalAction {
  if (item.kind === 'task_approval') {
    if (!destinations.onOpenTask) return { label: '', note: '当前页面不能打开任务，请到「任务」里查看。' }
    return { label: '打开任务', run: () => destinations.onOpenTask?.(item.target_id) }
  }

  if (item.kind === 'run_approval') {
    const runId = pendingApprovalRunId(item)
    if (!runId) return { label: '', note: '这条待办缺少运行标识，暂时无法跳转。' }
    if (!destinations.onOpenRun) return { label: '', note: '当前页面不能打开运行详情，请到「对话」里查看。' }
    return { label: '打开运行去审批', run: () => destinations.onOpenRun?.(runId) }
  }

  if (item.kind === 'plan_proposal') {
    return { label: '', note: '计划提案的处理入口尚未交付：现在只能看到它，交付后可直接处理。' }
  }

  return { label: '', note: '账号注册的审批入口尚未交付：现在只能看到它，交付后可直接处理。' }
}