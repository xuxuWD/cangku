/**
 * 「审计日志」适配层 —— 本模块**唯一**的接线点（页面与组件都不认识 URL）。
 *
 * 第 10 轮真机复测（2026-09-20，工作树后端 + 真库，超管 `13600000001` / 员工 `13600000002`）：
 *  - 读：`GET /api/v1/audits`（`action` **可重复** / `target_type` / `target_id` / `actor_id` /
 *        `since` / `until` / `limit` 1–200 / `offset`）；真库已有 1800+ 条记录；
 *  - 新增：`GET /api/v1/audits/actions`（动作目录，返回后端 `AuditAction` **全集**，94 项）；
 *  - **门禁**：四个业务角色可读（`employee` 为**服务端强制**的"仅本人相关"档）；`customer_admin` ⇒ `403`；
 *  - **时间参数**：必须带时区 —— 实测 `Z` 形态 ⇒ `200`；naive ⇒ `422`「since 必须带时区」；
 *    URL 里**字面 `+00:00` 会被解码成空格** ⇒ `422`（`%2B00:00` 或 `Z` 才可）⇒ 前端一律 `toISOString()`；
 *  - 其它约束：未知动作码 ⇒ `422`「未知的审计动作：xxx」；`limit=201` ⇒ `422`（`detail` 是数组）。
 *
 * 纪律（改这个文件前先读）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`）⇒ 生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真实数据**，不得静默返回空数组冒充"真的没有记录"；
 *  ③ `403`（无权限）/ `401` 等失败**按分类呈现**，不吞异常、不改写成"没有记录"；
 *  ④ 未来接线只改这一个文件。
 */
import { ApiError, request } from '../../../api/client'
import { SAMPLE_DATA_BADGE, ServiceError, resolveServiceMode } from '../../../utils/serviceKit'
import type { AuditActionCatalog, AuditPage, AuditPageParams, AuditQuery, AuditRecord } from '../types'

export type ServiceMode = 'mock' | 'http'

/** 适配层唯一模式开关（与其它模块同一份解析规则：显式变量 > 开发期 `mock` > 生产 `http`）。 */
export let mode: ServiceMode = resolveServiceMode()

/** 切换模式（开发 / 测试用）。 */
export function setServiceMode(next: ServiceMode): void {
  mode = next
}

/** 当前是否为样例模式（用函数取，避免页面读到模块级绑定的快照值）。 */
export function isConnected(): boolean {
  return mode === 'http'
}

/** 单页上限（后端 `limit` 上限 200）。 */
export const AUDITS_LIMIT = 200

const AUDITS_PATH = '/api/v1/audits'
const AUDIT_ACTIONS_PATH = '/api/v1/audits/actions'

/** 已接入真实数据时的说明（与「示例数据」标识互斥，避免含糊）。 */
export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '审计记录来自服务端，只读且不可修改；查询范围由服务端按岗位判定，界面上的筛选只是查询条件。'

/** 样例模式下的说明（**只在开发期存在** ⇒ 生产构建里为空串，"示例数据"字样不进产物）。 */
export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页审计记录为示例数据，不代表任何真实操作。'
  : ''

/** 「本租户全量」档的空态（解释为什么空，并区分"筛选没命中"）。 */
export const AUDITS_EMPTY_NOTE = '本租户还没有审计记录。'
export const AUDITS_NO_MATCH_NOTE = '当前筛选条件下没有命中的审计记录，可放宽条件后重试。'

/** 「我的操作」档（`employee`）的空态。 */
export const MY_AUDITS_EMPTY_NOTE = '你还没有审计记录。'
export const MY_AUDITS_NO_MATCH_NOTE = '当前筛选条件下没有你本人的审计记录，可放宽条件后重试。'

/** 「仅本人相关」档的如实说明（服务端强制，不是界面隐藏）。
 *
 *  2026-09-21 真机走查修正：原文写作 `**你自己**`，但渲染处是**纯文本**（不是 Markdown）
 *  ⇒ 界面把星号原样显示成「此处只显示**你自己**的操作记录」。改为项目通行的「」标注，
 *  既保留强调又不依赖 Markdown（回归用例：`auditService.test.ts` 的"界面文案不用 Markdown 标记" +
 *  `AuditLogPage.test.tsx` 员工档的渲染断言）。 */
export const SELF_SCOPE_NOTE =
  '此处只显示「你自己」的操作记录（由服务端按岗位强制，界面上的筛选不能扩大范围）。'

/** 「审计导出」的如实说明：矩阵要求 `super_admin` 可导出，但**后端零实现** ⇒ 不给假入口。 */
export const AUDIT_EXPORT_NOT_CONNECTED_NOTE =
  '审计导出尚未接入：当前版本没有导出接口，本页不提供导出按钮，也不会伪造下载入口。'

/** 无权限原因（`customer_admin`；矩阵 §3「审计：查询」末列 ❌）。 */
export const AUDIT_PERMISSION_REASON =
  '审计日志不向客户管理员开放：员工可查看本人操作记录，部门负责人、企业负责人与超级管理员可查看本租户记录。'

/** 形状不符统一文案（**绝不臆测**成"没有记录"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

/** 适配层错误（只带可读文案与分类，**不含**凭据 / 内部地址 / 堆栈）。 */
export class AuditError extends ServiceError {
  readonly kind: 'forbidden' | 'failed'

  constructor(message: string, kind: 'forbidden' | 'failed') {
    super(message, kind === 'forbidden' ? 'forbidden' : 'failed')
    this.name = 'AuditError'
    this.kind = kind
  }
}

/** 取数失败 → 界面四态：`forbidden` 单独区分（无权限），其余按"加载失败"。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' {
  if (error instanceof AuditError && error.kind === 'forbidden') return 'forbidden'
  if (error instanceof ServiceError && error.failure === 'forbidden') return 'forbidden'
  return 'error'
}

function readError(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new AuditError(error.message, 'forbidden')
    throw new AuditError(error.message, 'failed')
  }
  throw error
}

/** 单条记录 → 模块类型；缺必需键即抛错（不静默跳过、不编造字段）。 */
function toRecord(raw: unknown): AuditRecord {
  const value = raw as Partial<AuditRecord> | null
  if (!value || typeof value.record_id !== 'string' || typeof value.action !== 'string') {
    throw new AuditError(SHAPE_ERROR, 'failed')
  }
  return {
    record_id: value.record_id,
    action: value.action,
    actor_id: typeof value.actor_id === 'string' ? value.actor_id : null,
    target_type: typeof value.target_type === 'string' ? value.target_type : null,
    target_id: typeof value.target_id === 'string' ? value.target_id : null,
    phone_masked: typeof value.phone_masked === 'string' ? value.phone_masked : null,
    detail:
      value.detail && typeof value.detail === 'object' && !Array.isArray(value.detail)
        ? (value.detail as Record<string, unknown>)
        : {},
    occurred_at: typeof value.occurred_at === 'string' ? value.occurred_at : '',
  }
}

/** 把查询条件拼成 query（**空条件不传**；动作码按重复键展开）。 */
function queryOf(filters: AuditQuery): Record<string, string | readonly string[] | undefined> {
  return {
    ...(filters.actions.length > 0 ? { action: filters.actions } : {}),
    ...(filters.target_type ? { target_type: filters.target_type } : {}),
    ...(filters.target_id ? { target_id: filters.target_id } : {}),
    ...(filters.actor_id ? { actor_id: filters.actor_id } : {}),
    ...(filters.since ? { since: filters.since } : {}),
    ...(filters.until ? { until: filters.until } : {}),
  }
}

/** 审计查询（分页；范围由服务端按岗位判定，客户端不带租户）。 */
export async function fetchAudits(
  filters: AuditQuery,
  params: AuditPageParams,
  fetchImpl?: typeof fetch,
): Promise<AuditPage> {
  if (mode === 'mock') {
    const items = MOCK_RECORDS
    return { sample: true, items, total: items.length, limit: AUDITS_LIMIT, offset: 0 }
  }

  try {
    const raw = await request<unknown>(AUDITS_PATH, {
      query: { ...queryOf(filters), limit: params.limit, offset: params.offset },
      fetchImpl,
    })
    const view = raw as { items?: unknown; total?: unknown; limit?: unknown; offset?: unknown }
    const items = view.items
    if (!Array.isArray(items)) throw new AuditError(SHAPE_ERROR, 'failed')
    return {
      sample: false,
      items: items.map(toRecord),
      total: typeof view.total === 'number' ? view.total : items.length,
      limit: typeof view.limit === 'number' ? view.limit : params.limit,
      offset: typeof view.offset === 'number' ? view.offset : params.offset,
    }
  } catch (error) {
    readError(error)
  }
}

/** 动作目录（后端枚举全集；界面不复制 94 项，避免漂移）。 */
export async function fetchAuditActions(fetchImpl?: typeof fetch): Promise<AuditActionCatalog> {
  if (mode === 'mock') {
    return { sample: true, items: MOCK_ACTIONS, total: MOCK_ACTIONS.length }
  }

  try {
    const raw = await request<unknown>(AUDIT_ACTIONS_PATH, { fetchImpl })
    const view = raw as { items?: unknown; total?: unknown } | null
    if (!view || !Array.isArray(view.items)) throw new AuditError(SHAPE_ERROR, 'failed')
    const items = view.items.filter((item): item is string => typeof item === 'string')
    return { sample: false, items, total: typeof view.total === 'number' ? view.total : items.length }
  } catch (error) {
    readError(error)
  }
}

/**
 * 开发期样例记录（虚构内容，无 PII：**掩码手机号也是虚构**，无真实用户 ID / 租户 ID / 密钥）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 * 刻意覆盖：有明细 / 无明细、有掩码手机号 / 无、有目标 / 无目标。
 */
const MOCK_RECORDS: AuditRecord[] = import.meta.env.DEV
  ? [
      {
        record_id: 'sample-0003',
        action: 'skill.submitted',
        actor_id: '示例操作者 01',
        target_type: 'skill',
        target_id: 'sample-summarize@1.0.0',
        phone_masked: null,
        detail: { skill_key: 'sample-summarize', version: '1.0.0', source_key: 'manual' },
        occurred_at: '2026-09-20T02:10:00Z',
      },
      {
        record_id: 'sample-0002',
        action: 'knowledge.doc.published',
        actor_id: '示例操作者 02',
        target_type: 'knowledge',
        target_id: 'sample-doc-published',
        phone_masked: null,
        detail: { document_id: 'sample-doc-published', status: 'published' },
        occurred_at: '2026-09-19T08:30:00Z',
      },
      {
        record_id: 'sample-0001',
        action: 'account.login.succeeded',
        actor_id: '示例操作者 01',
        target_type: 'account',
        target_id: '示例账号 01',
        phone_masked: '138****0000',
        detail: {},
        occurred_at: '2026-09-19T01:05:00Z',
      },
    ]
  : []

/** 开发期样例动作目录（**只用于下拉**；真实值以后端枚举为准）。 */
const MOCK_ACTIONS: string[] = import.meta.env.DEV
  ? ['account.login.succeeded', 'knowledge.doc.published', 'skill.submitted']
  : []

/** 样例模式下的"示例数据"标识（供页面直接引用，避免各处另写）。 */
export { SAMPLE_DATA_BADGE }