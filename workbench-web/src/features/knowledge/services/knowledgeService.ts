/**
 * 「知识库」适配层 —— 本模块**唯一**的接线点（页面与组件都不认识 URL）。
 *
 * 第 7 轮实测（2026-09-19 真机 `127.0.0.1:18112` + 真库 + 本机知识服务实例，治理开关已开）：
 *  - 读：`GET /api/v1/knowledge/documents`（`status` 可选、`limit` 1–200、`offset`）、
 *        `GET /api/v1/knowledge/metrics`、`GET /api/v1/knowledge/governance/eligible`；
 *  - 写：`POST /api/v1/knowledge/documents`（**幂等**；请求体 `extra="forbid"`，只允许
 *        `document_id/title/owner_id/version/source_key`）、
 *        `POST …/{id}/publish`、`POST …/{id}/archive`、
 *        `POST …/{id}/review?approved=<bool>`（**`approved` 走 query 且必填**）、
 *        `POST /api/v1/knowledge/review-scan`（幂等，返回 `{"reviewed_due": n}`）；
 *  - 检索：`POST /api/v1/knowledge/search`（body `{query, role_key|agent_key, limit}`，**恰一**）；
 *        未配置知识服务 ⇒ `503`（**不是空结果**）；白名单为空 ⇒ `200 items=[] reason="empty_whitelist"`；
 *  - **实测门禁**：上述全部端点对 `employee` 一律 `403` ⇒ 本模块按"非超管 = 无权限"呈现（契约 §5）。
 *
 * 纪律（改这个文件前先读）：
 *  ① 样例数据只在**开发模式**存在（`import.meta.env.DEV`）⇒ 生产构建里整块被摇掉；
 *  ② `http` 分支**必须抛错或返回真实数据**，不得静默返回空数组冒充"真的没有内容"；
 *  ③ 写失败必须分类（`forbidden` / `conflict` / `invalid` / `failed`）并保留请求层已 sanitize 的文案，
 *     界面据此**就地呈现**且**不假装成功**；成功只用**服务端回读值**提示；
 *  ④ 未来接线只改这一个文件。
 */
import { ApiError, request } from '../../../api/client'
import { SAMPLE_DATA_BADGE, ServiceError, resolveServiceMode } from '../../../utils/serviceKit'
import type {
  Citation,
  DocumentPage,
  EligiblePage,
  GovernanceMetrics,
  KnowledgeDoc,
  MetricsPage,
  RegisterInput,
  ReviewScanOutcome,
  SearchInput,
  SearchOutcome,
  SearchReason,
  WriteOutcome,
} from '../types'
import { parseDocumentStatus } from '../types'

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

/** 文档列表单页上限（后端 `limit` 上限 200）。 */
export const DOCUMENTS_LIMIT = 200
/** 检索默认条数（后端 `limit` 1–50，默认 10）。 */
export const SEARCH_LIMIT = 10

const DOCUMENTS_PATH = '/api/v1/knowledge/documents'
const METRICS_PATH = '/api/v1/knowledge/metrics'
const ELIGIBLE_PATH = '/api/v1/knowledge/governance/eligible'
const REVIEW_SCAN_PATH = '/api/v1/knowledge/review-scan'
const SEARCH_PATH = '/api/v1/knowledge/search'

/** 写成功的如实说明（后端已确认写入；回读值取自服务端响应）。 */
export const WRITE_OK_NOTE = '操作已受理。'

/**
 * 样例模式下的写说明（**只在开发期存在**，生产构建里为空串）。
 * 措辞避免开发术语，只说"没有写入任何数据"。
 */
export const MOCK_WRITE_NOTE: string = import.meta.env.DEV
  ? '当前为示例数据（未接后端），本次操作没有写入任何数据。'
  : ''

/** 已接入真实数据时的说明（与「示例数据」标识互斥，避免含糊）。 */
export const CONNECTED_NOTICE = '已接入真实数据'
export const CONNECTED_DESCRIPTION =
  '文档、指标与可检索清单均来自服务端；发布 / 归档 / 复核每次都会记录，且以服务端判定为准。'

/** 样例模式下的说明（**只在开发期存在** ⇒ 生产构建里为空串，"示例数据"字样不进产物）。 */
export const SAMPLE_DESCRIPTION: string = import.meta.env.DEV
  ? '本页文档、指标与可检索清单均为示例数据，不会写入任何数据。'
  : ''

/** 样例模式下的到期扫描说明（同上，只在开发期存在）。 */
export const MOCK_SCAN_NOTE: string = import.meta.env.DEV
  ? `${SAMPLE_DATA_BADGE}，本次扫描没有改变任何文档。`
  : ''

/** 「文档列表」空态：解释**为什么空**，而不是显示"0 条文档"。 */
export const DOCUMENTS_EMPTY_NOTE =
  '本租户还没有登记任何文档；登记并发布后才可被检索。'

/** 「可检索文档」空态：说明"需先发布"。 */
export const ELIGIBLE_EMPTY_NOTE = '当前没有可检索文档（需先发布）。'

/** 指标全为 0 时的说明：**0 是真实值**，但要说清原因（不显示"没有数据"式含糊文案）。 */
export const METRICS_ZERO_NOTE = '本租户还没有登记任何文档，因此指标均为 0（这是真实值）。'

/** 列表被单页上限截断时的如实说明（不把残缺列表当全量）。 */
export function truncationNote(total: number, shown: number): string | undefined {
  return total > shown ? `共 ${total} 篇文档，本页只展示前 ${shown} 篇。` : undefined
}

/** 检索空结果归因文案（三种归因**必须分开**，不允许合并成"没查到"）。 */
export const SEARCH_EMPTY_WHITELIST_NOTE =
  '当前没有已发布的可检索文档：请先在「文档列表」登记文档并发布，再重新检索。'
export const SEARCH_NO_BINDING_NOTE =
  '该岗位或数字员工尚未绑定任何知识库，检索范围为空；请先在「权限配置」中配置知识范围。'
export const SEARCH_NO_HITS_NOTE = '已发布文档中没有匹配的内容，请更换关键词后重试。'
export const SEARCH_NOT_CONFIGURED_NOTE =
  '检索服务未接入：当前环境未配置知识检索，暂时无法执行检索（这不是"没有查到"）。'

/** 写失败分类：界面据此给出**不同的**可懂原因，而不是笼统的"操作失败"。 */
export type KnowledgeFailure = 'forbidden' | 'conflict' | 'invalid' | 'not_configured' | 'failed'

/**
 * 适配层错误（只带可读文案与分类，**不含**凭据 / 内部地址 / 堆栈）。
 *
 * 文案来源：请求层优先取服务端 `detail`（仅当它是"短且干净"的字符串），
 * 否则回落本地固定文案 —— 因此 `422`（`detail` 是数组）**不会**把校验 JSON 渲染到界面。
 */
export class KnowledgeError extends ServiceError {
  readonly kind: KnowledgeFailure

  constructor(message: string, kind: KnowledgeFailure) {
    super(
      message,
      kind === 'forbidden' ? 'forbidden' : kind === 'not_configured' ? 'not_connected' : 'failed',
    )
    this.name = 'KnowledgeError'
    this.kind = kind
  }
}

/** 写失败的就地提示（**必须说明"没有写入任何数据"**，不允许含糊成"操作失败"）。 */
export const WRITE_FAILURE_HINT: Record<Exclude<KnowledgeFailure, 'not_configured'>, string> = {
  forbidden: '本次没有写入任何数据；如需管理知识文档，请使用超级管理员账号。',
  conflict: '本次没有写入任何数据；该操作与文档当前状态冲突，请刷新后重试。',
  invalid: '本次没有写入任何数据；请检查填写内容后重试。',
  failed: '本次没有写入任何数据，请稍后重试。',
}

/** 取数失败 → 界面四态：`forbidden` / `not_configured`（未接入）单独区分，其余按"加载失败"。 */
export function panelStateOfError(error: unknown): 'error' | 'forbidden' | 'not_configured' {
  if (error instanceof KnowledgeError) {
    if (error.kind === 'forbidden') return 'forbidden'
    if (error.kind === 'not_configured') return 'not_configured'
  }
  if (error instanceof ServiceError && error.failure === 'forbidden') return 'forbidden'
  return 'error'
}

/** 读路径失败 → 模块错误（非请求层错误原样抛出，不吞异常）。`503` 仅在检索链路按"未接入"处理。 */
function readError(error: unknown, options?: { treat503AsNotConfigured?: boolean }): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new KnowledgeError(error.message, 'forbidden')
    if (options?.treat503AsNotConfigured && error.status === 503) {
      throw new KnowledgeError(error.message, 'not_configured')
    }
    throw new KnowledgeError(error.message, 'failed')
  }
  throw error
}

/** 写路径失败 → 模块错误（分类见 `KnowledgeFailure`）。 */
function writeError(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.failure === 'forbidden') throw new KnowledgeError(error.message, 'forbidden')
    if (error.failure === 'conflict') throw new KnowledgeError(error.message, 'conflict')
    if (error.status === 422) throw new KnowledgeError(error.message, 'invalid')
    throw new KnowledgeError(error.message, 'failed')
  }
  throw error
}

/** 形状不符统一文案（**绝不臆测**成"没有内容"）。 */
const SHAPE_ERROR = '服务端返回的内容形状不符合约定，本模块不展示该内容。'

/** 单条文档视图 → 模块类型；缺必需键即抛错（不静默跳过、不编造字段）。 */
function toDoc(raw: unknown): KnowledgeDoc {
  const value = raw as Partial<KnowledgeDoc> | null
  if (!value || typeof value.document_id !== 'string' || typeof value.title !== 'string') {
    throw new KnowledgeError(SHAPE_ERROR, 'failed')
  }
  return {
    document_id: value.document_id,
    title: value.title,
    owner_id: typeof value.owner_id === 'string' ? value.owner_id : '',
    status: parseDocumentStatus(typeof value.status === 'string' ? value.status : ''),
    version: typeof value.version === 'string' ? value.version : '',
    source_key: typeof value.source_key === 'string' ? value.source_key : '',
    last_reviewed_at: value.last_reviewed_at ?? null,
    review_due_at: value.review_due_at ?? null,
    registered_by: typeof value.registered_by === 'string' ? value.registered_by : '',
    created_at: value.created_at ?? null,
    updated_at: value.updated_at ?? null,
  }
}

/** 列表视图 → `KnowledgeDoc[]`（`items` 不是数组即抛错）。 */
function toDocs(raw: unknown): KnowledgeDoc[] {
  const items = (raw as { items?: unknown } | null)?.items
  if (!Array.isArray(items)) throw new KnowledgeError(SHAPE_ERROR, 'failed')
  return items.map(toDoc)
}

/** 指标视图 → 受控结构（必需键缺失即抛错，不用 0 兜底 —— 0 会被读成"真的是 0"）。 */
function toMetrics(raw: unknown): GovernanceMetrics {
  const value = raw as Partial<GovernanceMetrics> | null
  const keys = ['published', 'needs_review', 'archived', 'total', 'freshness_ratio'] as const
  if (!value || keys.some((key) => typeof value[key] !== 'number')) {
    throw new KnowledgeError(SHAPE_ERROR, 'failed')
  }
  return {
    published: value.published as number,
    needs_review: value.needs_review as number,
    archived: value.archived as number,
    total: value.total as number,
    freshness_ratio: value.freshness_ratio as number,
  }
}

/** 检索归因 → 受控枚举；未知取值落 `null`（当作"未归因"，界面按普通空结果呈现，不臆测原因）。 */
function toReason(raw: unknown): SearchReason {
  return raw === 'no_binding' || raw === 'empty_whitelist' || raw === 'no_hits' ? raw : null
}

/** 文档列表（`status` 可选、分页）。 */
export async function fetchDocuments(
  params: { status?: string; limit?: number; offset?: number } = {},
  fetchImpl?: typeof fetch,
): Promise<DocumentPage> {
  if (mode === 'mock') return { sample: true, items: MOCK_DOCS, total: MOCK_DOCS.length, limit: DOCUMENTS_LIMIT, offset: 0 }

  try {
    const raw = await request<unknown>(DOCUMENTS_PATH, {
      query: {
        ...(params.status ? { status: params.status } : {}),
        limit: params.limit ?? DOCUMENTS_LIMIT,
        offset: params.offset ?? 0,
      },
      fetchImpl,
    })
    const view = raw as { total?: unknown; limit?: unknown; offset?: unknown }
    const items = toDocs(raw)
    return {
      sample: false,
      items,
      total: typeof view.total === 'number' ? view.total : items.length,
      limit: typeof view.limit === 'number' ? view.limit : DOCUMENTS_LIMIT,
      offset: typeof view.offset === 'number' ? view.offset : 0,
    }
  } catch (error) {
    readError(error)
  }
}

/** 治理指标（Freshness Index）。 */
export async function fetchMetrics(fetchImpl?: typeof fetch): Promise<MetricsPage> {
  if (mode === 'mock') return { sample: true, metrics: MOCK_METRICS }

  try {
    const raw = await request<unknown>(METRICS_PATH, { fetchImpl })
    return { sample: false, metrics: toMetrics(raw) }
  } catch (error) {
    readError(error)
  }
}

/** 可检索（已发布且未过复核期）清单。 */
export async function fetchEligible(fetchImpl?: typeof fetch): Promise<EligiblePage> {
  if (mode === 'mock') return { sample: true, items: MOCK_ELIGIBLE, total: MOCK_ELIGIBLE.length }

  try {
    const raw = await request<unknown>(ELIGIBLE_PATH, { fetchImpl })
    const items = toDocs(raw)
    const total = (raw as { total?: unknown }).total
    return { sample: false, items, total: typeof total === 'number' ? total : items.length }
  } catch (error) {
    readError(error)
  }
}

/** 登记文档（只登记元数据，**无正文**；后端幂等）。成功返回**服务端回读值**。 */
export async function registerDocument(input: RegisterInput, fetchImpl?: typeof fetch): Promise<WriteOutcome> {
  if (mode === 'mock') {
    // 样例模式没有服务端 ⇒ 不伪造回读值，且明确"没有写入任何数据"
    return { doc: null, written: false, note: MOCK_WRITE_NOTE }
  }

  try {
    const raw = await request<unknown>(DOCUMENTS_PATH, {
      method: 'POST',
      // 后端 `extra="forbid"`：请求体只放后端允许的五个键
      body: {
        document_id: input.document_id,
        title: input.title,
        owner_id: input.owner_id ?? '',
        version: input.version ?? '1',
        source_key: input.source_key ?? 'manual',
      },
      fetchImpl,
    })
    return { doc: toDoc(raw), written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    writeError(error)
  }
}

/** 单个文档的管理动作路径。 */
function documentActionPath(document_id: string, action: 'publish' | 'archive' | 'review'): string {
  return `${DOCUMENTS_PATH}/${encodeURIComponent(document_id)}/${action}`
}

/** 发布（服务端闸门：`draft` + 已指定负责人；未指定 ⇒ `422`）。 */
export async function publishDocument(document_id: string, fetchImpl?: typeof fetch): Promise<WriteOutcome> {
  return writeDocAction(documentActionPath(document_id, 'publish'), {}, fetchImpl)
}

/** 归档（`archived` 为**终态**，不可恢复）。 */
export async function archiveDocument(document_id: string, fetchImpl?: typeof fetch): Promise<WriteOutcome> {
  return writeDocAction(documentActionPath(document_id, 'archive'), {}, fetchImpl)
}

/** 复核（人工事件）：`approved=true` → published 并刷新复核期；`false` → archived。 */
export async function reviewDocument(
  document_id: string,
  approved: boolean,
  fetchImpl?: typeof fetch,
): Promise<WriteOutcome> {
  return writeDocAction(documentActionPath(document_id, 'review'), { query: { approved } }, fetchImpl)
}

/** 三个单文档动作共用的写路径（只在开发期落到"没有写入任何数据"）。 */
async function writeDocAction(
  path: string,
  extra: { query?: Record<string, string | number | boolean> },
  fetchImpl?: typeof fetch,
): Promise<WriteOutcome> {
  if (mode === 'mock') return { doc: null, written: false, note: MOCK_WRITE_NOTE }

  try {
    const raw = await request<unknown>(path, { method: 'POST', query: extra.query, fetchImpl })
    return { doc: toDoc(raw), written: true, note: WRITE_OK_NOTE }
  } catch (error) {
    writeError(error)
  }
}

/** 触发到期扫描（`published` 且过期 ⇒ `needs_review`；幂等）。 */
export async function runReviewScan(fetchImpl?: typeof fetch): Promise<ReviewScanOutcome> {
  if (mode === 'mock') return { sample: true, reviewed_due: 0 }

  try {
    const raw = await request<unknown>(REVIEW_SCAN_PATH, { method: 'POST', fetchImpl })
    const count = (raw as { reviewed_due?: unknown } | null)?.reviewed_due
    if (typeof count !== 'number') throw new KnowledgeError(SHAPE_ERROR, 'failed')
    return { sample: false, reviewed_due: count }
  } catch (error) {
    writeError(error)
  }
}

/**
 * 检索：body 只有 `{query, role_key | agent_key, limit}`（**范围由服务端解析**，客户端不带租户 / 知识库 id）。
 * 未配置知识服务 ⇒ `503` ⇒ 分类为 `not_configured`（「服务未接入」，**不是空结果**）。
 */
export async function searchKnowledge(input: SearchInput, fetchImpl?: typeof fetch): Promise<SearchOutcome> {
  if (mode === 'mock') return { items: MOCK_CITATIONS, truncated: false, reason: null }

  const body: Record<string, unknown> = { query: input.query, limit: input.limit ?? SEARCH_LIMIT }
  if (input.agent_key) body.agent_key = input.agent_key
  else body.role_key = input.role_key ?? ''

  try {
    const raw = await request<unknown>(SEARCH_PATH, { method: 'POST', body, fetchImpl })
    const view = raw as { items?: unknown; truncated?: unknown; reason?: unknown } | null
    if (!view || !Array.isArray(view.items)) throw new KnowledgeError(SHAPE_ERROR, 'failed')
    return {
      items: view.items.map((item) => toCitation(item)),
      truncated: view.truncated === true,
      reason: toReason(view.reason),
    }
  } catch (error) {
    readError(error, { treat503AsNotConfigured: true })
  }
}

function toCitation(raw: unknown): Citation {
  const value = raw as Partial<Citation> | null
  if (!value || typeof value.citation_id !== 'string' || typeof value.content !== 'string') {
    throw new KnowledgeError(SHAPE_ERROR, 'failed')
  }
  return {
    citation_id: value.citation_id,
    content: value.content,
    source_title: typeof value.source_title === 'string' ? value.source_title : '',
    knowledge_id: typeof value.knowledge_id === 'string' ? value.knowledge_id : '',
    score: typeof value.score === 'number' ? value.score : null,
  }
}

/**
 * 开发期样例数据（虚构内容，无 PII：不含手机号 / 用户 ID / 租户 ID / 密钥）。
 * **只在 `import.meta.env.DEV` 分支里存在** ⇒ 生产构建里整块被摇掉（构建后 grep 应为 0 命中）。
 * 刻意覆盖四种状态（含终态与待复核）与"复核到期为空"，用于断言按钮可用性与"未设置"呈现。
 */
const MOCK_DOCS: KnowledgeDoc[] = import.meta.env.DEV
  ? [
      {
        document_id: 'sample-doc-draft',
        title: '示例文档：新员工入职指引',
        owner_id: '示例负责人 01',
        status: 'draft',
        version: '1',
        source_key: 'manual',
        last_reviewed_at: null,
        review_due_at: null,
        registered_by: '示例操作者 01',
        created_at: '2026-09-19T10:00:00Z',
        updated_at: '2026-09-19T10:00:00Z',
      },
      {
        document_id: 'sample-doc-published',
        title: '示例文档：运营手册',
        owner_id: '示例负责人 01',
        status: 'published',
        version: '2',
        source_key: 'manual',
        last_reviewed_at: '2026-09-19T10:00:00Z',
        review_due_at: '2026-10-19T10:00:00Z',
        registered_by: '示例操作者 01',
        created_at: '2026-09-18T10:00:00Z',
        updated_at: '2026-09-19T10:00:00Z',
      },
      {
        document_id: 'sample-doc-review',
        title: '示例文档：合规检查表',
        owner_id: '示例负责人 02',
        status: 'needs_review',
        version: '1',
        source_key: 'manual',
        last_reviewed_at: '2026-08-19T10:00:00Z',
        review_due_at: '2026-09-18T10:00:00Z',
        registered_by: '示例操作者 01',
        created_at: '2026-07-01T10:00:00Z',
        updated_at: '2026-08-19T10:00:00Z',
      },
      {
        document_id: 'sample-doc-archived',
        title: '示例文档：旧版制度',
        owner_id: '示例负责人 02',
        status: 'archived',
        version: '1',
        source_key: 'manual',
        last_reviewed_at: '2026-06-01T10:00:00Z',
        review_due_at: '2026-07-01T10:00:00Z',
        registered_by: '示例操作者 02',
        created_at: '2026-05-01T10:00:00Z',
        updated_at: '2026-06-01T10:00:00Z',
      },
    ]
  : []

const MOCK_METRICS: GovernanceMetrics = import.meta.env.DEV
  ? { published: 1, needs_review: 1, archived: 1, total: 4, freshness_ratio: 0.25 }
  : { published: 0, needs_review: 0, archived: 0, total: 0, freshness_ratio: 0 }

const MOCK_ELIGIBLE: KnowledgeDoc[] = import.meta.env.DEV
  ? MOCK_DOCS.filter((item) => item.status === 'published')
  : []

const MOCK_CITATIONS: Citation[] = import.meta.env.DEV
  ? [
      {
        citation_id: 'sample-citation-0001',
        content: '示例引用片段：运营手册中的流程说明。',
        source_title: '示例文档：运营手册',
        knowledge_id: 'sample-doc-published',
        score: 0.82,
      },
    ]
  : []