/**
 * 「我的工作台」模块类型（第 3 轮）。
 *
 * 命名口径：**尽量沿用后端契约既有字段名**（`docs/api-contract.md`），
 * 前端归一化出来的字段在注释里点明来源；与本模块契约
 * `docs/contracts/my-workbench-api.md` **逐字一致**（改一处必须同时改另一处）。
 */
import type { Capability } from '../../app/session'

/** 待办来源接口：待审批聚合（`/approvals/pending`）或站内通知（`/inbox`）。 */
export type TodoSource = 'approval' | 'notification'

/**
 * 待办类型（受控枚举）。
 * 前四类沿用后端 `/approvals/pending` 的 `kind`（`app/approvals.py:10-13`）；
 * `notification_result` 是站内通知（`/inbox`，11 个 kind，见 `app/inbox.py:47-58`）在界面的归一化取值；
 * `other` 是**未知 kind 的安全落点**（后端将来新增取值时如实显示"其他"，不误标成已知类型）。
 */
export type TodoKind =
  | 'task_approval'
  | 'plan_proposal'
  | 'run_approval'
  | 'account_registration'
  | 'notification_result'
  | 'other'

export interface TodoItem {
  /** 来源接口（前端合并两个来源时的判别字段）。 */
  source: TodoSource
  /** 类型：决定标签文案与语义色。 */
  kind: TodoKind
  /** 标题（后端为服务端固定文案，不含用户输入）。 */
  title: string
  /** 创建时间（ISO 8601，后端字段同名）。 */
  created_at: string
  /** 关联对象类型（后端可空）。 */
  target_type: string | null
  /** 关联对象 ID：任务号 / 审批号 / 通知号（后端字段同名）。 */
  target_id: string
  /**
   * 站内通知 ID（`/inbox` 的 `inbox_id`）；**审批类来源为 `null`**（审批没有"已读"概念）。
   * 只有非空时界面才提供"标记已读"，并据此调 `POST /api/v1/inbox/{inbox_id}/read`。
   */
  inbox_id: string | null
}

/** 最近使用的条目种类：会话或运行。 */
export type RecentKind = 'conversation' | 'run'

export interface RecentItem {
  kind: RecentKind
  /** 归一化主键：会话 ← `conversation_id`；运行 ← `run_id`。 */
  target_id: string
  /** 标题（后端字段同名）。 */
  title: string
  /** 最近更新时间：会话 ← `updated_at`；运行 ← `finished_at`（见契约 §2）。 */
  updated_at: string
}

/**
 * 日程可用性：**后端没有日程 / 日历实体，接口未定义**（见契约 §3）。
 *
 * `backend_entity` 被定死为 `'absent'` —— 这是**类型层面的硬约束**：
 * 本轮任何人都无法把"日程条目"塞进这个组件，也就杜绝了编造日程数据。
 */
export interface ScheduleAvailability {
  backend_entity: 'absent'
  /** 界面固定文案（含"尚未接入"字样）。 */
  note: string
}

/** 快捷入口键（受控枚举）。 */
export type QuickActionKey =
  | 'start-conversation'
  | 'new-task'
  | 'search-knowledge'
  | 'my-agents'
  | 'agent-config'
  | 'permission-config'

export interface QuickActionItem {
  key: QuickActionKey
  label: string
  /** 需要的能力；`null` 表示所有登录角色都可用。 */
  capability: Capability | null
  /** `admin` = 管理类入口：无权限时**禁用 + 给原因**，绝不静默隐藏。 */
  kind: 'common' | 'admin'
}

/**
 * 列表信封：`sample` 是**显式来源标记**。
 * `true` = 开发期样例（界面必须显示「示例数据（未接后端）」）；
 * `false` = 来自后端真实接口（接线后）。**绝不允许**把真实数据标成 sample，反之亦然。
 */
export interface SamplePayload<T> {
  sample: boolean
  items: T[]
}