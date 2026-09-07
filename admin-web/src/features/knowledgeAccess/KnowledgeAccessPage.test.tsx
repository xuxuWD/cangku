import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeAccessPage } from './KnowledgeAccessPage'

function mockFetch(binding = ['company-general', 'content-operations']) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
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
})
