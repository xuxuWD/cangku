import { getKnowledgeAccess, getKnowledgeAudits, saveKnowledgeAccess } from './api'

describe('knowledge access api', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('uses versioned role endpoint and parses binding', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => ({ ok: true, json: async () => ({ binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: ['b', 'a'] }) }) as Response)
    vi.stubGlobal('fetch', fetchMock)
    await expect(getKnowledgeAccess('role', 'content-operator')).resolves.toMatchObject({ knowledge_base_ids: ['b', 'a'] })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/knowledge-access/roles/content-operator')
  })
  it('sends an idempotency key when saving', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => ({ ok: true, json: async () => ({ knowledge_base_ids: ['a'] }) }) as Response)
    vi.stubGlobal('fetch', fetchMock)
    await saveKnowledgeAccess('agent', 'writer', ['a'], 'agent:writer:a')
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({ 'Idempotency-Key': 'agent:writer:a' })
  })
  it('normalizes unauthorized responses into a Chinese error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json: async () => ({}) }) as Response))
    await expect(getKnowledgeAudits()).rejects.toMatchObject({ status: 403, unauthorized: true, message: '当前账号没有配置知识权限的权限。' })
  })
})
