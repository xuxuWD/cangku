/**
 * 「用量与费用 + 数据导出」适配层 —— 本模块**唯一**的接线点。
 *
 * **来源**：由 `admin-web/src/features/billing/api.ts` 合并移植；传输层换成全前端唯一请求层
 * （`src/api/client.ts`，令牌注入 / 超时 / sanitize 全在那里），契约未改。
 *
 * 错误口径：**按状态码给固定中文文案**，不透出服务端原始 `detail`
 * （后端改词或换实现时界面文案不漂移）。`404` 的语义是「本租户尚未在商业化模块登记」——
 * 这是**常见态、不是故障**，界面上要与"加载失败"分开呈现（`asBillingError` 暴露 `status` 供页面分流）。
 *
 * 纪律：样例数据只在开发模式存在；`http` 分支必须抛错或返回真实数据；不得静默返回空。
 */
import { ApiError, request } from '../../../api/client'
import {
  SAMPLE_DATA_BADGE,
  ServiceError,
  resolveServiceMode,
  type ServiceFailure,
} from '../../../utils/serviceKit'
import type {
  ExportPackageDetail,
  ExportPackageList,
  LifecycleJob,
  UsageSummary,
} from '../types'

export type ServiceMode = 'mock' | 'http'
export type ErrorScope = 'usage' | 'export'

export let mode: ServiceMode = resolveServiceMode()

export function setServiceMode(next: ServiceMode): void {
  mode = next
}

export function isConnected(): boolean {
  return mode === 'http'
}

const USAGE_PATH = '/commercial/usage'
const EXPORTS_PATH = '/commercial/exports'
const LIFECYCLE_PATH = '/commercial/lifecycle'
const API_PREFIX = '/api/v1'

/** 单页上限（导出包列表）。 */
export const EXPORT_PACKAGE_LIMIT = 20

export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '用量与费用来自追加式用量账本（含冲正记录），本页只读：不提供冲正、额度调整或计费口径变更入口。'

export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页用量与费用为示例数据，不代表任何真实计费结果。'
  : ''

/** 未登记账本（`404`）的如实说明：**这不是故障**，且与"加载失败"分开呈现。 */
export const NOT_REGISTERED_NOTE =
  '商业化模块里还没有本租户的登记记录，因此没有可展示的用量与费用。这通常说明当前环境尚未初始化商业化数据，不是故障；已登记租户即使没有计量事件也会返回 0。'

export const EXPORT_HINT =
  '导出本租户在平台里的配置与业务记录，内容经过脱敏（不含密码、登录凭据与客户原文）。申请后由后台生成导出包，生成完成后才能下载；导出包自生成起 7 天内有效。'

/** 形状不符统一文案（**绝不臆测**成"没有数据"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

/** 固定中文文案（按状态码），与 `admin-web` 原口径逐字一致。 */
const FIXED_MESSAGES: Record<ErrorScope, Record<number, string>> = {
  usage: {
    401: '登录态已失效，请重新登录。',
    403: '当前账号没有查看用量与费用的权限。',
    404: '本租户尚未在商业化模块登记，暂时没有可展示的用量与费用。',
    0: '用量与费用服务暂时不可用，请检查网络后重新尝试。',
  },
  export: {
    401: '登录态已失效，请重新登录。',
    403: '当前账号没有查看数据导出的权限。',
    404: '本租户尚未在商业化模块登记，暂时不能导出数据。',
    0: '数据导出服务暂时不可用，请检查网络后重新尝试。',
  },
}

/** 适配层错误：带**状态码**与**所属面**，供页面把 404（未登记）与真故障分开。 */
export class BillingError extends ServiceError {
  readonly status: number
  readonly scope: ErrorScope

  constructor(message: string, failure: ServiceFailure, status: number, scope: ErrorScope) {
    super(message, failure)
    this.name = 'BillingError'
    this.status = status
    this.scope = scope
  }
}

/** 请求层失败 → 本层失败（固定文案 + 状态码）。非请求层错误原样抛出（不吞异常）。 */
function toBillingError(error: unknown, scope: ErrorScope): never {
  if (error instanceof ApiError) {
    const messages = FIXED_MESSAGES[scope]
    const message =
      messages[error.status] ??
      (error.failure === 'unavailable' ? messages[0] : error.message)
    throw new BillingError(message, error.failure === 'forbidden' ? 'forbidden' : 'failed', error.status, scope)
  }
  throw error
}

const MOCK_USAGE: UsageSummary = { tenant_id: 'demo-tenant', units: 1280, cost_cents: 4321 }

/** 样例里刻意备一条**负数**累计：冲正后累计为负是合法态，开发期就该看得见它的渲染。 */
export const MOCK_USAGE_NEGATIVE: UsageSummary = { tenant_id: 'demo-tenant', units: 980, cost_cents: -1500 }

/** 测试 / 开发用：切换样例用量到「有过冲正」的负值形态。 */
export let mockNegative = false
export function setMockUsageNegative(next: boolean): void {
  mockNegative = next
}

const MOCK_PACKAGES: ExportPackageList = import.meta.env.DEV
  ? {
      items: [
        {
          package_id: 'pkg-sample-1',
          tenant_id: 'demo-tenant',
          job_id: 'job-sample-1',
          created_at: '2026-09-23T01:00:00Z',
          expires_at: '2026-09-30T01:00:00Z',
        },
        {
          package_id: 'pkg-sample-expired',
          tenant_id: 'demo-tenant',
          job_id: 'job-sample-0',
          created_at: '2026-09-01T01:00:00Z',
          expires_at: '2026-09-08T01:00:00Z',
        },
      ],
      total: 2,
      limit: EXPORT_PACKAGE_LIMIT,
      offset: 0,
    }
  : { items: [], total: 0, limit: EXPORT_PACKAGE_LIMIT, offset: 0 }

/** 累计用量与费用（只读）。 */
export async function fetchUsage(fetchImpl?: typeof fetch): Promise<UsageSummary> {
  if (mode === 'mock') return { ...(mockNegative ? MOCK_USAGE_NEGATIVE : MOCK_USAGE) }

  try {
    const payload = await request<unknown>(API_PREFIX + USAGE_PATH, { fetchImpl })
    const candidate = payload as Partial<UsageSummary> | null
    if (!candidate || typeof candidate !== 'object' || typeof candidate.cost_cents !== 'number') {
      throw new Error(SHAPE_ERROR)
    }
    return candidate as UsageSummary
  } catch (error) {
    toBillingError(error, 'usage')
  }
}

/** 申请租户数据导出（服务端只创建异步作业并返回 `202`）。 */
export async function requestExport(fetchImpl?: typeof fetch): Promise<LifecycleJob> {
  if (mode === 'mock') {
    return {
      job_id: 'job-sample-new',
      tenant_id: 'demo-tenant',
      kind: 'tenant_export',
      status: 'queued',
      requested_by: 'acct-walkthrough',
      requested_at: '2026-09-23T03:00:00Z',
      execute_after: null,
      final_exported: false,
    }
  }

  try {
    const payload = await request<unknown>(API_PREFIX + EXPORTS_PATH, { method: 'POST', fetchImpl })
    const candidate = payload as Partial<LifecycleJob> | null
    if (!candidate || typeof candidate !== 'object' || typeof candidate.job_id !== 'string') {
      throw new Error(SHAPE_ERROR)
    }
    return candidate as LifecycleJob
  } catch (error) {
    toBillingError(error, 'export')
  }
}

/** 查导出作业状态（用于确认后台是否已生成导出包）。 */
export async function fetchLifecycleJob(jobId: string, fetchImpl?: typeof fetch): Promise<LifecycleJob> {
  if (mode === 'mock') {
    return {
      job_id: jobId,
      tenant_id: 'demo-tenant',
      kind: 'tenant_export',
      status: 'completed',
      requested_by: 'acct-walkthrough',
      requested_at: '2026-09-23T03:00:00Z',
      execute_after: null,
      final_exported: true,
    }
  }

  try {
    const payload = await request<unknown>(`${API_PREFIX}${LIFECYCLE_PATH}/${encodeURIComponent(jobId)}`, { fetchImpl })
    const candidate = payload as Partial<LifecycleJob> | null
    if (!candidate || typeof candidate !== 'object' || typeof candidate.status !== 'string') {
      throw new Error(SHAPE_ERROR)
    }
    return candidate as LifecycleJob
  } catch (error) {
    toBillingError(error, 'export')
  }
}

/** 列出本租户已生成的导出包（元数据；不含载荷）。 */
export async function fetchExportPackages(
  limit = EXPORT_PACKAGE_LIMIT,
  offset = 0,
  fetchImpl?: typeof fetch,
): Promise<ExportPackageList> {
  if (mode === 'mock') return { ...MOCK_PACKAGES, items: MOCK_PACKAGES.items.map((item) => ({ ...item })) }

  try {
    const payload = await request<unknown>(API_PREFIX + EXPORTS_PATH, { query: { limit, offset }, fetchImpl })
    const candidate = payload as Partial<ExportPackageList> | null
    // 边界校验（响应来自外部服务）：条目不是数组 ⇒ 按契约不符处理，
    // 既不静默当成空列表，也不让一次异常响应把整页渲染打崩。
    if (!candidate || typeof candidate !== 'object' || !Array.isArray(candidate.items)) {
      throw new Error(SHAPE_ERROR)
    }
    return candidate as ExportPackageList
  } catch (error) {
    toBillingError(error, 'export')
  }
}

/** 取回导出包全文（脱敏载荷）：**只在「下载」动作里使用**，不渲染到页面上。 */
export async function fetchExportPackage(packageId: string, fetchImpl?: typeof fetch): Promise<ExportPackageDetail> {
  if (mode === 'mock') {
    return {
      package_id: packageId,
      tenant_id: 'demo-tenant',
      job_id: 'job-sample-1',
      created_at: '2026-09-23T01:00:00Z',
      expires_at: '2026-09-30T01:00:00Z',
      payload: { sample: true, note: '示例导出包，仅用于开发期验证下载流程。' },
    }
  }

  try {
    const payload = await request<unknown>(`${API_PREFIX}${EXPORTS_PATH}/${encodeURIComponent(packageId)}`, { fetchImpl })
    const candidate = payload as Partial<ExportPackageDetail> | null
    if (!candidate || typeof candidate !== 'object' || candidate.payload === undefined) {
      throw new Error(SHAPE_ERROR)
    }
    return candidate as ExportPackageDetail
  } catch (error) {
    toBillingError(error, 'export')
  }
}

export { SAMPLE_DATA_BADGE }
