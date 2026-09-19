import { createAgent, createRole, listAgents, listCandidates, listRoles, readAgentConfig, updateAgent, updateAgentConfig, updateRole } from './api'
import { directoryErrorFromStatus } from './state'

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function ok(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response
}

describe('workforceSettings api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists roles with the single-page limit and optional status filter', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ items: [], total: 0, limit: 200, offset: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listRoles()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/workforce/roles?limit=200&offset=0')

    await listRoles('disabled')
    expect(String(fetchMock.mock.calls[1][0])).toContain('status=disabled')
  })

  it('creates a role with a JSON body', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({}, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createRole({ role_key: 'content-operator', name: '自媒体运营岗', description: '' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/workforce/roles')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ role_key: 'content-operator', name: '自媒体运营岗', description: '' })
  })

  it('updates a role by key without ever sending the identity', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await updateRole('content-operator', { status: 'disabled' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/workforce/roles/content-operator')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ status: 'disabled' })
  })

  it('filters agents by role and moves an employee between roles', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ items: [], total: 0, limit: 200, offset: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listAgents({ status: 'active', role_key: 'geo-operator' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('role_key=geo-operator')

    await updateAgent('content-writer', { role_key: 'geo-operator' })
    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toContain('/workforce/agents/content-writer')
    expect(JSON.parse(String(init?.body))).toEqual({ role_key: 'geo-operator' })
  })

  it('reads the unmanaged candidates', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ok({ roles: ['content-operator'], agents: ['content-writer'] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listCandidates()).resolves.toEqual({ roles: ['content-operator'], agents: ['content-writer'] })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/workforce/candidates')
  })

  it('surfaces the server-authored reason for conflicts', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ detail: '该岗位标识已存在' }, 409)))

    await expect(createRole({ role_key: 'content-operator', name: '重复', description: '' })).rejects.toMatchObject({ status: 409, retryable: false, message: '该岗位标识已存在' })
  })

  it('falls back to a fixed message when detail is a validation array', async () => {
    // Pydantic 的参数校验错误 detail 是数组：绝不把它 dump 到界面。
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ detail: [{ loc: ['body', 'role_key'], msg: 'too short' }] }, 422)))

    await expect(createRole({ role_key: '', name: '', description: '' })).rejects.toMatchObject({ status: 422, message: '提交的内容不符合要求：标识只能是小写字母、数字、点、下划线与短横线，中文名不能为空。' })
  })

  it('maps 403 and 401 to fixed Chinese messages', async () => {
    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({ detail: '只有超级管理员可以管理岗位与数字员工目录' }, 403)))
    await expect(listRoles()).rejects.toMatchObject({ status: 403, retryable: false, message: '当前账号没有管理岗位与数字员工的权限。' })

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => ok({}, 401)))
    await expect(listRoles()).rejects.toMatchObject({ status: 401, message: '登录态已失效，请重新登录。' })
  })

  it('maps network failures and 5xx to a retryable message', async () => {
    expect(directoryErrorFromStatus(0).retryable).toBe(true)
    expect(directoryErrorFromStatus(503).message).toBe('名单暂时读不出来，请检查网络后重新尝试。')

    vi.stubGlobal('fetch', vi.fn<FetchMock>(async () => { throw new Error('boom') }))
    await expect(listAgents()).rejects.toMatchObject({ status: 0, retryable: true })
  })

  it('reads and patches an employee config by key', async () => {
    const config = { agent_key: 'content-writer', system_prompt: '', model_key: '', temperature: 0.2, tool_allowlist: [], memory_policy: {}, autonomy_level: 'approval_for_risky', risk_threshold: 'high', approval_timeout_minutes: 60, daily_budget_cents: 0, updated_at: null }
    const fetchMock = vi.fn<FetchMock>(async () => ok(config))
    vi.stubGlobal('fetch', fetchMock)

    await readAgentConfig('content-writer')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/workforce/agents/content-writer/config')
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined()

    await updateAgentConfig('content-writer', { system_prompt: '你是助手', model_key: '', temperature: 0.2, tool_allowlist: [], memory_policy: { short_term_enabled: true, short_term_turns: 6 }, autonomy_level: 'full_auto', risk_threshold: 'high', approval_timeout_minutes: 60, daily_budget_cents: 1234 })

    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toContain('/workforce/agents/content-writer/config')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toMatchObject({ memory_policy: { short_term_enabled: true, short_term_turns: 6 }, autonomy_level: 'full_auto', daily_budget_cents: 1234 })
  })
})
