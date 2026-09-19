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
import { ServiceError } from '../../../utils/serviceKit'
import { ROLE_TEMPLATES } from '../../myAgents/services/myAgentsService'
import type { AgentItem, RoleKey } from '../../myAgents/types'
import { REGISTRY_PAGE_SIZE, lastRunPresence, ranLast7dPresence, usagePresence } from '../types'
import type { RegistryRow } from '../types'

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
    expect(['approval_for_all', 'approval_for_risky', 'full_auto']).toContain(row.template.autonomy_level)
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
    expect(stats.total).toBe(stats.active + stats.disabled + stats.draft)
    expect(stats.draft).toBeGreaterThan(0)
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

  it('http 模式：全部取数 / 写入都抛"尚未接入"，**不静默返回空数据**', async () => {
    setServiceMode('http')

    const calls: (() => Promise<unknown>)[] = [
      () => fetchRegistryAgents({ page: 1, pageSize: REGISTRY_PAGE_SIZE }),
      () => fetchRegistryStats(),
      () => fetchRegistryAgentDetail('sample-ops-content'),
      () => setAgentStatus({ agent_key: 'sample-ops-content', status: 'disabled' }),
    ]
    for (const call of calls) {
      await expect(call()).rejects.toBeInstanceOf(ServiceError)
      await expect(call()).rejects.toMatchObject({ failure: 'not_connected' })
      await expect(call()).rejects.toThrow(/尚未接入/)
    }
  })

  it('岗位选项覆盖 role-templates.md 的 6 个岗位', () => {
    const keys: RoleKey[] = roleTemplateOptions().map((template) => template.role_key)
    expect(keys).toEqual(['sales', 'hr', 'rd', 'finance', 'ops', 'admin'])
  })
})