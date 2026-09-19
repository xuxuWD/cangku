import {
  MOCK_WRITE_NOTE,
  fetchRegistryAgentDetail,
  fetchRegistryAgents,
  fetchRegistryStats,
  mode,
  roleTemplateOptions,
  setAgentStatus,
  setServiceMode,
} from '../services/agentRegistryService'
import { AGENT_PAGE_LIMIT, ROLE_TEMPLATES } from '../../myAgents/services/myAgentsService'
import type { AgentItem, RoleKey } from '../../myAgents/types'
import { REGISTRY_PAGE_SIZE, lastRunPresence, ranLast7dPresence, usagePresence } from '../types'
import type { RegistryRow } from '../types'

/**
 * 最小 `fetch` 桩（与接线批 1 同形，不引 MSW）：**不发真实网络请求**。
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
  return { fetchImpl, calls }
}

/** 后端 `DigitalEmployeeView` 实测形状（8 个键；**无** template / usage / last_run_at）。 */
const AGENT_VIEW = {
  agent_key: 'content-ops',
  name: '内容运营助手',
  description: '负责选题与草稿。',
  role_key: 'ops',
  status: 'active',
  created_by: 'acct-0001',
  created_at: '2026-09-10T09:00:00+08:00',
  updated_at: '2026-09-19T09:00:00+08:00',
}

const LIST_VIEW = { items: [AGENT_VIEW], total: 1, limit: REGISTRY_PAGE_SIZE, offset: 0 }

/**
 * 与员工侧实体（`my-agents-api.md`）**逐字一致**的共享字段清单。
 * 类型层面已由 `Pick<AgentItem, …>` 保证；这里再在运行时逐个点名，防止有人改成手抄字段名。
 */
const SHARED_FIELDS = [
  'agent_key',
  'name',
  'description',
  'role_key',
  'created_by',
  'created_at',
  'updated_at',
  'last_run_at',
  'template',
] as const satisfies readonly (keyof AgentItem)[]

/** 递归收集所有字符串（含键名），用于"样例数据不含敏感信息"的自检。 */
function collectText(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(collectText)
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, nested]) => [key, ...collectText(nested)])
  }
  return []
}

describe('agentRegistryService 适配层', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('⑧ 与员工侧共享字段逐字一致，岗位 / 自治档沿用 role-templates.md 的受控枚举', async () => {
    expect(mode).toBe('mock')

    const payload = await fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE })
    const row: RegistryRow = payload.items[0]

    for (const field of SHARED_FIELDS) {
      expect(Object.keys(row)).toContain(field)
    }
    // 结构兼容 ⇒ 同名同义（类型层面直接取 employee 侧实体类型）
    const shared: Pick<AgentItem, (typeof SHARED_FIELDS)[number]> = row
    expect(shared.agent_key).toBe(row.agent_key)
    expect(shared.role_key).toBe(row.role_key)

    // 管理侧多出的字段
    expect(Object.keys(row)).toEqual(expect.arrayContaining(['status', 'usage']))
    // 管理侧不含员工侧视角字段
    expect(Object.keys(row)).not.toContain('ownership')

    // 岗位键 / 自治档 / 模板对象都来自项目级唯一一份（同对象身份 ⇒ 没有第二份副本）
    expect(['sales', 'hr', 'rd', 'finance', 'ops', 'admin']).toContain(row.role_key)
    expect(['approval_for_all', 'approval_for_risky', 'full_auto']).toContain(row.template!.autonomy_level)
    expect(row.template).toBe(ROLE_TEMPLATES.find((template) => template.role_key === row.role_key))
    expect(roleTemplateOptions()).toBe(ROLE_TEMPLATES)
  })

  it('列表：筛选条件与分页都交给"服务端"（mock 分支），并返回 items/total/limit/offset', async () => {
    const all = await fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE })
    expect(all.sample).toBe(true)
    expect(all.total).toBe(9)
    expect(all.limit).toBe(REGISTRY_PAGE_SIZE)
    expect(all.offset).toBe(0)

    const paged = await fetchRegistryAgents({ page: 2, pageSize: 4 })
    expect(paged.items).toHaveLength(4)
    expect(paged.total).toBe(9)
    expect(paged.offset).toBe(4)

    const byRole = await fetchRegistryAgents({ role_key: 'ops', page: 1, pageSize: REGISTRY_PAGE_SIZE })
    expect(byRole.items.length).toBeGreaterThan(0)
    expect(byRole.items.every((row) => row.role_key === 'ops')).toBe(true)

    const byStatus = await fetchRegistryAgents({ status: 'draft', page: 1, pageSize: REGISTRY_PAGE_SIZE })
    expect(byStatus.items).toHaveLength(1)
    expect(byStatus.items[0].status).toBe('draft')

    const byCreator = await fetchRegistryAgents({ created_by: '02', page: 1, pageSize: REGISTRY_PAGE_SIZE })
    expect(byCreator.items.length).toBeGreaterThan(0)
    expect(byCreator.items.every((row) => row.created_by.includes('02'))).toBe(true)

    const byKeyword = await fetchRegistryAgents({ keyword: '报价', page: 1, pageSize: REGISTRY_PAGE_SIZE })
    expect(byKeyword.items.map((row) => row.name)).toEqual(['报价单助手'])

    const noneMatch = await fetchRegistryAgents({
      role_key: 'ops',
      status: 'disabled',
      keyword: '报价',
      page: 1,
      pageSize: REGISTRY_PAGE_SIZE,
    })
    expect(noneMatch.items).toHaveLength(0)
    expect(noneMatch.total).toBe(0)
  })

  it('统计：全员口径且**总数恒等于三态之和**（期望值从样例派生）；运行口径未接入 ⇒ null（不得填 0）', async () => {
    const rows = (await fetchRegistryAgents({ page: 1, pageSize: 100 })).items
    const expected = {
      total: rows.length,
      active: rows.filter((row) => row.status === 'active').length,
      disabled: rows.filter((row) => row.status === 'disabled').length,
      draft: rows.filter((row) => row.status === 'draft').length,
    }

    const stats = await fetchRegistryStats()
    expect(stats.sample).toBe(true)
    // 与逐行派生的期望值一致（样例增删行时用例自动跟随，不硬编码 9/6/2/1）
    expect(stats).toMatchObject(expected)
    expect(stats.total).toBe(stats.active + stats.disabled + stats.draft!)
    expect(stats.draft!).toBeGreaterThan(0)
    expect(stats.ran_last_7d).toBeNull()
    expect(ranLast7dPresence(stats)).toBe('unverified')
  })

  it('状态保真：样例覆盖"未验证 / 样本不足 / 未配置"三种非就绪态，且判定规则单调', async () => {
    const rows = (await fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE })).items
    const presences = rows.map((row) => usagePresence(row.usage))
    expect(presences).toContain('unverified')
    expect(presences).toContain('insufficient_sample')
    expect(presences).toContain('not_configured')
    expect(presences).toContain('ready')

    expect(usagePresence({ run_count: null, success_rate: null })).toBe('unverified')
    expect(usagePresence({ run_count: 0, success_rate: null })).toBe('insufficient_sample')
    expect(usagePresence({ run_count: 4, success_rate: null })).toBe('not_configured')
    expect(usagePresence({ run_count: 4, success_rate: 0.5 })).toBe('ready')
    expect(lastRunPresence({ last_run_at: null } as RegistryRow)).toBe('unverified')
  })

  it('样例数据不含敏感信息（手机号 / 租户 / 用户 / 凭据字段）', async () => {
    const payloads = [await fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE }), await fetchRegistryStats()]
    const text = payloads.flatMap(collectText).join('\n')

    expect(text).not.toMatch(/1[3-9]\d{9}/)
    expect(text).not.toMatch(/tenant_id|user_id|password|token|secret|api[_-]?key/i)
  })

  it('写操作在 mock 下明确"没有写入后端"（不假装成功）', async () => {
    const result = await setAgentStatus({ agent_key: 'sample-ops-content', status: 'disabled' })
    expect(result.written).toBe(false)
    expect(result.note).toBe(MOCK_WRITE_NOTE)
    expect(result.note).toMatch(/未接后端/)
  })

  it('详情：查不到时按 failed 抛错（不返回伪造对象）', async () => {
    await expect(fetchRegistryAgentDetail('not-exist')).rejects.toMatchObject({ failure: 'failed' })
    const found = await fetchRegistryAgentDetail('sample-ops-content')
    expect(found.agent_key).toBe('sample-ops-content')
  })

  describe('http 模式（接线批 2：列表 / 指标 / 启停走真接口）', () => {
    beforeEach(() => {
      setServiceMode('http')
      sessionStorage.removeItem('workbench.token')
    })

    it('列表：`GET /api/v1/workforce/agents`，筛选与分页原样透传（limit / offset）', async () => {
      const { fetchImpl, calls } = stubFetch({ '/api/v1/workforce/agents': { body: LIST_VIEW } })

      const payload = await fetchRegistryAgents(
        { role_key: 'ops', status: 'disabled', page: 3, pageSize: REGISTRY_PAGE_SIZE },
        fetchImpl,
      )

      expect(calls).toHaveLength(1)
      expect(calls[0].url).toBe(
        `/api/v1/workforce/agents?role_key=ops&status=disabled&limit=${REGISTRY_PAGE_SIZE}&offset=${2 * REGISTRY_PAGE_SIZE}`,
      )
      expect(calls[0].init.method).toBe('GET')
      expect(payload).toMatchObject({ sample: false, total: 1, limit: REGISTRY_PAGE_SIZE, offset: 0 })
    })

    it('列表：字段逐个映射；usage / last_run_at 后端不提供 ⇒ 非就绪（绝不填 0 或 0%）', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/workforce/agents': { body: LIST_VIEW } })

      const row = (await fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE }, fetchImpl)).items[0]

      expect(row).toEqual({
        agent_key: 'content-ops',
        name: '内容运营助手',
        description: '负责选题与草稿。',
        role_key: 'ops',
        created_by: 'acct-0001',
        created_at: '2026-09-10T09:00:00+08:00',
        updated_at: '2026-09-19T09:00:00+08:00',
        last_run_at: null,
        template: ROLE_TEMPLATES.find((template) => template.role_key === 'ops'),
        status: 'active',
        usage: { run_count: null, success_rate: null },
      })
      expect(usagePresence(row.usage)).toBe('unverified')
      expect(lastRunPresence(row)).toBe('unverified')
      // 管理侧**不含**员工侧视角字段（后端也没有共享关系）
      expect(Object.keys(row)).not.toContain('ownership')
    })

    it('列表：后端未支持的筛选（创建者 / 名称 / 草稿）⇒ 抛"尚未接入"，**不静默忽略**', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/workforce/agents': { body: LIST_VIEW } })

      for (const query of [
        { created_by: 'acct', page: 1, pageSize: REGISTRY_PAGE_SIZE },
        { keyword: '助手', page: 1, pageSize: REGISTRY_PAGE_SIZE },
        { status: 'draft' as const, page: 1, pageSize: REGISTRY_PAGE_SIZE },
      ]) {
        await expect(fetchRegistryAgents(query, fetchImpl)).rejects.toMatchObject({ failure: 'not_connected' })
      }
    })

    it('指标：**从真实列表派生**（无聚合接口）；草稿枚举后端未定义 ⇒ null，运行口径 ⇒ null', async () => {
      const { fetchImpl, calls } = stubFetch({
        '/api/v1/workforce/agents': {
          body: {
            items: [AGENT_VIEW, { ...AGENT_VIEW, agent_key: 'b', status: 'disabled' }],
            total: 2,
            limit: AGENT_PAGE_LIMIT,
            offset: 0,
          },
        },
      })

      const stats = await fetchRegistryStats(fetchImpl)

      expect(calls[0].url).toBe(`/api/v1/workforce/agents?limit=${AGENT_PAGE_LIMIT}&offset=0`)
      expect(stats).toEqual({ sample: false, total: 2, active: 1, disabled: 1, draft: null, ran_last_7d: null })
      expect(ranLast7dPresence(stats)).toBe('unverified')
    })

    it('指标：`total` 大于单页返回 ⇒ 抛 failed（不把残缺派生当准数）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': { body: { items: [AGENT_VIEW], total: 900, limit: 200, offset: 0 } },
      })

      await expect(fetchRegistryStats(fetchImpl)).rejects.toMatchObject({ failure: 'failed' })
    })

    it('启停：`PATCH /api/v1/workforce/agents/{agent_key}`，请求体恰为 `{status}`，`written` 为 true', async () => {
      const { fetchImpl, calls } = stubFetch({
        '/api/v1/workforce/agents/': { body: { ...AGENT_VIEW, status: 'disabled' } },
      })

      const result = await setAgentStatus({ agent_key: 'content-ops', status: 'disabled' }, fetchImpl)

      expect(calls[0].url).toBe('/api/v1/workforce/agents/content-ops')
      expect(calls[0].init.method).toBe('PATCH')
      expect(JSON.parse(String(calls[0].init.body))).toEqual({ status: 'disabled' })
      expect(result).toEqual({ agent_key: 'content-ops', written: true, note: expect.stringMatching(/已写入后端/) })
    })

    it('详情 / 员工侧无对应口径：管理侧只读详情**如实抛"尚未接入"**', async () => {
      await expect(fetchRegistryAgentDetail('content-ops')).rejects.toMatchObject({ failure: 'not_connected' })
    })

    it('失败分类：403 ⇒ `forbidden`（界面走无权限态，不静默空表格）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': { status: 403, body: { detail: '只有超级管理员可以管理岗位与数字员工目录' } },
      })

      await expect(fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE }, fetchImpl)).rejects.toMatchObject({
        failure: 'forbidden',
      })
    })
  })

  it('岗位选项覆盖 role-templates.md 的 6 个岗位', () => {
    const keys: RoleKey[] = roleTemplateOptions().map((template) => template.role_key)
    expect(keys).toEqual(['sales', 'hr', 'rd', 'finance', 'ops', 'admin'])
  })
})