/**
 * 绑定面适配层用例（第 9 轮）。
 *
 * 覆盖口径（与 `docs/contracts/skill-bindings-api.md` §1/§2 逐条对应）：
 *  - 读：`GET /api/v1/skills/bindings` 路径与查询参数逐字正确（`skill_key` / `agent_key` / 分页）；
 *  - 写：绑定请求体**只有**后端允许的两键（`extra="forbid"`）；解绑走 `DELETE` + **query**；
 *  - 工具面：`GET /skills/agents/{agent_key}/tools` 路径逐字正确（含路径段编码）；
 *  - 员工候选：`GET /workforce/agents?status=active`；**目录为空是正常状态**（不抛错）；
 *  - 失败分类：`403` ⇒ `forbidden`、`404`（解绑不存在的绑定）⇒ `not_found`；
 *  - 样例模式：不发任何请求，绑定 / 解绑 `written === false` 且**不伪造回读值**。
 */
import {
  MOCK_BINDING_WRITE_NOTE,
  SkillError,
  bindAgentSkill,
  fetchAgentCandidates,
  fetchAgentTools,
  fetchBindings,
  setServiceMode,
  unbindAgentSkill,
} from '../services/skillsService'
import { agentToolsReason, parseBindingStatus } from '../types'
import type { SkillBinding, SkillSummary } from '../types'

/** 最小 `fetch` 桩（与技能包面用例同口径）：记录 `(url, init)` 供逐字断言。 */
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

const BINDING = (over: Partial<Record<string, unknown>> = {}) => ({
  skill_key: 'summarize',
  agent_key: 'agent-1',
  status: 'active',
  created_by: 'acct-admin',
  created_at: '2026-09-20T06:00:00Z',
  ...over,
})

describe('绑定面读路径', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('绑定列表：路径与查询参数逐字正确，返回服务端形状', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { body: { items: [BINDING()], total: 1, limit: 200, offset: 0 } },
    })

    const page = await fetchBindings({ limit: 200, offset: 0 }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/bindings?limit=200&offset=0')
    expect(page.sample).toBe(false)
    expect(page.total).toBe(1)
    expect(page.items[0]).toEqual({
      skill_key: 'summarize',
      agent_key: 'agent-1',
      status: 'active',
      created_by: 'acct-admin',
      created_at: '2026-09-20T06:00:00Z',
    })
    // 响应里的 tenant_id 不进入模块类型（最小化）
    expect('tenant_id' in page.items[0]).toBe(false)
  })

  it('绑定列表：过滤参数进 query（agent_key / skill_key）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { body: { items: [], total: 0, limit: 200, offset: 0 } },
    })

    await fetchBindings({ agent_key: 'agent-1', skill_key: 'summarize' }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/bindings?skill_key=summarize&agent_key=agent-1&limit=200&offset=0')
  })

  it('绑定列表：形状不符（items 不是数组）⇒ 抛错，绝不静默当成空列表', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({ '/api/v1/skills/bindings': { body: { total: 2 } } })

    await expect(fetchBindings({}, fetchImpl)).rejects.toBeInstanceOf(SkillError)
  })

  it('绑定列表：403 ⇒ `forbidden`（非 super_admin 不得读绑定关系）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { status: 403, body: { detail: '只有超级管理员可以绑定或解绑技能' } },
    })

    const error = (await fetchBindings({}, fetchImpl).catch((caught: unknown) => caught)) as SkillError

    expect(error.kind).toBe('forbidden')
    expect(error.message).toBe('只有超级管理员可以绑定或解绑技能')
  })

  it('工具面：路径逐字正确（含路径段编码）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/agents/a%2Fb/tools': { body: { agent_key: 'a/b', tools: ['fs.read'] } },
    })

    const outcome = await fetchAgentTools('a/b', fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/agents/a%2Fb/tools')
    expect(outcome.sample).toBe(false)
    expect(outcome.tools?.tools).toEqual(['fs.read'])
  })

  it('工具面：`tools` 缺失即抛错，不编造工具清单', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({ '/api/v1/skills/agents/agent-1/tools': { body: { agent_key: 'agent-1' } } })

    await expect(fetchAgentTools('agent-1', fetchImpl)).rejects.toBeInstanceOf(SkillError)
  })

  it('员工候选：读目录（active）+ 分页；目录为空返回空列表而非报错', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/workforce/agents': { body: { items: [], total: 0, limit: 200, offset: 0 } },
    })

    const page = await fetchAgentCandidates(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/workforce/agents?status=active&limit=200&offset=0')
    expect(page.items).toEqual([])
    expect(page.total).toBe(0)
  })

  it('员工候选：只取 `agent_key` 与展示名（其余字段不入模块类型）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/workforce/agents': {
        body: {
          items: [{ agent_key: 'agent-1', name: '内容运营助手', role_key: 'ops', status: 'active' }],
          total: 1,
          limit: 200,
          offset: 0,
        },
      },
    })

    const page = await fetchAgentCandidates(fetchImpl)

    expect(page.items).toEqual([{ agent_key: 'agent-1', name: '内容运营助手' }])
  })
})

describe('绑定面写路径', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('绑定：请求体只有后端允许的两键；回读值取自服务端响应', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { body: { skill_key: 'summarize', agent_key: 'agent-1', status: 'active' } },
    })

    const outcome = await bindAgentSkill('summarize', 'agent-1', fetchImpl)

    const body = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>
    expect(calls[0].init.method).toBe('POST')
    expect(Object.keys(body).sort()).toEqual(['agent_key', 'skill_key'])
    expect(outcome.written).toBe(true)
    expect(outcome.result).toEqual({ skill_key: 'summarize', agent_key: 'agent-1', status: 'active' })
  })

  it('解绑：`DELETE` + query（`skill_key` / `agent_key`）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { body: { skill_key: 'summarize', agent_key: 'agent-1', status: 'disabled' } },
    })

    const outcome = await unbindAgentSkill('summarize', 'agent-1', fetchImpl)

    expect(calls[0].init.method).toBe('DELETE')
    expect(calls[0].url).toBe('/api/v1/skills/bindings?skill_key=summarize&agent_key=agent-1')
    expect(outcome.result?.status).toBe('disabled')
  })

  it('解绑不存在的绑定：`404` ⇒ `not_found`（保持服务端原文）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills/bindings': { status: 404, body: { detail: 'binding agent-1/nope' } },
    })

    const error = (await unbindAgentSkill('nope', 'agent-1', fetchImpl).catch((caught: unknown) => caught)) as SkillError

    expect(error.kind).toBe('not_found')
    expect(error.message).toBe('binding agent-1/nope')
  })

  it('样例模式：不发任何请求，`written === false` 且不伪造回读值', async () => {
    setServiceMode('mock')
    const fetchImpl = (async () => {
      throw new Error('样例模式不应发请求')
    }) as unknown as typeof fetch

    const bound = await bindAgentSkill('summarize', 'agent-1', fetchImpl)
    const unbound = await unbindAgentSkill('summarize', 'agent-1', fetchImpl)

    expect(bound.written).toBe(false)
    expect(bound.result).toBeNull()
    expect(bound.note).toBe(MOCK_BINDING_WRITE_NOTE)
    expect(unbound.written).toBe(false)
    expect(unbound.result).toBeNull()
  })
})

describe('绑定状态与工具面归因（纯函数）', () => {
  const binding = (over: Partial<SkillBinding> = {}): SkillBinding => ({
    skill_key: 'summarize',
    agent_key: 'agent-1',
    status: 'active',
    created_by: 'acct-admin',
    created_at: null,
    ...over,
  })
  const skill = (over: Partial<SkillSummary> = {}): SkillSummary => ({
    skill_key: 'summarize',
    version: '1.0.0',
    name: '摘要助手',
    description: '生成结构化摘要',
    license: 'Apache-2.0',
    allowed_tools: ['fs.read'],
    status: 'enabled',
    source_key: 'manual',
    owner_id: 'acct-1',
    reviewed_by: null,
    created_at: null,
    updated_at: null,
    ...over,
  })

  it('未知绑定状态落 `unknown`（不误标）', () => {
    expect(parseBindingStatus('paused')).toBe('unknown')
    expect(parseBindingStatus('active')).toBe('active')
  })

  it('工具面归因：无绑定 / 无已启用技能 / 交集为空 / 就绪 四态分开', () => {
    expect(
      agentToolsReason({ agentKey: 'agent-1', bindings: [], skills: [skill()], tools: [] }),
    ).toBe('no_binding')

    expect(
      agentToolsReason({
        agentKey: 'agent-1',
        bindings: [binding({ skill_key: 'draft-skill' })],
        skills: [skill({ skill_key: 'draft-skill', status: 'submitted' })],
        tools: [],
      }),
    ).toBe('none_enabled')

    expect(
      agentToolsReason({ agentKey: 'agent-1', bindings: [binding()], skills: [skill()], tools: [] }),
    ).toBe('empty_intersection')

    expect(
      agentToolsReason({ agentKey: 'agent-1', bindings: [binding()], skills: [skill()], tools: ['fs.read'] }),
    ).toBe('ready')
  })

  it('工具面归因：只看**该员工**的 active 绑定（他人绑定 / 已解除绑定不算）', () => {
    expect(
      agentToolsReason({
        agentKey: 'agent-1',
        bindings: [binding({ agent_key: 'agent-2' })],
        skills: [skill()],
        tools: [],
      }),
    ).toBe('no_binding')

    expect(
      agentToolsReason({
        agentKey: 'agent-1',
        bindings: [binding({ status: 'disabled' })],
        skills: [skill()],
        tools: [],
      }),
    ).toBe('no_binding')
  })

  it('工具面归因：技能键查不到状态 ⇒ 不算已启用（fail-closed 呈现）', () => {
    expect(
      agentToolsReason({ agentKey: 'agent-1', bindings: [binding()], skills: [], tools: [] }),
    ).toBe('none_enabled')
  })
})