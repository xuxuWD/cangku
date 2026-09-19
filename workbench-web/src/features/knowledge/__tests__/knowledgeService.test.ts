/**
 * 「知识库」适配层用例（第 7 轮）。
 *
 * 覆盖口径（与 `docs/contracts/knowledge-api.md` 逐条对应）：
 *  - 读：请求路径与分页参数逐字正确；形状不符即抛错（不臆测、不静默补空）；
 *  - 写：登记请求体**只有**后端允许的五键（后端 `extra="forbid"`）；发布 / 归档 / 复核方法正确；
 *    复核的 `approved` 走 **query**（后端 `Query(...)` 必填）；
 *  - 失败分类：`403` ⇒ `forbidden`、`409` ⇒ `conflict`（保留服务端原文）、
 *    `422`（`detail` 是数组）⇒ `invalid`（回落本地固定文案，**绝不渲染校验 JSON**）；
 *  - 检索：`503` ⇒ `not_configured`（服务未接入，**不是空结果**）；`reason` 原样透传；
 *  - 状态机：未知状态**不误标**成已知状态；非法动作给原因（不是静默隐藏）；
 *  - 样例模式：**不伪造服务端回读值**（`doc === null`）、`written === false`。
 */
import { ServiceError } from '../../../utils/serviceKit'
import {
  MOCK_WRITE_NOTE,
  KnowledgeError,
  fetchDocuments,
  fetchEligible,
  fetchMetrics,
  registerDocument,
  publishDocument,
  archiveDocument,
  reviewDocument,
  runReviewScan,
  searchKnowledge,
  setServiceMode,
} from '../services/knowledgeService'
import { KNOWLEDGE_STATUS_LABEL, actionDisabledReason, parseDocumentStatus } from '../types'

/** 最小 `fetch` 桩（与工作台用例同口径）：记录 `(url, init)`，供逐字断言使用。 */
function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  return { calls, fetchImpl }
}

const DOC = (over: Partial<Record<string, unknown>> = {}) => ({
  document_id: 'doc-0001',
  title: '员工手册',
  owner_id: 'acct-0001',
  status: 'draft',
  version: '1',
  source_key: 'manual',
  last_reviewed_at: null,
  review_due_at: null,
  registered_by: 'acct-0001',
  created_at: '2026-09-19T10:00:00Z',
  updated_at: '2026-09-19T10:00:00Z',
  ...over,
})

describe('knowledgeService（读路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('文档列表：路径与分页参数逐字正确，返回服务端形状', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents': {
        body: { items: [DOC()], total: 1, limit: 50, offset: 0 },
      },
    })

    const page = await fetchDocuments({ limit: 50, offset: 0 }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge/documents?limit=50&offset=0')
    expect(page.sample).toBe(false)
    expect(page.total).toBe(1)
    expect(page.items[0].document_id).toBe('doc-0001')
    expect(page.items[0].status).toBe('draft')
  })

  it('文档列表：形状不符（缺 items）即抛错，不静默当空', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({ '/api/v1/knowledge/documents': { body: { total: 0 } } })

    await expect(fetchDocuments(undefined, fetchImpl)).rejects.toBeInstanceOf(ServiceError)
  })

  it('治理指标：四数 + freshness_ratio 原样取回', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/metrics': {
        body: { published: 1, needs_review: 0, archived: 1, total: 3, freshness_ratio: 0.3333333333333333 },
      },
    })

    const result = await fetchMetrics(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge/metrics')
    expect(result.metrics).toEqual({
      published: 1,
      needs_review: 0,
      archived: 1,
      total: 3,
      freshness_ratio: 0.3333333333333333,
    })
  })

  it('可检索清单：路径正确，只读列表', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/governance/eligible': {
        body: { items: [DOC({ status: 'published' })], total: 1, limit: 200, offset: 0 },
      },
    })

    const page = await fetchEligible(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge/governance/eligible')
    expect(page.items[0].status).toBe('published')
  })

  it('403：映射为 forbidden（界面走"无权限"态，与"加载失败"分开）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents': { status: 403, body: {} },
    })

    const error = await fetchDocuments(undefined, fetchImpl).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ServiceError)
    expect((error as ServiceError).failure).toBe('forbidden')
  })
})

describe('knowledgeService（写路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('登记：POST，请求体只含后端允许的键；回读值取自服务端响应', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents': { status: 201, body: DOC() },
    })

    const result = await registerDocument({ document_id: 'doc-0001', title: '员工手册' }, fetchImpl)

    const write = calls.find((call) => call.init.method === 'POST')
    expect(write?.url).toBe('/api/v1/knowledge/documents')
    // 后端 `extra="forbid"`：请求体不得夹带其它字段
    expect(JSON.parse(String(write?.init.body))).toEqual({
      document_id: 'doc-0001',
      title: '员工手册',
      owner_id: '',
      version: '1',
      source_key: 'manual',
    })
    expect(result.written).toBe(true)
    expect(result.doc?.status).toBe('draft')
  })

  it('发布 / 归档：方法 POST、路径含文档标识', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents/doc-0001/publish': { body: DOC({ status: 'published' }) },
      '/api/v1/knowledge/documents/doc-0001/archive': { body: DOC({ status: 'archived' }) },
    })

    const published = await publishDocument('doc-0001', fetchImpl)
    const archived = await archiveDocument('doc-0001', fetchImpl)

    expect(calls.map((call) => `${call.init.method} ${call.url}`)).toEqual([
      'POST /api/v1/knowledge/documents/doc-0001/publish',
      'POST /api/v1/knowledge/documents/doc-0001/archive',
    ])
    expect(published.doc?.status).toBe('published')
    expect(archived.doc?.status).toBe('archived')
  })

  it('复核：`approved` 走 query（后端必填），true / false 各一条', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents/doc-0001/review': { body: DOC({ status: 'published' }) },
    })

    await reviewDocument('doc-0001', true, fetchImpl)
    await reviewDocument('doc-0001', false, fetchImpl)

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/knowledge/documents/doc-0001/review?approved=true',
      '/api/v1/knowledge/documents/doc-0001/review?approved=false',
    ])
    for (const call of calls) expect(call.init.method).toBe('POST')
  })

  it('到期扫描：POST，取回 reviewed_due', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/review-scan': { body: { reviewed_due: 1 } },
    })

    const result = await runReviewScan(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge/review-scan')
    expect(calls[0].init.method).toBe('POST')
    expect(result.reviewed_due).toBe(1)
  })

  it('409（状态冲突）：保留服务端原文，分类为 conflict', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents/doc-0001/publish': {
        status: 409,
        body: { detail: '当前状态不能发布（仅 draft 可发布）' },
      },
    })

    const error = await publishDocument('doc-0001', fetchImpl).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(KnowledgeError)
    expect((error as KnowledgeError).kind).toBe('conflict')
    expect((error as KnowledgeError).message).toBe('当前状态不能发布（仅 draft 可发布）')
  })

  it('422（detail 是数组）：回落本地固定文案，绝不渲染校验 JSON', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents': {
        status: 422,
        body: { detail: [{ type: 'string_too_short', loc: ['body', 'document_id'], msg: 'String should have at least 1 character' }] },
      },
    })

    const error = await registerDocument({ document_id: '', title: '' }, fetchImpl).catch(
      (caught: unknown) => caught,
    )

    expect((error as KnowledgeError).kind).toBe('invalid')
    expect((error as KnowledgeError).message).toBe('请求参数不合法，已拒绝。')
    expect((error as KnowledgeError).message).not.toMatch(/string_too_short|String should/)
  })

  it('403（非超管）：分类为 forbidden', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/documents': { status: 403, body: {} },
    })

    const error = await registerDocument({ document_id: 'doc-1', title: 'x' }, fetchImpl).catch(
      (caught: unknown) => caught,
    )
    expect((error as KnowledgeError).kind).toBe('forbidden')
  })

  it('样例模式：不伪造服务端回读值（doc 为 null）、written 为 false', async () => {
    setServiceMode('mock')

    const result = await registerDocument({ document_id: 'doc-1', title: 'x' })

    expect(result.written).toBe(false)
    expect(result.doc).toBeNull()
    expect(result.note).toBe(MOCK_WRITE_NOTE)
    expect(MOCK_WRITE_NOTE).toMatch(/没有写入任何数据/)
  })
})

describe('knowledgeService（检索）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('检索：请求体只含 query / role_key / limit，reason 原样透传', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/search': {
        body: {
          items: [
            { citation_id: 'c-1', content: '片段', source_title: '员工手册', knowledge_id: 'doc-0001', score: 0.5 },
          ],
          total: 1,
          limit: 10,
          truncated: false,
          reason: null,
        },
      },
    })

    const result = await searchKnowledge({ query: '合规', role_key: 'evidence-ops', limit: 10 }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge/search')
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      query: '合规',
      role_key: 'evidence-ops',
      limit: 10,
    })
    expect(result.items).toHaveLength(1)
    expect(result.reason).toBeNull()
  })

  it('检索：白名单为空（fail-closed）时 reason=empty_whitelist 且 items 为空', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/search': {
        body: { items: [], total: 0, limit: 10, truncated: false, reason: 'empty_whitelist' },
      },
    })

    const result = await searchKnowledge({ query: '合规', role_key: 'evidence-ops' }, fetchImpl)

    expect(result.items).toEqual([])
    expect(result.reason).toBe('empty_whitelist')
  })

  it('检索：503 ⇒ not_configured（服务未接入，不是空结果）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/search': { status: 503, body: { detail: '知识检索服务未启用' } },
    })

    const error = await searchKnowledge({ query: '合规', role_key: 'evidence-ops' }, fetchImpl).catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(KnowledgeError)
    expect((error as KnowledgeError).kind).toBe('not_configured')
  })
})

describe('状态机与状态解析（纯函数）', () => {
  it('已知状态照实映射；未知取值不误标成已知状态', () => {
    expect(parseDocumentStatus('draft')).toBe('draft')
    expect(parseDocumentStatus('published')).toBe('published')
    expect(parseDocumentStatus('needs_review')).toBe('needs_review')
    expect(parseDocumentStatus('archived')).toBe('archived')
    expect(parseDocumentStatus('under_review')).toBe('unknown')
    expect(parseDocumentStatus('')).toBe('unknown')
    expect(KNOWLEDGE_STATUS_LABEL.draft).toBe('草稿')
  })

  it('动作可用性由前置状态决定，不合法一律给原因（不静默隐藏）', () => {
    expect(actionDisabledReason('publish', 'draft')).toBeNull()
    expect(actionDisabledReason('publish', 'published')).toMatch(/仅|只有/)
    expect(actionDisabledReason('publish', 'archived')).toMatch(/归档/)
    expect(actionDisabledReason('archive', 'draft')).toBeNull()
    expect(actionDisabledReason('archive', 'published')).toBeNull()
    expect(actionDisabledReason('archive', 'needs_review')).toBeNull()
    expect(actionDisabledReason('archive', 'archived')).toMatch(/终态/)
    expect(actionDisabledReason('review_approve', 'needs_review')).toBeNull()
    expect(actionDisabledReason('review_reject', 'needs_review')).toBeNull()
    expect(actionDisabledReason('review_approve', 'published')).toMatch(/复核/)
    expect(actionDisabledReason('review_approve', 'archived')).toMatch(/归档/)
    // 未知状态：任何动作都不可执行，并给原因
    expect(actionDisabledReason('publish', 'unknown')).toMatch(/状态/)
    expect(actionDisabledReason('archive', 'unknown')).toMatch(/状态/)
    expect(actionDisabledReason('review_approve', 'unknown')).toMatch(/状态/)
  })
})