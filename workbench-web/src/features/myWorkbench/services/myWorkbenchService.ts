/**
 * 「我的工作台」适配层 —— 本模块**唯一**的接线点。
 *
 * 第 6 轮（接线批 1）：**`http` 分支已是真实现**（不再抛"尚未接入"）：
 *  - 待办 = 未读站内通知（`GET /api/v1/inbox?unread_only=true`）+ 待审批（`GET /api/v1/approvals/pending`）
 *    合并按 `created_at` 倒序；合并口径见 `docs/contracts/my-workbench-api.md` §1。
 *  - 「标记已读」走真端点 `POST /api/v1/inbox/{inbox_id}/read`（审批类待办没有已读概念，`inbox_id` 为 null）。
 *  - 「最近使用」「日程」**仍未接入**（后端没有运行列表 / 日程实体）：http 下如实抛 `not_connected`，
 *    **绝不返回空数组假装"没有内容"**（见契约 §2 / §3）。
 *
 * 纪律（改这个文件前先读）：
 *  ① mock 样例只在**开发模式**存在（`import.meta.env.DEV`）：生产构建里整块被摇掉，`sample` 恒为 false；
 *  ② 失败必须抛错，不静默返回空；
 *  ③ 未来接线只改这一个文件（页面与组件都不认识 URL）。
 */
import { ApiError, request } from '../../../api/client'
import { resolveServiceMode } from '../../../utils/serviceKit'
import type { QuickActionItem, RecentItem, SamplePayload, ScheduleAvailability, TodoItem } from '../types'

export type ServiceMode = 'mock' | 'http'

/** 模式：与其它模块同一份解析规则（显式变量 > 开发期 mock > 生产 http）。 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 失败分类：决定界面进入哪一种四态。 */
export type ServiceFailure = 'not_connected' | 'forbidden' | 'failed'

/** 适配层错误（只带可读文案与分类，**不含**凭据 / 内部地址 / 堆栈）。 */
export class WorkbenchServiceError extends Error {
  readonly failure: ServiceFailure

  constructor(message: string, failure: ServiceFailure) {
    super(message)
    this.name = 'WorkbenchServiceError'
    this.failure = failure
  }
}

/** 取数失败 → 界面四态：无权限单独区分，其余一律按 `error` 处理（不做静默降级）。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  if (error instanceof ApiError && error.failure === 'forbidden') return 'forbidden'
  if (error instanceof WorkbenchServiceError && error.failure === 'forbidden') return 'forbidden'
  return 'error'
}

/** 失败是否为"后端未定义该接口"（用于把"未接入"与"加载失败"分开呈现）。 */
export function isNotConnected(error: unknown): boolean {
  return error instanceof WorkbenchServiceError && error.failure === 'not_connected'
}

/** 页面上唯一一处"示例数据"标识文案（生产构建里为空串 ⇒ 相关字样不会进入产物）。 */
export const SAMPLE_DATA_BADGE: string = import.meta.env.DEV ? '示例数据（未接后端）' : ''

/** 日程块的固定文案：如实说明"后端无实体"，不含任何日期 / 会议条目。 */
export const SCHEDULE_NOTE =
  '日程尚未接入：后端暂无日程实体（接口未定义），已登记为后续专项（见 docs/contracts/adr.md「明确后置」WH-01~04）。本块不展示任何日程数据。'

/** 最近使用块的固定文案：运行列表接口未定义 ⇒ 本批仍不展示任何数据。 */
export const RECENT_NOTE =
  '最近使用尚未接入：后端没有运行列表接口（会话列表接口已存在，接线见后续批次）。本块不展示任何数据。'

/** 日程可用性（与 `fetchSchedule` 结果同值，供页面做初始值）。 */
export const SCHEDULE_ABSENT: ScheduleAvailability = { backend_entity: 'absent', note: SCHEDULE_NOTE }

function notConnected(what: string): never {
  throw new WorkbenchServiceError(`${what}尚未接入：后端接口未定义，本批不展示任何数据。`, 'not_connected')
}

/**
 * 开发期样例数据（虚构内容，无 PII：不含手机号 / 用户 ID / 租户 ID）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 */
const MOCK_TODOS: TodoItem[] = import.meta.env.DEV
  ? [
      {
        source: 'approval',
        kind: 'task_approval',
        title: '待审批：整理本周选题',
        created_at: '2026-09-19T09:20:00+08:00',
        target_type: 'task',
        target_id: 'sample-task-0001',
        inbox_id: null,
      },
      {
        source: 'notification',
        kind: 'notification_result',
        title: '任务已通过：整理客户反馈',
        created_at: '2026-09-18T17:05:00+08:00',
        target_type: 'task',
        target_id: 'sample-task-0002',
        inbox_id: 'sample-inbox-0002',
      },
    ]
  : []

const MOCK_RECENT: RecentItem[] = import.meta.env.DEV
  ? [
      {
        kind: 'conversation',
        target_id: 'sample-conversation-0001',
        title: '示例会话：季度内容排期',
        updated_at: '2026-09-19T09:05:00+08:00',
      },
    ]
  : []

/**
 * 快捷入口目录：**前端静态定义**（后端无此实体，见契约 §4）。
 * 可用性按角色能力判定 —— 管理类入口对无权限角色禁用并给原因，不隐藏。
 */
export const QUICK_ACTIONS: QuickActionItem[] = [
  { key: 'start-conversation', label: '发起对话', capability: null, kind: 'common' },
  { key: 'new-task', label: '新建任务', capability: null, kind: 'common' },
  { key: 'search-knowledge', label: '搜知识', capability: null, kind: 'common' },
  { key: 'my-agents', label: '我的数字员工', capability: null, kind: 'common' },
  { key: 'agent-config', label: '数字员工配置', capability: 'agent.manage', kind: 'admin' },
  { key: 'permission-config', label: '权限配置', capability: 'permission.manage', kind: 'admin' },
]

/** 单次合并的待办上限（`/inbox` 与 `/approvals/pending` 的 `limit` 上限都是 200）。 */
export const TODO_LIMIT = 50

/** 后端 `/approvals/pending` 的 `kind` → 界面受控枚举（`app/approvals.py:10-13` 的四个取值）。 */
const APPROVAL_KIND: Record<string, TodoItem['kind']> = {
  task_approval: 'task_approval',
  plan_proposal: 'plan_proposal',
  run_approval: 'run_approval',
  account_registration: 'account_registration',
}

/** `/inbox` 的 `kind`（`app/inbox.py:47-58` 的 11 个取值）在界面统一归一化为"结果通知"。 */
const INBOX_KIND: TodoItem['kind'] = 'notification_result'

/** 后端待审批条目（`PendingApprovalView`，`app/main.py:4568`）。 */
interface PendingApprovalView {
  kind: string
  target_id: string
  title: string
  requested_by: string | null
  created_at: string
  detail: Record<string, unknown>
}

/** 后端站内通知条目（`InboxItemView`，`app/main.py:4741`）。 */
interface InboxItemView {
  inbox_id: string
  kind: string
  title: string
  target_type: string | null
  target_id: string | null
  target_conversation_id: string | null
  target_approval_id: string | null
  created_at: string
  read_at: string | null
}

interface InboxListView {
  items: InboxItemView[]
  unread_count: number
}

interface PendingApprovalsView {
  items: PendingApprovalView[]
  counts: Record<string, number>
}

function todoFromApproval(item: PendingApprovalView): TodoItem {
  return {
    source: 'approval',
    // 未知 kind（后端将来新增取值）落到"其他"，**不误标**成已知类型
    kind: APPROVAL_KIND[item.kind] ?? 'other',
    title: item.title,
    created_at: item.created_at,
    target_type: 'approval',
    target_id: item.target_id,
    inbox_id: null,
  }
}

function todoFromInbox(item: InboxItemView): TodoItem {
  return {
    source: 'notification',
    kind: INBOX_KIND,
    title: item.title,
    created_at: item.created_at,
    target_type: item.target_type,
    target_id: item.target_id ?? item.inbox_id,
    inbox_id: item.inbox_id,
  }
}

/**
 * 待办：**未读**站内通知 + 待审批合并（按 `created_at` 倒序）。
 * 两个请求任一失败即整体失败（不静默漏掉一半数据 —— 少一半待办比"加载失败"更危险）。
 */
export async function fetchTodos(fetchImpl?: typeof fetch): Promise<SamplePayload<TodoItem>> {
  if (mode === 'mock') return { sample: true, items: MOCK_TODOS }

  const [inbox, approvals] = await Promise.all([
    request<InboxListView>('/api/v1/inbox', { query: { unread_only: true, limit: TODO_LIMIT }, fetchImpl }),
    request<PendingApprovalsView>('/api/v1/approvals/pending', { query: { limit: TODO_LIMIT }, fetchImpl }),
  ])

  const items = [...approvals.items.map(todoFromApproval), ...inbox.items.map(todoFromInbox)]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, TODO_LIMIT)

  return { sample: false, items }
}

/** 标记单条通知已读：`POST /api/v1/inbox/{inbox_id}/read`（重复标记幂等；他人/跨租户 404）。 */
export async function markTodoRead(inbox_id: string, fetchImpl?: typeof fetch): Promise<void> {
  if (mode === 'mock') {
    // 样例标识只在开发期存在（生产构建里 `SAMPLE_DATA_BADGE` 为空串 ⇒ 该字样不进产物，构建后 grep 为 0）
    throw new WorkbenchServiceError(
      `${SAMPLE_DATA_BADGE || '后台未接入'}，标记已读不会写入任何数据。`,
      'not_connected',
    )
  }
  await request<unknown>(`/api/v1/inbox/${encodeURIComponent(inbox_id)}/read`, { method: 'POST', fetchImpl })
}

/** 最近使用：后端**没有运行列表接口** ⇒ 本批如实抛"未接入"，不返回空数组。 */
export async function fetchRecent(): Promise<SamplePayload<RecentItem>> {
  if (mode === 'mock') return { sample: true, items: MOCK_RECENT }
  notConnected('最近使用')
}

/**
 * 日程：后端**无实体**，因此与 `mode` 无关 —— 两种模式都返回同一个"无实体"标记。
 * 这里**不抛错也不返回空数组**：抛错会被当成"加载失败"，空数组会被读成"今天没有日程"。
 */
export async function fetchSchedule(): Promise<ScheduleAvailability> {
  return SCHEDULE_ABSENT
}

/** 快捷入口：前端静态目录（`capability` 决定可用性，界面禁用而非隐藏）。 */
export async function fetchQuickActions(): Promise<QuickActionItem[]> {
  return QUICK_ACTIONS
}