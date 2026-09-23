/**
 * 「通知（收件箱）」适配层 —— 本模块**唯一**的接线点（页面与组件都不认识 URL）。
 *
 * **来源**：由 `admin-web/src/features/inbox/api.ts` 合并移植到基座；**未改契约**，只把传输层
 * 从 admin-web 的自写 `fetch` 换成全前端唯一的请求层 `src/api/client.ts`（令牌注入 / 超时 /
 * 错误分类 / sanitize 全在那里，本文件不得自己发 HTTP）。
 *
 * 契约（`docs/api-contract.md`「站内通知（收件箱）」）：
 *  - 读：`GET  /api/v1/inbox`（`unread_only` / `limit`）；
 *  - 写：`POST /api/v1/inbox/{inbox_id}/read`（单条标已读，返回更新后的条目）
 *        `POST /api/v1/inbox/read-all`（全部标已读，返回 `{ updated }`）。
 *
 * 纪律（改这个文件前先读）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`）⇒ 生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真实数据**，不得静默返回空数组冒充"真的没有通知"；
 *  ③ `403`（无权限）与其它失败**按分类呈现**，不吞异常、不改写成"没有通知"；
 *  ④ 未来接线只改这一个文件。
 */
import { request } from '../../../api/client'
import { SAMPLE_DATA_BADGE, resolveServiceMode, serviceErrorFromApi } from '../../../utils/serviceKit'
import type { InboxItem, InboxList } from '../types'

export type ServiceMode = 'mock' | 'http'

/** 适配层唯一模式开关（与其它模块同一份解析规则：显式变量 > 开发期 `mock` > 生产 `http`）。 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 当前是否已接入真实后端（用函数取，避免页面读到模块级绑定的快照值）。 */
export function isConnected(): boolean {
  return mode === 'http'
}

/** 单页上限（与 admin-web 侧一致）。 */
export const INBOX_LIMIT = 50

const INBOX_PATH = '/api/v1/inbox'

/** 已接入真实数据时的说明（与「示例数据」标识互斥，避免含糊）。 */
export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '通知由服务端写入，标记已读只影响你自己的收件箱，不影响其他人。'

/** 样例模式下的说明（**只在开发期存在** ⇒ 生产构建里为空串，"示例数据"字样不进产物）。 */
export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页通知为示例数据，不代表任何真实审批或运行结果。'
  : ''

/** 空态与筛选未命中要分开说，**不得**把"筛选没命中"说成"没有通知"。 */
export const INBOX_EMPTY_NOTE = '还没有通知。'
export const INBOX_NO_UNREAD_NOTE = '当前列表里的通知都已读，切回「全部」可以查看历史通知。'

/** 无权限原因（`403`；矩阵口径：通知按当前登录身份自限，不向他人开放）。 */
export const INBOX_PERMISSION_REASON =
  '收件箱只显示你自己的通知：通知范围由服务端按当前登录身份强制，界面上的筛选不能扩大范围。'

/** 形状不符统一文案（**绝不臆测**成"没有通知"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

/** 稳定的空结果（非就绪态的占位值，**不外泄**给界面当作真实数据）。 */
export const EMPTY_INBOX: InboxList = { sample: false, items: [], unread_count: 0 }

/**
 * 开发期样例数据（生产构建里为空数组 ⇒ 整块被摇掉）。
 * 覆盖「能到 / 不能到」两类目标，便于开发期就能看见行内如实说明。
 */
const SAMPLE_ITEMS: readonly InboxItem[] = import.meta.env.DEV
  ? [
      {
        inbox_id: 'inbox-sample-1',
        kind: 'task.approved',
        title: '任务「Q3 内容排期」已通过审批',
        target_type: 'task',
        target_id: 'task-sample-1',
        target_conversation_id: null,
        target_approval_id: null,
        created_at: '2026-09-23T02:10:00Z',
        read_at: null,
      },
      {
        inbox_id: 'inbox-sample-2',
        kind: 'run.failed',
        title: '运行「竞品资料抓取」失败',
        target_type: 'run',
        target_id: 'run-sample-1',
        target_conversation_id: null,
        target_approval_id: null,
        created_at: '2026-09-22T09:40:00Z',
        read_at: null,
      },
      {
        inbox_id: 'inbox-sample-3',
        kind: 'account.registration.approved',
        title: '注册申请已通过',
        target_type: null,
        target_id: null,
        target_conversation_id: null,
        target_approval_id: null,
        created_at: '2026-09-21T14:05:00Z',
        read_at: '2026-09-21T15:00:00Z',
      },
    ]
  : []

/**
 * 样例数据的**会话内可变副本**。
 *
 * 为什么不是直接返回 `SAMPLE_ITEMS`：页面在写成功后会**重新取数**（以服务端回读为准）。
 * 若样例数据是无状态的常量，标完已读一刷新就复原 ⇒ 开发期看着像"点了没用"，
 * 会让人误判成界面缺陷（2026-09-23 真机走查实测到这一点）。
 * ⇒ 样例也必须有状态，才谈得上"如实反映交互"。
 *
 * 生命周期：只活在内存里，**刷新页面即重置**（样例数据本就不该被持久化成"真实数据"）。
 */
let mockItems: InboxItem[] = SAMPLE_ITEMS.map((item) => ({ ...item }))

/** 重置样例状态（测试用，避免用例之间互相污染）。 */
export function resetMockInbox(): void {
  mockItems = SAMPLE_ITEMS.map((item) => ({ ...item }))
}

/** 形状校验：只接受契约里写明的形状；不符时抛错，**绝不**降级成空列表。 */
function asInboxList(payload: unknown): InboxList {
  const candidate = payload as Partial<InboxList> | null
  if (!candidate || typeof candidate !== 'object' || !Array.isArray(candidate.items)) {
    throw new Error(SHAPE_ERROR)
  }
  return {
    sample: false,
    items: candidate.items as InboxItem[],
    unread_count: typeof candidate.unread_count === 'number' ? candidate.unread_count : 0,
  }
}

function asInboxItem(payload: unknown): InboxItem {
  const candidate = payload as Partial<InboxItem> | null
  if (!candidate || typeof candidate !== 'object' || typeof candidate.inbox_id !== 'string') {
    throw new Error(SHAPE_ERROR)
  }
  return candidate as InboxItem
}

/** 拉取通知列表。`unreadOnly` 走服务端参数（与页内纯前端筛选不是一回事）。 */
export async function fetchInbox(
  unreadOnly = false,
  limit = INBOX_LIMIT,
  fetchImpl?: typeof fetch,
): Promise<InboxList> {
  if (mode === 'mock') {
    return {
      sample: true,
      items: mockItems.map((item) => ({ ...item })),
      unread_count: mockItems.filter((item) => item.read_at === null).length,
    }
  }

  try {
    const payload = await request<unknown>(INBOX_PATH, {
      query: { unread_only: unreadOnly, limit },
      fetchImpl,
    })
    return asInboxList(payload)
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 单条标为已读（**真实副作用**：服务端写入 `read_at` 并返回更新后的条目）。 */
export async function markInboxRead(inboxId: string, fetchImpl?: typeof fetch): Promise<InboxItem> {
  if (mode === 'mock') {
    const found = mockItems.find((item) => item.inbox_id === inboxId)
    if (!found) throw new Error(SHAPE_ERROR)
    const updated = { ...found, read_at: found.read_at ?? '2026-09-23T03:00:00Z' }
    mockItems = mockItems.map((item) => (item.inbox_id === inboxId ? updated : item))
    return updated
  }

  try {
    const payload = await request<unknown>(`${INBOX_PATH}/${encodeURIComponent(inboxId)}/read`, {
      method: 'POST',
      fetchImpl,
    })
    return asInboxItem(payload)
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

/** 全部标为已读。返回受影响条数（`updated`）。 */
export async function markAllInboxRead(fetchImpl?: typeof fetch): Promise<{ updated: number }> {
  if (mode === 'mock') {
    const pending = mockItems.filter((item) => item.read_at === null).length
    const now = '2026-09-23T03:00:00Z'
    mockItems = mockItems.map((item) => (item.read_at === null ? { ...item, read_at: now } : item))
    return { updated: pending }
  }

  try {
    const payload = await request<unknown>(`${INBOX_PATH}/read-all`, { method: 'POST', fetchImpl })
    const candidate = payload as { updated?: unknown } | null
    if (!candidate || typeof candidate !== 'object' || typeof candidate.updated !== 'number') {
      throw new Error(SHAPE_ERROR)
    }
    return { updated: candidate.updated }
  } catch (error) {
    serviceErrorFromApi(error)
  }
}

export { SAMPLE_DATA_BADGE }
