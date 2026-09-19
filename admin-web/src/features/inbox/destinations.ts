import type { InboxItem } from './types'

/**
 * 通知的下落（S3「无死胡同」）。
 *
 * 纪律：**能到的直达，不能到的如实说明**——没有处理入口的类型返回 `note`（行内展示），
 * 不渲染按钮、不假装可点（「点了没反应」不算通过）。
 *
 * 后端 `target_type` / `target_id` 口径（`app/inbox.py`）：
 *  * `task` → 任务 id（任务审批结果）
 *  * `publication` → **来源任务 id**（发布转人工接管）
 *  * `run` → 运行 id（运行失败 / 取消 / 审批被驳回）；**带 `target_conversation_id` 时优先直达该会话**
 *    （S1 第三款，带 `target_approval_id` 时页内聚焦那张卡），否则回落运行详情
 *  * `plan_proposal` / `orchestration_proposal` → 提案 id（前端无处理页）
 *  * `crm_contract` / `crm_activity` → CRM 对象（落到对应列表页）
 *  * 无 `target_type` 的（如账号注册结果）→ 无对象可打开
 */
export interface InboxDestinations {
  onOpenTask?: (taskId: string) => void
  onOpenRun?: (runId: string) => void
  /** S1 第三款：带会话上文的通知直达「该会话（的该条卡）」；第二个参数是该条审批（可缺）。 */
  onOpenConversation?: (conversationId: string, approvalId?: string) => void
  onNavigate?: (view: 'crmContracts' | 'crmProgress') => void
}

export interface InboxAction {
  label: string
  run?: () => void
  note?: string
}

export function resolveInboxAction(item: InboxItem, destinations: InboxDestinations): InboxAction {
  const targetId = item.target_id

  if (!item.target_type || !targetId) {
    return { label: '', note: '这条通知没有可打开的对象（例如账号注册结果）；标记已读即可。' }
  }

  if (item.target_type === 'task' || item.target_type === 'publication') {
    if (!destinations.onOpenTask) return { label: '', note: '当前页面不能打开任务，请到「任务」里查看。' }
    const label = item.target_type === 'publication' ? '打开来源任务' : '打开任务'
    return { label, run: () => destinations.onOpenTask?.(targetId) }
  }

  if (item.target_type === 'run') {
    // S1 第三款：服务端给了会话上文 ⇒ 直达该会话（带审批标识时页内聚焦那张卡）；
    // 没有会话上文（非对话触发的运行 / 存量通知）⇒ 按既有落点打开运行详情，语义不变。
    const conversationId = item.target_conversation_id
    if (conversationId && destinations.onOpenConversation) {
      const approvalId = item.target_approval_id ?? undefined
      return {
        label: approvalId ? '打开该会话的审批' : '打开会话',
        run: () => destinations.onOpenConversation?.(conversationId, approvalId),
      }
    }
    if (!destinations.onOpenRun) return { label: '', note: '当前页面不能打开运行详情，请到「对话」里查看。' }
    return { label: '打开运行详情', run: () => destinations.onOpenRun?.(targetId) }
  }

  if (item.target_type === 'crm_contract') {
    if (!destinations.onNavigate) return { label: '', note: '请到「更多 / 合同」查看。' }
    return { label: '打开合同页', run: () => destinations.onNavigate?.('crmContracts') }
  }

  if (item.target_type === 'crm_activity') {
    if (!destinations.onNavigate) return { label: '', note: '请到「更多 / 进度概览」查看。' }
    return { label: '打开进度概览', run: () => destinations.onNavigate?.('crmProgress') }
  }

  if (item.target_type === 'plan_proposal') {
    return { label: '', note: '计划提案的处理入口尚未交付：现在只能看到它，标记已读即可。' }
  }

  if (item.target_type === 'orchestration_proposal') {
    return { label: '', note: '编排优化的处理入口尚未交付：现在只能看到它，标记已读即可。' }
  }

  return { label: '', note: '这条通知的目标类型暂不支持打开；标记已读即可。' }
}