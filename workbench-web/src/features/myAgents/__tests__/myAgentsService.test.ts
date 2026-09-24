import {
  AGENT_PAGE_LIMIT,
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

/**
 * 最小 `fetch` 桩（与接线批 1 同形，不引 MSW）：返回收到的 `(url, init)`，
 * 供"路径 / 方法 / 请求体逐字正确"的断言使用。**不发真实网络请求**。
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

/** 后端 `DigitalEmployeeView`（`app/main.py:1399`）的实测形状：8 个键，**没有** template / last_run_at。 */
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

const LIST_VIEW = { items: [AGENT_VIEW], total: 1, limit: AGENT_PAGE_LIMIT, offset: 0 }

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
      expect(agent.template!.role_key).toBe(agent.role_key)
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

  it('http 模式：岗位模板 / 员工侧详情 / 创建**如实抛"尚未接入"**（后端无对应口径，不假装成功）', async () => {
    setServiceMode('http')

    const calls: (() => Promise<unknown>)[] = [
      () => fetchRoleTemplates(),
      () => fetchAgentDetail('sample-content-ops'),
      () => createAgent({ name: 'n', role_key: 'ops', description: 'd' }),
    ]

    for (const call of calls) {
      await expect(call()).rejects.toBeInstanceOf(ServiceError)
      await expect(call()).rejects.toMatchObject({ failure: 'not_connected' })
      await expect(call()).rejects.toThrow(/尚未接入/)
    }
  })

  describe('http 模式（接线批 2：列表 / 配置 / 停用走真接口）', () => {
    beforeEach(() => {
      setServiceMode('http')
      sessionStorage.removeItem('workbench.token')
    })

    it('列表：`GET /api/v1/workforce/agents`，路径与参数逐字正确，字段逐个映射且不编造', async () => {
      const { fetchImpl, calls } = stubFetch({ '/api/v1/workforce/agents': { body: LIST_VIEW } })

      const payload = await fetchMyAgents(fetchImpl)

      expect(calls).toHaveLength(1)
      expect(calls[0].url).toBe(`/api/v1/workforce/agents?limit=${AGENT_PAGE_LIMIT}&offset=0`)
      expect(calls[0].init.method).toBe('GET')
      // 真实数据**不得**被标成样例
      expect(payload.sample).toBe(false)

      expect(payload.items[0]).toEqual({
        agent_key: 'content-ops',
        name: '内容运营助手',
        description: '负责选题与草稿。',
        role_key: 'ops',
        status: 'active',
        created_by: 'acct-0001',
        created_at: '2026-09-10T09:00:00+08:00',
        updated_at: '2026-09-19T09:00:00+08:00',
        // 后端目录视图**不下发运行时间** ⇒ 恒为 null，界面按"未验证"呈现（绝不给 0 / 成功）
        last_run_at: null,
        // 本用例**未建会话**（无 `workbench.user`）⇒ 归属判不了 ⇒ `unknown`，不编造"我创建的"。
        // 注：原注释写「后端也无『共享』实体」—— OP-01（2026-09-24）起该前提已失效，
        // 后端已有共享实体且视图下发 `owner_user_id`；此处落到 `unknown` 是因为**缺本人标识**。
        ownership: 'unknown',
        // 能力包按 role_key 解析自项目级唯一目录（role-templates.md）；后端未下发 template 字段
        template: ROLE_TEMPLATES.find((template) => template.role_key === 'ops'),
      })
    })

    it('归属判定（OP-01 起可判）：按后端下发的 `owner_user_id` 与本人标识逐行比对', async () => {
      sessionStorage.setItem('workbench.token', 'token-for-test')
      sessionStorage.setItem('workbench.user', 'acct-0001')
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': {
          body: {
            items: [
              { ...AGENT_VIEW, agent_key: 'mine', owner_user_id: 'acct-0001' },
              { ...AGENT_VIEW, agent_key: 'theirs', owner_user_id: 'acct-9999' },
              // 后端未下发归属 ⇒ fail-closed 落到 unknown，**绝不**当成 mine
              { ...AGENT_VIEW, agent_key: 'no-owner', owner_user_id: null },
            ],
            total: 3,
            limit: AGENT_PAGE_LIMIT,
            offset: 0,
          },
        },
      })

      const payload = await fetchMyAgents(fetchImpl)

      expect(payload.items.map((agent) => [agent.agent_key, agent.ownership])).toEqual([
        ['mine', 'mine'],
        ['theirs', 'shared'],
        ['no-owner', 'unknown'],
      ])
    })

    it('归属判定 fail-closed：没有本人标识 ⇒ 一律 unknown（即便后端下发了归属）', async () => {
      sessionStorage.setItem('workbench.token', 'token-for-test')
      sessionStorage.removeItem('workbench.user')
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': {
          body: {
            items: [{ ...AGENT_VIEW, owner_user_id: 'acct-0001' }],
            total: 1,
            limit: AGENT_PAGE_LIMIT,
            offset: 0,
          },
        },
      })

      const payload = await fetchMyAgents(fetchImpl)

      expect(payload.items[0].ownership).toBe('unknown')
    })

    it('列表：岗位键不在项目级目录里 ⇒ `template` 为 null（不编造模板）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': {
          body: { items: [{ ...AGENT_VIEW, role_key: 'legal' }], total: 1, limit: AGENT_PAGE_LIMIT, offset: 0 },
        },
      })

      const payload = await fetchMyAgents(fetchImpl)
      expect(payload.items[0].role_key).toBe('legal')
      expect(payload.items[0].template).toBeNull()
    })

    it('列表：`total` 大于单页返回 ⇒ 抛 failed（**不返回残缺列表**）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': { body: { items: [AGENT_VIEW], total: 250, limit: 200, offset: 0 } },
      })

      await expect(fetchMyAgents(fetchImpl)).rejects.toMatchObject({ failure: 'failed' })
    })

    it('列表：后端返回未知状态 ⇒ 抛 failed（不误标成"已启用 / 已停用"）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': {
          body: { items: [{ ...AGENT_VIEW, status: 'archived' }], total: 1, limit: AGENT_PAGE_LIMIT, offset: 0 },
        },
      })

      await expect(fetchMyAgents(fetchImpl)).rejects.toMatchObject({ failure: 'failed' })
    })

    it('配置：`PATCH /api/v1/workforce/agents/{agent_key}`，请求体恰为 name / description，`written` 为 true', async () => {
      const { fetchImpl, calls } = stubFetch({
        '/api/v1/workforce/agents/': { body: { ...AGENT_VIEW, name: '改名', description: '改范围。' } },
      })

      const result = await updateAgent({ agent_key: 'content-ops', name: '改名', description: '改范围。' }, fetchImpl)

      expect(calls[0].url).toBe('/api/v1/workforce/agents/content-ops')
      expect(calls[0].init.method).toBe('PATCH')
      expect(JSON.parse(String(calls[0].init.body))).toEqual({ name: '改名', description: '改范围。' })
      expect(result).toEqual({ agent_key: 'content-ops', written: true, note: expect.stringMatching(/已写入后端/) })
    })

    it('停用：`PATCH /api/v1/workforce/agents/{agent_key}`，请求体恰为 `{status:"disabled"}`', async () => {
      const { fetchImpl, calls } = stubFetch({
        '/api/v1/workforce/agents/': { body: { ...AGENT_VIEW, status: 'disabled' } },
      })

      const result = await disableAgent('content-ops', fetchImpl)

      expect(calls[0].url).toBe('/api/v1/workforce/agents/content-ops')
      expect(calls[0].init.method).toBe('PATCH')
      expect(JSON.parse(String(calls[0].init.body))).toEqual({ status: 'disabled' })
      expect(result).toEqual({ agent_key: 'content-ops', written: true, note: expect.stringMatching(/已写入后端/) })
    })

    it('失败分类：403 ⇒ `forbidden`（与其它失败分开，界面据四态区分）', async () => {
      const { fetchImpl } = stubFetch({
        '/api/v1/workforce/agents': { status: 403, body: { detail: '只有超级管理员可以管理岗位与数字员工目录' } },
      })

      await expect(fetchMyAgents(fetchImpl)).rejects.toMatchObject({ failure: 'forbidden' })
    })

    it('失败分类：404（目标不存在）⇒ `failed`，且不静默返回空列表', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/workforce/agents/': { status: 404, body: { detail: '数字员工不存在' } } })

      await expect(disableAgent('no-such-agent', fetchImpl)).rejects.toMatchObject({ failure: 'failed' })
    })
  })

  it('详情查不到时按 failed 抛错（不返回伪造对象）', async () => {
    await expect(fetchAgentDetail('not-exist')).rejects.toMatchObject({ failure: 'failed' })
  })
})