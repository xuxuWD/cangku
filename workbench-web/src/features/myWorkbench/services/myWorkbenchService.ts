/**
 * 「我的工作台」适配层 —— 本模块**唯一**的接线点。
 *
 * 现状：**未接后端**。`mode = 'mock'` 时返回显式标注（`sample: true`）的样例数据。
 * 纪律（三条，改这个文件前先读）：
 *  ① mock 分支的数据一律带 `sample: true`，界面必须显示"示例数据（未接后端）"；
 *  ② `http` 分支**必须抛错**，不得静默返回空数组 —— 静默空会伪装成"真的没有数据"；
 *  ③ 未来接线只改这一个文件（页面与组件都不认识 URL）。
 *
 * 接口口径见 `docs/contracts/my-workbench-api.md`（与 `types.ts` 字段逐字一致）。
 */
import type { QuickActionItem, RecentItem, SamplePayload, ScheduleAvailability, TodoItem } from '../types'

export type ServiceMode = 'mock' | 'http'

/**
 * 适配层唯一模式开关：本轮默认 `mock`。
 * 接线轮改为 `'http'`，或用构建期变量 `VITE_WORKBENCH_API_MODE=http` 注入。
 */
export let mode: ServiceMode = import.meta.env.VITE_WORKBENCH_API_MODE === 'http' ? 'http' : 'mock'

/** 切换模式（开发 / 测试用；生产接线轮由上面的默认值或环境变量决定）。 */
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

/** 取数失败 → 界面四态：`forbidden` 单独区分（无权限），其余一律按 `error` 处理。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  return error instanceof WorkbenchServiceError && error.failure === 'forbidden' ? 'forbidden' : 'error'
}

/** 页面上唯一一处"示例数据"标识文案（单一来源，禁止各处另写）。 */
export const SAMPLE_DATA_BADGE = '示例数据（未接后端）'

/** 日程块的固定文案：如实说明"后端无实体"，不含任何日期 / 会议条目。 */
export const SCHEDULE_NOTE =
  '日程尚未接入：后端暂无日程实体（接口未定义），已登记为后续专项（见 docs/contracts/adr.md「明确后置」WH-01~04）。本块不展示任何日程数据。'

/** 日程可用性（与 `fetchSchedule` 结果同值，供页面做初始值）。 */
export const SCHEDULE_ABSENT: ScheduleAvailability = { backend_entity: 'absent', note: SCHEDULE_NOTE }

function notConnected(what: string): never {
  throw new WorkbenchServiceError(`${what}尚未接入：后端接口未接线（本轮为${SAMPLE_DATA_BADGE}）。`, 'not_connected')
}

/** 样例待办（虚构内容，无 PII：不含手机号 / 用户 ID / 租户 ID）。 */
const MOCK_TODOS: TodoItem[] = [
  {
    source: 'approval',
    kind: 'task_approval',
    title: '待审批：整理本周选题',
    created_at: '2026-09-19T09:20:00+08:00',
    target_type: 'task',
    target_id: 'sample-task-0001',
  },
  {
    source: 'approval',
    kind: 'plan_proposal',
    title: '待裁决：季度内容计划（3 步）',
    created_at: '2026-09-19T08:40:00+08:00',
    target_type: 'plan_proposal',
    target_id: 'sample-proposal-0001',
  },
  {
    source: 'notification',
    kind: 'notification_result',
    title: '任务已通过：整理客户反馈',
    created_at: '2026-09-18T17:05:00+08:00',
    target_type: 'task',
    target_id: 'sample-task-0002',
  },
]

/** 样例最近使用（虚构内容）。 */
const MOCK_RECENT: RecentItem[] = [
  {
    kind: 'conversation',
    target_id: 'sample-conversation-0001',
    title: '示例会话：季度内容排期',
    updated_at: '2026-09-19T09:05:00+08:00',
  },
  {
    kind: 'conversation',
    target_id: 'sample-conversation-0002',
    title: '示例会话：产品资料摘要',
    updated_at: '2026-09-18T20:30:00+08:00',
  },
  {
    kind: 'run',
    target_id: 'sample-run-0001',
    title: '示例运行：文档摘要生成',
    updated_at: '2026-09-18T18:40:00+08:00',
  },
]

/**
 * 快捷入口目录：**前端静态定义**（后端无此实体，见契约 §4）。
 * 可用性按角色能力本地判定 —— 管理类入口对员工禁用并给原因，不隐藏。
 */
export const QUICK_ACTIONS: QuickActionItem[] = [
  { key: 'start-conversation', label: '发起对话', capability: null, kind: 'common' },
  { key: 'new-task', label: '新建任务', capability: null, kind: 'common' },
  { key: 'search-knowledge', label: '搜知识', capability: null, kind: 'common' },
  { key: 'my-agents', label: '我的数字员工', capability: null, kind: 'common' },
  { key: 'agent-config', label: '数字员工配置', capability: 'agent.manage', kind: 'admin' },
  { key: 'permission-config', label: '权限配置', capability: 'permission.manage', kind: 'admin' },
]

/** 待办：待审批聚合（`GET /api/v1/approvals/pending`）+ 站内通知（`GET /api/v1/inbox`）。 */
export async function fetchTodos(): Promise<SamplePayload<TodoItem>> {
  if (mode === 'http') notConnected('待办列表')
  return { sample: true, items: MOCK_TODOS }
}

/** 最近使用：最近会话（`GET /api/v1/conversations`）+ 最近运行（列表接口未定义，见契约 §2）。 */
export async function fetchRecent(): Promise<SamplePayload<RecentItem>> {
  if (mode === 'http') notConnected('最近使用')
  return { sample: true, items: MOCK_RECENT }
}

/**
 * 日程：后端**无实体**，因此与 `mode` 无关 —— 两种模式都返回同一个"无实体"标记。
 * 这里**不抛错也不返回空数组**：抛错会被当成"加载失败"，空数组会被读成"今天没有日程"。
 */
export async function fetchSchedule(): Promise<ScheduleAvailability> {
  return SCHEDULE_ABSENT
}

/** 快捷入口：前端静态目录。`http` 模式下按纪律抛错，不静默返回本地写死的入口。 */
export async function fetchQuickActions(): Promise<QuickActionItem[]> {
  if (mode === 'http') notConnected('快捷入口目录')
  return QUICK_ACTIONS
}