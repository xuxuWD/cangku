import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkforceSettingsPage } from './WorkforceSettingsPage'

function json(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response
}

function role(overrides: Record<string, unknown> = {}) {
  return { role_key: 'content-operator', name: '自媒体运营岗', description: '', status: 'active', created_by: 'admin-1', created_at: null, updated_at: null, ...overrides }
}

function agent(overrides: Record<string, unknown> = {}) {
  return { agent_key: 'content-writer', name: '内容创作数字员工', description: '', role_key: 'content-operator', status: 'active', created_by: 'admin-1', created_at: null, updated_at: null, ...overrides }
}

interface Directory {
  roles: Array<Record<string, unknown>>
  agents: Array<Record<string, unknown>>
  candidates: { roles: string[]; agents: string[] }
}

interface Options {
  getStatus?: number
  writeStatus?: number
  writeDetail?: unknown
  configStatus?: number
  failFirstBatch?: boolean
}

// 假服务端：GET 返回当前目录内容，POST/PATCH 会真的改动内存中的目录，
// 这样「写成功后列表刷新能看到新内容」也是被验证过的，而不只是断言请求发出去了。
function makeFetch(directory: Directory, options: Options = {}) {
  const calls: Array<{ url: string; method: string; body: string }> = []
  let getBatches = 0
  const config = { agent_key: 'content-writer', system_prompt: '你是内容创作助手', model_key: 'mock-default', temperature: 0.2, tool_allowlist: [], memory_policy: { short_term_enabled: true, short_term_turns: 6 }, autonomy_level: 'approval_for_risky', risk_threshold: 'high', approval_timeout_minutes: 60, daily_budget_cents: 0, updated_at: '2026-09-12T07:28:57.796743Z' }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (options.getStatus && options.getStatus >= 400) return json({ detail: '只有超级管理员可以管理岗位与数字员工目录' }, options.getStatus)

    if (url.includes('/workforce/agents/') && url.includes('/config')) {
      if (method === 'PATCH') {
        if (options.writeStatus && options.writeStatus >= 400) return json({ detail: options.writeDetail }, options.writeStatus)
        return json({ ...config, ...(JSON.parse(String(init?.body)) as Record<string, unknown>) })
      }
      if (options.configStatus && options.configStatus >= 400) return json({ detail: '只有超级管理员可以读取配置' }, options.configStatus)
      return json(config)
    }

    if (method === 'POST' || method === 'PATCH') {
      if (options.writeStatus && options.writeStatus >= 400) return json({ detail: options.writeDetail }, options.writeStatus)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      if (method === 'POST' && url.includes('/workforce/roles')) {
        directory.roles.push(role({ role_key: body.role_key, name: body.name, description: body.description ?? '' }))
        return json(role({ role_key: body.role_key, name: body.name }), 201)
      }
      if (method === 'POST' && url.includes('/workforce/agents')) {
        directory.agents.push(agent({ agent_key: body.agent_key, name: body.name, role_key: body.role_key }))
        return json(agent({ agent_key: body.agent_key, name: body.name, role_key: body.role_key }), 201)
      }
      return json(role(body))
    }

    if (url.includes('/workforce/roles')) {
      if (options.failFirstBatch && ++getBatches === 1) return json({}, 500)
      return json({ items: directory.roles, total: directory.roles.length, limit: 200, offset: 0 })
    }
    if (url.includes('/workforce/agents')) {
      if (options.failFirstBatch && getBatches === 1) return json({}, 500)
      return json({ items: directory.agents, total: directory.agents.length, limit: 200, offset: 0 })
    }
    if (url.includes('/workforce/candidates')) {
      if (options.failFirstBatch && getBatches === 1) return json({}, 500)
      return json(directory.candidates)
    }
    return json({})
  })
  return { fetchMock, calls }
}

const emptyDirectory = (): Directory => ({ roles: [], agents: [], candidates: { roles: [], agents: [] } })

describe('WorkforceSettingsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders roles with identifier, name, status and the unmanaged block', async () => {
    const { fetchMock } = makeFetch({ roles: [role()], agents: [agent()], candidates: { roles: ['legacy-role'], agents: ['legacy-agent'] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)

    expect(await screen.findByText('自媒体运营岗')).toBeInTheDocument()
    expect(screen.getByText('content-operator')).toBeInTheDocument()
    expect(screen.getByText('启用', { selector: 'span.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('legacy-role')).toBeInTheDocument()
    expect(screen.getByText('共 1 个岗位')).toBeInTheDocument()
  })

  it('creates a role and shows it after the reload', async () => {
    const { fetchMock, calls } = makeFetch(emptyDirectory())
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await screen.findByText('暂无岗位')

    await userEvent.type(screen.getByLabelText('岗位标识'), 'geo-operator')
    await userEvent.type(screen.getByLabelText('中文名'), 'GEO 运营岗')
    await userEvent.click(screen.getByRole('button', { name: '创建岗位' }))

    expect(await screen.findByText('GEO 运营岗')).toBeInTheDocument()
    const post = calls.find((call) => call.method === 'POST')
    expect(post && JSON.parse(post.body)).toEqual({ role_key: 'geo-operator', name: 'GEO 运营岗', description: '' })
  })

  it('disables a role from the list', async () => {
    const { fetchMock, calls } = makeFetch({ roles: [role()], agents: [], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await screen.findByText('自媒体运营岗')

    await userEvent.click(screen.getByRole('button', { name: '停用' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH' && JSON.parse(call.body).status === 'disabled')).toBe(true))
  })

  it('renames a role from the inline editor', async () => {
    const { fetchMock, calls } = makeFetch({ roles: [role()], agents: [], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await screen.findByText('自媒体运营岗')

    await userEvent.click(screen.getByRole('button', { name: '修改' }))
    const input = screen.getAllByLabelText('中文名').find((element) => (element as HTMLInputElement).value === '自媒体运营岗') as HTMLInputElement
    await userEvent.clear(input)
    await userEvent.type(input, '内容运营岗')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH' && JSON.parse(call.body).name === '内容运营岗')).toBe(true))
  })

  it('shows the permission message for 403 without offering a retry', async () => {
    const { fetchMock } = makeFetch(emptyDirectory(), { getStatus: 403 })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('当前账号没有管理岗位与数字员工的权限。')
    expect(screen.queryByRole('button', { name: '重新尝试' })).not.toBeInTheDocument()
  })

  it('retries after a server error', async () => {
    const { fetchMock } = makeFetch({ roles: [role()], agents: [], candidates: { roles: [], agents: [] } }, { failFirstBatch: true })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('目录服务暂时不可用')

    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('自媒体运营岗')).toBeInTheDocument()
  })

  it('creates an employee under the selected role', async () => {
    const { fetchMock, calls } = makeFetch({ roles: [role()], agents: [], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await screen.findByText('自媒体运营岗')

    await userEvent.click(screen.getByRole('tab', { name: '数字员工' }))
    await screen.findByText('暂无数字员工')

    await userEvent.type(screen.getByLabelText('员工标识'), 'geo-analyst')
    await userEvent.type(screen.getByLabelText('中文名'), 'GEO 分析数字员工')
    await userEvent.selectOptions(screen.getByLabelText('所属岗位'), 'content-operator')
    await userEvent.click(screen.getByRole('button', { name: '创建数字员工' }))

    expect(await screen.findByText('GEO 分析数字员工')).toBeInTheDocument()
    const post = calls.find((call) => call.method === 'POST' && call.url.includes('/workforce/agents'))
    expect(post && JSON.parse(post.body)).toEqual({ agent_key: 'geo-analyst', name: 'GEO 分析数字员工', role_key: 'content-operator', description: '' })
  })

  it('prefills the create form when adopting an unmanaged identifier', async () => {
    const { fetchMock } = makeFetch({ roles: [], agents: [], candidates: { roles: ['legacy-role'], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await screen.findByText('legacy-role')

    await userEvent.click(screen.getByRole('button', { name: '纳管' }))

    expect((screen.getByLabelText('岗位标识') as HTMLInputElement).value).toBe('legacy-role')
  })

  it('reads and saves the employee config, converting the budget from yuan to integer cents', async () => {
    const { fetchMock, calls } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await userEvent.click(await screen.findByRole('tab', { name: '数字员工' }))
    await screen.findByText('内容创作数字员工')

    await userEvent.click(screen.getByRole('button', { name: '配置' }))

    const prompt = await screen.findByLabelText('系统提示词')
    expect(prompt).toHaveValue('你是内容创作助手')
    expect(prompt).toHaveAttribute('maxlength', '8000')
    // 温度按两位小数展示，步进与后端 0.00–2.00 口径一致。
    expect(screen.getByLabelText('温度')).toHaveValue(0.2)
    expect(screen.getByLabelText('温度')).toHaveAttribute('step', '0.05')
    expect(screen.getByText(/每个工具调用都需要人工审批通过后才执行/)).toBeInTheDocument()
    expect(screen.getByText(/免人工审批；但「极高（critical）」风险动作任何自治等级都必须审批/)).toBeInTheDocument()
    // D18：风险阈值必须能选到最高档 critical（否则 full_auto 的兜底无从表达）。
    expect(screen.getByRole('option', { name: /critical/ })).toBeInTheDocument()
    // 配置的更新时间必须本地化，不得把后端原始 ISO 串直接摊到界面上。
    expect(screen.queryByText(/2026-09-12T07:28:57/)).not.toBeInTheDocument()
    expect(screen.getByText(/更新于 \d{4}\/\d{2}\/\d{2} \d{2}:\d{2}/)).toBeInTheDocument()

    const budget = screen.getByLabelText('每日预算（元）')
    await userEvent.clear(budget)
    await userEvent.type(budget, '12.34')
    await userEvent.click(screen.getByRole('button', { name: '保存配置' }))

    await waitFor(() => {
      const patch = calls.find((call) => call.method === 'PATCH' && call.url.includes('/config'))
      expect(patch && JSON.parse(patch.body).daily_budget_cents).toBe(1234)
    })
  })

  it('shows the backend reason verbatim when the prompt is rejected (D11)', async () => {
    const detail = '提示词包含试图改变权限判定的指令（如忽略/跳过审批、绕过权限），已拒绝写入'
    const { fetchMock } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } }, { writeStatus: 422, writeDetail: detail })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await userEvent.click(await screen.findByRole('tab', { name: '数字员工' }))
    await screen.findByText('内容创作数字员工')
    await userEvent.click(screen.getByRole('button', { name: '配置' }))
    await screen.findByLabelText('系统提示词')

    await userEvent.click(screen.getByRole('button', { name: '保存配置' }))

    expect(await screen.findByText(detail)).toBeInTheDocument()
  })

  it('shows the explicit config permission message when reading the config is forbidden', async () => {
    const { fetchMock } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } }, { configStatus: 403 })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await userEvent.click(await screen.findByRole('tab', { name: '数字员工' }))
    await screen.findByText('内容创作数字员工')
    await userEvent.click(screen.getByRole('button', { name: '配置' }))

    expect(await screen.findByText('仅超级管理员可查看与修改数字员工配置。')).toBeInTheDocument()
  })

  it('warns that full_auto is super-admin only and audited when it is selected', async () => {
    const { fetchMock } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await userEvent.click(await screen.findByRole('tab', { name: '数字员工' }))
    await screen.findByText('内容创作数字员工')
    await userEvent.click(screen.getByRole('button', { name: '配置' }))
    await screen.findByLabelText('系统提示词')

    await userEvent.selectOptions(screen.getByLabelText('自治等级'), 'full_auto')

    expect(await screen.findByText(/仅超级管理员可设置，且该变更会写入审计/)).toBeInTheDocument()
  })
})
