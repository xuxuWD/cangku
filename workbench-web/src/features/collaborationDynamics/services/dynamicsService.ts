/**
 * 「协同动态」适配层 —— 本模块**唯一**的接线点。
 *
 * **来源**：由 `admin-web/src/features/collaborationDynamics/api.ts` 合并移植；传输层换成全前端唯一
 * 请求层（`src/api/client.ts`），契约未改。
 *
 * ⚠️ **与原实现的一处有意差异（如实登记）**：
 * admin-web 原实现对「响应不是数组」按"没有动态"处理（理由是不让面板整块空白）。
 * 基座纪律要求**不得静默返回空**（静默空会伪装成"真的没有数据"，见 `utils/serviceKit.ts` 第 ② 条），
 * 且形状不符是**服务端契约被破坏**，必须让用户看见 —— 故本实现**改为抛错**，走"加载失败（可重试）"态。
 *
 * 纪律：样例数据只在开发模式存在；`http` 分支必须抛错或返回真实数据；失败按分类呈现。
 */
import { request } from '../../../api/client'
import { SAMPLE_DATA_BADGE, resolveServiceMode, serviceErrorFromApi } from '../../../utils/serviceKit'
import type { CollaborationDynamic } from '../types'

export { SAMPLE_DATA_BADGE }

export type ServiceMode = 'mock' | 'http'

export let mode: ServiceMode = resolveServiceMode()

export function setServiceMode(next: ServiceMode): void {
  mode = next
}

export function isConnected(): boolean {
  return mode === 'http'
}

export const DYNAMICS_LIMIT = 50

const DYNAMICS_PATH = '/api/v1/collaboration-dynamics'

export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION = '协同动态来自服务端；可见范围由服务端按当前身份判定，界面不能扩大范围。'

export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页协同动态为示例数据，不代表任何真实任务。'
  : ''

export const DYNAMICS_EMPTY_NOTE = '暂无协同动态：有新的任务动态后会展示在这里。'

/** 无权限原因（`403`）。 */
export const DYNAMICS_PERMISSION_REASON =
  '当前账号没有查看协同动态的权限。可见范围由服务端按岗位判定，界面上的操作不能扩大范围。'

/** 形状不符统一文案（**绝不臆测**成"没有动态"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

const SAMPLE_ITEMS: readonly CollaborationDynamic[] = import.meta.env.DEV
  ? [
      {
        event_id: 'dyn-sample-1',
        aggregate_id: 'task-sample-1',
        action: 'task.queued',
        title: '任务「Q3 内容排期」进入执行队列',
        employee_key: 'content-writer',
        status: 'queued',
        tenant_id: 'demo-tenant',
        project_id: null,
        created_by: 'acct-sample',
        occurred_at: '2026-09-23T02:05:00Z',
      },
      {
        event_id: 'dyn-sample-2',
        aggregate_id: 'task-sample-2',
        action: 'task.submitted_for_approval',
        title: '任务「竞品资料抓取」提交审批',
        employee_key: 'researcher',
        status: 'pending_approval',
        tenant_id: 'demo-tenant',
        project_id: null,
        created_by: 'acct-sample',
        occurred_at: '2026-09-22T09:30:00Z',
      },
    ]
  : []

/** 拉取协同动态。服务端返回**裸数组**（不是信封），故形状校验针对数组本身。 */
export async function fetchDynamics(
  limit = DYNAMICS_LIMIT,
  fetchImpl?: typeof fetch,
): Promise<CollaborationDynamic[]> {
  if (mode === 'mock') return SAMPLE_ITEMS.map((item) => ({ ...item }))

  try {
    const payload = await request<unknown>(DYNAMICS_PATH, { query: { limit }, fetchImpl })
    if (!Array.isArray(payload)) throw new Error(SHAPE_ERROR)
    return payload as CollaborationDynamic[]
  } catch (error) {
    serviceErrorFromApi(error)
  }
}
