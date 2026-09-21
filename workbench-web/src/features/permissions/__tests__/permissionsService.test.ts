/**
 * 「权限配置」适配层用例（第 6 轮）。
 *
 * 覆盖口径（与 `docs/contracts/permissions-api.md` 逐条对应）：
 *  - 读：请求路径与参数逐字正确；目录分页截断必须抛错（不把残缺列表当全量）；未知状态抛错（不误标）；
 *  - 写：`PUT` + 请求体**只有** `knowledge_base_ids`（后端 `extra="forbid"`）；
 *  - 失败分类：`403` ⇒ `forbidden` / `409` ⇒ `conflict`（未纳管，保留服务端原文）/
 *    `422`（`detail` 是数组）⇒ `invalid`（回落本地固定文案，**绝不渲染校验 JSON**）；
 *  - 样例模式：**不伪造服务端回读值**（`binding === null`）、`written === false`。
 */
import { ServiceError } from '../../../utils/serviceKit'
import { MAX_KNOWLEDGE_BASE_IDS, normalizeIds, unknownCandidateIds, validateIds } from '../types'
import {
  MOCK_WRITE_NOTE,
  ScopeWriteError,
  WRITE_FAILURE_HINT,
  fetchAgentScopes,
  fetchAudits,
  fetchRoleScopes,
  listKnowledgeBases,
  saveScopeBinding,
  setServiceMode,
} from '../services/permissionsService'

/**
 * 最小 `fetch` 桩（与工作台用例同口径）：只实现请求层用到的三样，记录 `(url, init)`，
 * 供"请求路径 / 方法与请求体逐字正确"的断言使用。
 */
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

const ROLE_VIEW = (over: Partial<Record<string, unknown>> = {}) => ({
  role_key: 'ops',
  name: '运营',
  description: '内容生产与发布准备。',
  status: 'active',
  created_by: 'acct-0001',
  created_at: '2026-09-10T09:00:00Z',
  updated_at: '2026-09-19T09:00:00Z',
  ...over,
})

const AGENT_VIEW = {
  agent_key: 'content-ops',
  name: '内容运营助手',
  description: '负责选题与草稿。',
  role_key: 'ops',
  status: 'active',
  created_by: 'acct-0001',
  created_at: null,
  updated_at: null,
}

describe('permissionsService（读路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('角色块：先取目录再逐行取绑定，路径与分页参数逐字正确', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/workforce/roles': {
        body: { items: [ROLE_VIEW(), ROLE_VIEW({ role_key: 'finance', name: '财务', status: 'disabled' })], total: 2, limit: 200, offset: 0 },
      },
      '/api/v1/knowledge-access/roles/ops': {
        body: { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: ['kb-brand-assets'] },
      },
      '/api/v1/knowledge-access/roles/finance': {
        body: { binding_type: 'role', binding_key: 'finance', knowledge_base_ids: [] },
      },
    })

    const page = await fetchRoleScopes(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/workforce/roles?limit=200&offset=0')
    expect(calls.map((call) => call.url).sort()).toEqual([
      '/api/v1/knowledge-access/roles/finance',
      '/api/v1/knowledge-access/roles/ops',
      '/api/v1/workforce/roles?limit=200&offset=0',
    ])
    expect(page.sample).toBe(false)
    expect(page.rows).toEqual([
      {
        binding_type: 'role',
        binding_key: 'ops',
        name: '运营',
        status: 'active',
        knowledge_base_ids: ['kb-brand-assets'],
      },
      {
        binding_type: 'role',
        binding_key: 'finance',
        name: '财务',
        status: 'disabled',
        knowledge_base_ids: [],
      },
    ])
  })

  it('数字员工块：路径走 agents，字段名与角色块同形（逐行取绑定）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/workforce/agents': { body: { items: [AGENT_VIEW], total: 1, limit: 200, offset: 0 } },
      '/api/v1/knowledge-access/agents/content-ops': {
        body: { binding_type: 'agent', binding_key: 'content-ops', knowledge_base_ids: ['kb-brand-assets'] },
      },
    })

    const page = await fetchAgentScopes(fetchImpl)

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/workforce/agents?limit=200&offset=0',
      '/api/v1/knowledge-access/agents/content-ops',
    ])
    expect(page.rows[0]).toEqual({
      binding_type: 'agent',
      binding_key: 'content-ops',
      name: '内容运营助手',
      status: 'active',
      knowledge_base_ids: ['kb-brand-assets'],
    })
  })

  it('目录超过单页上限：抛错，不把残缺列表当全量', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/workforce/roles': { body: { items: [ROLE_VIEW()], total: 300, limit: 200, offset: 0 } },
    })

    await expect(fetchRoleScopes(fetchImpl)).rejects.toBeInstanceOf(ServiceError)
    await expect(fetchRoleScopes(fetchImpl)).rejects.toThrow(/不展示残缺/)
  })

  it('后端返回未定义的目录状态：抛错，不误标成"已启用 / 已停用"', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/workforce/roles': { body: { items: [ROLE_VIEW({ status: 'archived' })], total: 1, limit: 200, offset: 0 } },
      '/api/v1/knowledge-access/roles/ops': {
        body: { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: [] },
      },
    })

    await expect(fetchRoleScopes(fetchImpl)).rejects.toThrow(/未定义的目录状态/)
  })

  it('403：映射为 forbidden（界面走"无权限"态，与"加载失败"分开）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/workforce/roles': { status: 403, body: { detail: '只有超级管理员可以管理岗位与数字员工目录' } },
    })

    const error = await fetchRoleScopes(fetchImpl).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ServiceError)
    expect((error as ServiceError).failure).toBe('forbidden')
  })

  it('变更记录：只读数组，`limit` 原样透传', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge-access/audits': {
        body: [
          {
            tenant_id: 't-0001',
            binding_type: 'role',
            binding_key: 'ops',
            old_knowledge_base_ids: [],
            new_knowledge_base_ids: ['kb-brand-assets'],
            actor_id: 'acct-0001',
            occurred_at: '2026-09-19T10:25:43Z',
          },
        ],
      },
    })

    const page = await fetchAudits(20, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/knowledge-access/audits?limit=20')
    expect(page.sample).toBe(false)
    expect(page.items[0].new_knowledge_base_ids).toEqual(['kb-brand-assets'])
  })
})

describe('permissionsService（写路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('成功：走 PUT，请求体只有 knowledge_base_ids；回读值取自服务端响应', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge-access/roles/ops': {
        body: { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: ['kb-a', 'kb-b'] },
      },
    })

    const result = await saveScopeBinding(
      { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: ['kb-a', 'kb-b'] },
      fetchImpl,
    )

    const write = calls.find((call) => call.init.method === 'PUT')
    expect(write?.url).toBe('/api/v1/knowledge-access/roles/ops')
    // `extra="forbid"`：请求体不得夹带其它字段
    expect(JSON.parse(String(write?.init.body))).toEqual({ knowledge_base_ids: ['kb-a', 'kb-b'] })
    expect(result.written).toBe(true)
    expect(result.binding?.knowledge_base_ids).toEqual(['kb-a', 'kb-b'])
  })

  it('409（未纳管）：就地保留服务端原文，分类为 conflict', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge-access/roles/evidence-ops': {
        status: 409,
        body: { detail: '该标识尚未纳入目录，请先在「数字员工设置」中纳管' },
      },
    })

    const error = await saveScopeBinding(
      { binding_type: 'role', binding_key: 'evidence-ops', knowledge_base_ids: ['kb-a'] },
      fetchImpl,
    ).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ScopeWriteError)
    expect((error as ScopeWriteError).kind).toBe('conflict')
    expect((error as ScopeWriteError).message).toBe('该标识尚未纳入目录，请先在「数字员工设置」中纳管')
    expect(WRITE_FAILURE_HINT.conflict).toMatch(/没有写入任何数据/)
  })

  it('422（detail 是数组）：回落本地固定文案，绝不渲染校验 JSON', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge-access/roles/ops': {
        status: 422,
        body: { detail: [{ type: 'extra_forbidden', loc: ['body', 'extra'], msg: 'Extra inputs are not permitted' }] },
      },
    })

    const error = await saveScopeBinding(
      { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: [] },
      fetchImpl,
    ).catch((caught: unknown) => caught)

    expect((error as ScopeWriteError).kind).toBe('invalid')
    expect((error as ScopeWriteError).message).toBe('请求参数不合法，已拒绝。')
    expect((error as ScopeWriteError).message).not.toMatch(/extra_forbidden|Extra inputs/)
  })

  it('403（非超管）：分类为 forbidden', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge-access/roles/ops': {
        status: 403,
        body: { detail: '只有超级管理员可以调整知识库范围' },
      },
    })

    const error = await saveScopeBinding(
      { binding_type: 'role', binding_key: 'ops', knowledge_base_ids: [] },
      fetchImpl,
    ).catch((caught: unknown) => caught)

    expect((error as ScopeWriteError).kind).toBe('forbidden')
    expect((error as ScopeWriteError).message).toBe('只有超级管理员可以调整知识库范围')
  })

  it('样例模式：不伪造服务端回读值（binding 为 null）、written 为 false', async () => {
    setServiceMode('mock')

    const result = await saveScopeBinding({
      binding_type: 'role',
      binding_key: 'ops',
      knowledge_base_ids: ['kb-brand-assets'],
    })

    expect(result.written).toBe(false)
    expect(result.binding).toBeNull()
    expect(result.note).toBe(MOCK_WRITE_NOTE)
    expect(MOCK_WRITE_NOTE).toMatch(/没有写入任何数据/)
  })
})

describe('知识库候选清单 listKnowledgeBases（第 15 轮新增端点）', () => {
  beforeEach(() => {
    setServiceMode('http')
  })
  afterEach(() => {
    setServiceMode('mock')
  })

  it('请求路径逐字正确，形状合规时原样返回', async () => {
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/knowledge/bases': {
        body: {
          upstream_available: true,
          source: 'upstream',
          items: [{ knowledge_base_id: 'kb-a', name: '知识库 A', origin: 'upstream' }],
          note: null,
        },
      },
    })

    const list = await listKnowledgeBases(fetchImpl)

    expect(calls[0].url).toContain('/api/v1/knowledge/bases')
    expect(list.items).toEqual([{ knowledge_base_id: 'kb-a', name: '知识库 A', origin: 'upstream' }])
  })

  it('降级（upstream_available=false）带 note ⇒ 原样返回（界面据此如实提示）', async () => {
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/bases': {
        body: {
          upstream_available: false,
          source: 'local_only',
          items: [{ knowledge_base_id: 'kb-old', name: null, origin: 'binding_only' }],
          note: '未能获取知识库清单（未配置知识库服务），以下为本租户已绑定过的标识；可直接输入标识。',
        },
      },
    })

    const list = await listKnowledgeBases(fetchImpl)

    expect(list.upstream_available).toBe(false)
    expect(list.note).toMatch(/未能获取知识库清单/)
  })

  it('降级却不带 note ⇒ 抛错（不静默返回空清单冒充"没有知识库"）', async () => {
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/bases': {
        body: { upstream_available: false, source: 'local_only', items: [], note: null },
      },
    })

    await expect(listKnowledgeBases(fetchImpl)).rejects.toBeInstanceOf(ServiceError)
  })

  it('形状不符（缺 knowledge_base_id）⇒ 抛错（不展示臆测内容）', async () => {
    const { fetchImpl } = stubFetch({
      '/api/v1/knowledge/bases': {
        body: {
          upstream_available: true,
          source: 'upstream',
          items: [{ name: '没有标识', origin: 'upstream' }],
          note: null,
        },
      },
    })

    await expect(listKnowledgeBases(fetchImpl)).rejects.toBeInstanceOf(ServiceError)
  })
})

describe('知识库标识的候选校验（纯函数）', () => {
  it('规范化：去空白 + 去重（保持首次出现顺序）', () => {
    expect(normalizeIds([' kb-a ', 'kb-a', '', 'kb-b'])).toEqual(['kb-a', 'kb-b'])
  })

  it('"不在清单里"只认 upstream 项：binding_only 与手输值都要被提醒出来', () => {
    const items = [
      { knowledge_base_id: 'kb-a', name: null, origin: 'upstream' as const },
      { knowledge_base_id: 'kb-old', name: null, origin: 'binding_only' as const },
    ]

    // kb-a 在清单里 ⇒ 不提醒；kb-old（绑定里有、清单没返回）与 kb-new（全新手输）都要提醒
    expect(unknownCandidateIds(['kb-a', 'kb-old', ' kb-new ', 'kb-new'], items)).toEqual(['kb-old', 'kb-new'])
  })

  it('校验：空项被拒；超过 100 项被拒（服务端 max_length=100）；100 项通过', () => {
    expect(validateIds(['kb-a'])).toBeNull()
    expect(validateIds(['kb-a', '   '])).toMatch(/不能为空/)
    expect(validateIds(Array.from({ length: MAX_KNOWLEDGE_BASE_IDS + 1 }, (_, index) => `kb-${index}`))).toMatch(
      /最多 100/,
    )
    expect(
      validateIds(Array.from({ length: MAX_KNOWLEDGE_BASE_IDS }, (_, index) => `kb-${index}`)),
    ).toBeNull()
    expect(MAX_KNOWLEDGE_BASE_IDS).toBe(100)
  })
})