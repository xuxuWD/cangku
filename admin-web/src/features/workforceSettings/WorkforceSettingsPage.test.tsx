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
  /** P2c-4：候选端点（模型键 / 工具目录）返回异常状态，用于验证「回落自由文本」。 */
  candidatesStatus?: number
  /** P2c-4：读取到的配置里 `model_key` 覆盖值（用于验证「当前值不在候选内 ⇒ 灰显给原因」）。 */
  modelKey?: string
}

// P2c-4：模型候选与工具目录（`items` = 执行目录；`allowlist` = 保存闸门集合）。
export const MODEL_CANDIDATES = { items: ['mock-default', 'deepseek-chat'], total: 2 }
export const TOOL_CATALOG = {
  items: [
    { tool_key: 'fs.read', risk_level: 'low', requires_approval: false, has_side_effect: false, reversible: true, params: [{ name: 'path', role: 'control' }] },
    { tool_key: 'artifact.export', risk_level: 'critical', requires_approval: true, has_side_effect: true, reversible: false, params: [{ name: 'path', role: 'control' }] },
  ],
  allowlist: ['fs.read', 'knowledge.search'],
  total: 2,
}

// 假服务端：GET 返回当前目录内容，POST/PATCH 会真的改动内存中的目录，
// 这样「写成功后列表刷新能看到新内容」也是被验证过的，而不只是断言请求发出去了。
function makeFetch(directory: Directory, options: Options = {}) {
  const calls: Array<{ url: string; method: string; body: string }> = []
  let getBatches = 0
  const config = { agent_key: 'content-writer', system_prompt: '你是内容创作助手', model_key: options.modelKey ?? 'mock-default', temperature: 0.2, tool_allowlist: [], memory_policy: { short_term_enabled: true, short_term_turns: 6 }, autonomy_level: 'approval_for_risky', risk_threshold: 'high', approval_timeout_minutes: 60, daily_budget_cents: 0, updated_at: '2026-09-12T07:28:57.796743Z' }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })
    if (url.includes('/inbox?')) return json({ items: [], unread_count: 0 })
    if (options.getStatus && options.getStatus >= 400) return json({ detail: '只有超级管理员可以管理岗位与数字员工目录' }, options.getStatus)

    if (url.includes('/workforce/model-candidates')) {
      if (options.candidatesStatus && options.candidatesStatus >= 400) return json({ detail: '只有超级管理员可以读取模型与工具候选' }, options.candidatesStatus)
      return json(MODEL_CANDIDATES)
    }
    if (url.includes('/tools/catalog')) {
      if (options.candidatesStatus && options.candidatesStatus >= 400) return json({ detail: '只有超级管理员可以读取模型与工具候选' }, options.candidatesStatus)
      return json(TOOL_CATALOG)
    }

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

    expect(await screen.findByRole('alert')).toHaveTextContent('名单暂时读不出来')

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

// ---------------------------------------------------------------- P2c-4 只读候选端点（选择器）

describe('WorkforceSettingsPage（P2c-4 选择器）', () => {
  afterEach(() => vi.unstubAllGlobals())

  async function openConfig() {
    await userEvent.click(await screen.findByRole('tab', { name: '数字员工' }))
    await screen.findByText('内容创作数字员工')
    await userEvent.click(screen.getByRole('button', { name: '配置' }))
    await screen.findByLabelText('系统提示词')
  }

  it('模型键为候选下拉（含默认项）；未注册的当前值灰显并给原因', async () => {
    const { fetchMock } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await openConfig()

    const select = screen.getByLabelText('模型键') as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    expect(select.value).toBe('mock-default')
    const options = Array.from(select.options).map((option) => option.value)
    expect(options).toEqual(expect.arrayContaining(['', 'mock-default', 'deepseek-chat']))
    expect(screen.getByText(/可选 2 个，来自本部署已登记的模型键/)).toBeInTheDocument()
  })

  it('当前模型键不在候选内 ⇒ 灰显选项 + 原因（保存会被后端 422 拒绝）', async () => {
    const { fetchMock } = makeFetch(
      { roles: [], agents: [agent()], candidates: { roles: [], agents: [] } },
      { modelKey: 'legacy-model' },
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await openConfig()

    const select = screen.getByLabelText('模型键') as HTMLSelectElement
    expect(select.value).toBe('legacy-model')
    const disabled = Array.from(select.options).filter((option) => option.disabled)
    expect(disabled).toHaveLength(1)
    expect(disabled[0].textContent).toContain('本部署没有登记这个模型键')
  })

  it('工具白名单为目录多选：闸门内的目录项可勾选，闸门外的灰显并给原因', async () => {
    const { fetchMock, calls } = makeFetch({ roles: [], agents: [agent()], candidates: { roles: [], agents: [] } })
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await openConfig()

    // `fs.read` 在保存闸门内 ⇒ 可勾选；`artifact.export` 不在闸门内 ⇒ 灰显 + 原因。
    const gateTool = screen.getByLabelText('工具 fs.read')
    const blockedTool = screen.getByLabelText('工具 artifact.export')
    expect(gateTool).not.toBeDisabled()
    expect(blockedTool).toBeDisabled()
    expect(screen.getByText(/本部署未提供该工具：勾选后保存会被拒绝/)).toBeInTheDocument()
    // 保存闸门里的目录外键也要出现（否则管理员无法勾选合法键）。
    expect(screen.getByLabelText('工具 knowledge.search')).not.toBeDisabled()

    await userEvent.click(gateTool)
    await userEvent.click(screen.getByRole('button', { name: '保存配置' }))

    await waitFor(() => {
      const patch = calls.find((call) => call.method === 'PATCH' && call.url.includes('/config'))
      expect(patch && JSON.parse(patch.body).tool_allowlist).toEqual(['fs.read'])
    })
  })

  it('候选端点不可用（403 / 形态不完整）⇒ 回落自由文本并**如实告知**，不摆假选项', async () => {
    const { fetchMock } = makeFetch(
      { roles: [], agents: [agent()], candidates: { roles: [], agents: [] } },
      { candidatesStatus: 403 },
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<WorkforceSettingsPage />)
    await openConfig()

    const modelInput = screen.getByLabelText('模型键')
    expect(modelInput.tagName).toBe('INPUT')
    expect(screen.getByText(/暂时读不到可选的模型清单（当前账号没有管理岗位与数字员工的权限。）/)).toBeInTheDocument()
    const toolInput = screen.getByLabelText('工具白名单')
    expect(toolInput.tagName).toBe('INPUT')
    expect(screen.getByText(/暂时读不到工具清单/)).toBeInTheDocument()
  })
})
