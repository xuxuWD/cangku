import {
  MOCK_WRITE_NOTE,
  ROLE_TEMPLATES,
  createAgent,
  disableAgent,
  fetchAgentDetail,
  fetchMyAgents,
  fetchRoleTemplates,
  mode,
  setServiceMode,
  templateOf,
  updateAgent,
} from '../services/myAgentsService'
import { ServiceError } from '../../../utils/serviceKit'

/**
 * 与 `docs/contracts/role-templates.md` §2 的**逐字比对**表。
 * 这里刻意再抄一遍契约原文：任一模板的 Skill / 自治档被改动，本用例即红，逼迫回改契约或回改代码。
 */
const CONTRACT_EXPECTATION: Record<string, { name: string; skills: string[]; autonomy_level: string; scopes: number }> = {
  sales: {
    name: '销售',
    skills: ['crm.lead_intake', 'crm.quote_draft', 'content.outreach_draft'],
    autonomy_level: 'approval_for_risky',
    scopes: 2,
  },
  hr: {
    name: '人事',
    skills: ['hr.jd_draft', 'hr.interview_summary', 'doc.extract'],
    autonomy_level: 'approval_for_all',
    scopes: 2,
  },
  rd: {
    name: '研发',
    skills: ['rd.repo_inspect', 'rd.spec_draft', 'rd.changelog'],
    autonomy_level: 'approval_for_risky',
    scopes: 2,
  },
  finance: {
    name: '财务',
    skills: ['fin.reconcile_hint', 'fin.report_explain', 'doc.extract'],
    autonomy_level: 'approval_for_all',
    scopes: 2,
  },
  ops: {
    name: '运营',
    skills: ['content.topic_plan', 'content.draft', 'content.review'],
    autonomy_level: 'approval_for_risky',
    scopes: 2,
  },
  admin: {
    name: '行政',
    skills: ['office.meeting_minutes', 'office.schedule_hint', 'doc.extract'],
    autonomy_level: 'approval_for_risky',
    scopes: 1,
  },
}

/** 递归收集所有字符串（含键名），用于"样例数据不含敏感信息"的自检。 */
function collectText(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(collectText)
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, nested]) => [key, ...collectText(nested)])
  }
  return []
}

describe('myAgentsService 适配层', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('6 个岗位模板与 role-templates.md §2 逐字一致（名称 / Skill / 自治档 / 知识范围条数）', () => {
    expect(ROLE_TEMPLATES.map((template) => template.role_key)).toEqual([
      'sales',
      'hr',
      'rd',
      'finance',
      'ops',
      'admin',
    ])

    for (const template of ROLE_TEMPLATES) {
      const expected = CONTRACT_EXPECTATION[template.role_key]
      expect(template.name).toBe(expected.name)
      expect(template.skills).toEqual(expected.skills)
      expect(template.autonomy_level).toBe(expected.autonomy_level)
      expect(template.knowledge_scopes).toHaveLength(expected.scopes)
      // 金额一律整数分（契约：金额不用浮点）
      expect(Number.isInteger(template.budget_cents)).toBe(true)
      expect(template.budget_cents).toBeGreaterThan(0)
    }
  })

  it('默认 mock：列表与模板都带 sample 硬标记，且样例覆盖"共享给我的"与"无运行记录"', async () => {
    expect(mode).toBe('mock')

    const agents = await fetchMyAgents()
    const templates = await fetchRoleTemplates()
    expect(agents.sample).toBe(true)
    expect(templates.sample).toBe(true)
    expect(agents.items.some((agent) => agent.ownership === 'mine')).toBe(true)
    expect(agents.items.some((agent) => agent.ownership === 'shared')).toBe(true)
    // 状态保真样本：至少有一个从未运行过的员工
    expect(agents.items.some((agent) => agent.last_run_at === null)).toBe(true)
    // 能力包内联解析：员工的 role_key 必须能在模板表里找到
    for (const agent of agents.items) {
      expect(templateOf(agent.role_key)).toBeDefined()
      expect(agent.template.role_key).toBe(agent.role_key)
    }
  })

  it('样例数据不含敏感信息（手机号 / 租户 / 用户 / 凭据字段）', async () => {
    const payloads = [
      await fetchMyAgents(),
      await fetchRoleTemplates(),
      await fetchAgentDetail('sample-content-ops'),
    ]
    const text = payloads.flatMap(collectText).join('\n')

    expect(text).not.toMatch(/1[3-9]\d{9}/)
    expect(text).not.toMatch(/tenant_id|user_id|password|token|secret|api[_-]?key/i)
  })

  it('写操作在 mock 下明确"没有写入后端"（不假装成功）', async () => {
    const created = await createAgent({ name: '示例员工', role_key: 'ops', description: '示例范围。' })
    const updated = await updateAgent({ agent_key: 'sample-content-ops', name: '改名', description: '改范围。' })
    const disabled = await disableAgent('sample-content-ops')

    for (const result of [created, updated, disabled]) {
      expect(result.written).toBe(false)
      expect(result.note).toBe(MOCK_WRITE_NOTE)
      expect(result.note).toMatch(/未接后端/)
    }
  })

  it('http 模式：全部取数 / 写入都抛"尚未接入"，**不静默返回空数据**', async () => {
    setServiceMode('http')

    const calls: (() => Promise<unknown>)[] = [
      () => fetchMyAgents(),
      () => fetchRoleTemplates(),
      () => fetchAgentDetail('sample-content-ops'),
      () => createAgent({ name: 'n', role_key: 'ops', description: 'd' }),
      () => updateAgent({ agent_key: 'k', name: 'n', description: 'd' }),
      () => disableAgent('k'),
    ]

    for (const call of calls) {
      await expect(call()).rejects.toBeInstanceOf(ServiceError)
      await expect(call()).rejects.toMatchObject({ failure: 'not_connected' })
      await expect(call()).rejects.toThrow(/尚未接入/)
    }
  })

  it('详情查不到时按 failed 抛错（不返回伪造对象）', async () => {
    await expect(fetchAgentDetail('not-exist')).rejects.toMatchObject({ failure: 'failed' })
  })
})