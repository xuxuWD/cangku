import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeAccessPage } from './KnowledgeAccessPage'

const directoryRoles = [{ role_key: 'content-operator', name: '自媒体运营岗' }]
const directoryAgents = [{ agent_key: 'content-writer', name: '内容创作数字员工', role_key: 'content-operator' }]

// 候选对象来自目录接口（「数字员工设置」）：这里必须按真实契约返回 items/total。
function mockFetch(
  binding = ['company-general', 'content-operations'],
  directory: { roles: Array<Record<string, string>>; agents: Array<Record<string, string>> } = { roles: directoryRoles, agents: directoryAgents },
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes('/workforce/roles')) return { ok: true, json: async () => ({ items: directory.roles, total: directory.roles.length, limit: 200, offset: 0 }) } as Response
    if (path.includes('/workforce/agents')) return { ok: true, json: async () => ({ items: directory.agents, total: directory.agents.length, limit: 200, offset: 0 }) } as Response
    if (path.includes('/audits')) return { ok: true, json: async () => [] } as Response
    if (init?.method === 'PUT') return { ok: true, json: async () => ({ binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: binding }) } as Response
    return { ok: true, json: async () => ({ binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: binding }) } as Response
  })
}

describe('KnowledgeAccessPage', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('loads scopes, toggles count and saves with feedback', async () => {
    vi.stubGlobal('fetch', mockFetch())
    render(<KnowledgeAccessPage />)
    await waitFor(() => expect(screen.getByText('可以使用的知识库')).toBeInTheDocument())
    expect(screen.getByText('已选择 2 个')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /财务与经营数据/ }))
    expect(screen.getByText('已选择 3 个')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存调整' }))
    expect(screen.getByRole('button', { name: '正在保存' })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已保存权限调整'))
  })
  it('shows retryable network error without losing the page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    render(<KnowledgeAccessPage />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('权限服务暂时不可用'))
  })
  it('reads candidate subjects from the directory instead of a hardcoded list', async () => {
    vi.stubGlobal('fetch', mockFetch())
    render(<KnowledgeAccessPage />)

    await waitFor(() => expect(screen.getByText('可以使用的知识库')).toBeInTheDocument())
    // 下拉选项来自目录数据（含中文名），不再出现写死的「Vibe Coding 岗」
    expect(screen.getByRole('option', { name: '自媒体运营岗' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Vibe Coding/ })).not.toBeInTheDocument()
    expect(screen.getByText('共 1 个启用中的岗位')).toBeInTheDocument()
  })
  it('points to the directory settings when there is nothing to configure', async () => {
    vi.stubGlobal('fetch', mockFetch(['company-general'], { roles: [], agents: [] }))
    render(<KnowledgeAccessPage />)

    expect(await screen.findByText('还没有可配置的岗位或数字员工')).toBeInTheDocument()
    expect(screen.getByText(/请先在「数字员工设置」中创建岗位与数字员工/)).toBeInTheDocument()
  })
})
