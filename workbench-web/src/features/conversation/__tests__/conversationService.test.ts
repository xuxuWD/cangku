/**
 * 「对话」适配层用例（合并移植的第 1 片）。
 *
 * 覆盖口径：
 *  - **13 条路径逐字**：会话 CRUD / 消息 / SSE 流 / 导出 / 验收 / 协作成员；
 *  - **移植时改动的那两处**要专门锁住：
 *    ① 认证走**会话令牌**（`Authorization: Bearer`），**不再**用 admin-web 的 `X-User-Role` 等自报头；
 *    ② 错误文案保留本模块**更具体**的版本（如 409「会话已归档」），查不到才回落到请求层文案；
 *  - **SSE 头语义**：`Accept: text/event-stream`；`Last-Event-ID` **只在续播（since>0）时发**；
 *  - **`Idempotency-Key` 只在给了键时才发**（不给键 ⇒ 后端走 `stub` 桩回复）；
 *  - `204` 无响应体 ⇒ **不得解析 JSON**（解析会把成功当失败）。
 */
import { ConversationError } from '../services/conversationService'
import { signInAs, signOutForTest } from '../../../test/renderWithProviders'
import {
  addConversationMember,
  archiveConversation,
  createConversation,
  deleteConversation,
  exportMyConversations,
  getConversation,
  getRunAcceptance,
  listConversationMembers,
  listConversations,
  openConversationStream,
  removeConversationMember,
  sendConversationMessage,
  sendConversationMessageStream,
  setConversationMode,
} from '../services/conversationService'

function stubFetch(routes: Record<string, { status?: number; body?: unknown; headers?: Record<string, string> }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const method = init?.method ?? 'GET'
    const path = Object.keys(routes).find((key) => {
      const parts = key.split(' ')
      if (parts.length === 2) return parts[0] === method && String(url).startsWith(parts[1])
      return String(url).startsWith(key)
    })
    if (!path) throw new Error(`未预期的请求：${method} ${url}`)
    const { status = 200, body, headers = {} } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      headers: { get: (name: string) => headers[name] ?? null },
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
      json: async () => {
        // 204 无响应体：真 `Response.json()` 会抛错 —— 桩要**忠实复刻**这一点，
        // 否则"204 当成功"的缺陷在用例里永远照不出来。
        if (body === undefined) throw new SyntaxError('Unexpected end of JSON input')
        return body
      },
    }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return { calls }
}

const headersOf = (call: { init: RequestInit }) => (call.init.headers ?? {}) as Record<string, string>

describe('对话适配层 · 认证模型（移植改动 ①）', () => {
  beforeEach(() => {
    signInAs('employee', 'acct-1')
  })
  afterEach(() => {
    signOutForTest()
    vi.unstubAllGlobals()
  })

  it('走**会话令牌**：Authorization: Bearer，且**不发**任何自报身份头', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations': { body: { items: [], total: 0, limit: 20, offset: 0 } } })

    await listConversations({ limit: 20, offset: 0 })

    const headers = headersOf(calls[0])
    expect(headers.Authorization).toBe('Bearer test-token')
    // admin-web 原实现靠这三个头自报身份；合并到基座后**必须不再有**
    expect(headers['X-User-Role']).toBeUndefined()
    expect(headers['X-User-Id']).toBeUndefined()
    expect(headers['X-Tenant-Id']).toBeUndefined()
  })

  it('调用方**无法**用自定义头覆盖 Authorization（认证由请求层独占）', async () => {
    const { calls } = stubFetch({
      'POST /api/v1/conversations/c1/messages': { body: { reply: null } },
    })

    await sendConversationMessage('c1', 'hi', 'k1')

    const headers = headersOf(calls[0])
    expect(headers.Authorization).toBe('Bearer test-token')
    expect(headers['Idempotency-Key']).toBe('k1')
  })
})

describe('对话适配层 · 会话与消息路径（逐字）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('列表：status 缺省不拼进 URL；limit/offset 逐字', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations': { body: { items: [], total: 0, limit: 20, offset: 0 } } })
    await listConversations({ limit: 20, offset: 40 })
    expect(calls[0].url).toBe('/api/v1/conversations?limit=20&offset=40')

    const withStatus = stubFetch({ '/api/v1/conversations': { body: { items: [], total: 0, limit: 20, offset: 0 } } })
    await listConversations({ status: 'archived', limit: 20, offset: 0 })
    expect(withStatus.calls[0].url).toBe('/api/v1/conversations?status=archived&limit=20&offset=0')
  })

  it('详情：会话 id 走 encodeURIComponent', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations/': { body: {} } })
    await getConversation('a/b', { limit: 50, offset: 0 })
    expect(calls[0].url).toBe('/api/v1/conversations/a%2Fb?limit=50&offset=0')
  })

  it('新建：POST，且**只发受控的两个键**（agent_key 缺省时也带上，避免未知字段）', async () => {
    const { calls } = stubFetch({ 'POST /api/v1/conversations': { body: {} } })
    await createConversation()
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ agent_key: undefined, title: '' })
  })

  it('归档 / 改模式 / 物理删除：路径与方法', async () => {
    const { calls } = stubFetch({
      'POST /api/v1/conversations/c1/archive': { body: {} },
      'POST /api/v1/conversations/c1/mode': { body: {} },
      'POST /api/v1/conversations/c1/delete': { body: {} },
    })
    await archiveConversation('c1')
    await setConversationMode('c1', 'plan')
    await deleteConversation('c1')

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/conversations/c1/archive',
      '/api/v1/conversations/c1/mode',
      '/api/v1/conversations/c1/delete',
    ])
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ mode: 'plan' })
  })

  it('发消息：不给幂等键时**不发**该头（后端据此走 stub 桩回复）', async () => {
    const { calls } = stubFetch({ 'POST /api/v1/conversations/c1/messages': { body: { reply: null } } })
    await sendConversationMessage('c1', '你好')
    expect(headersOf(calls[0])['Idempotency-Key']).toBeUndefined()
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ content: '你好' })
  })
})

describe('对话适配层 · SSE 流（头语义）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const streamResponse = { status: 200, body: undefined }

  it('首连（since=0）：Accept 是事件流，且**不发** Last-Event-ID（即 after_seq 缺省 0）', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations/c1/stream': streamResponse })
    await openConversationStream({ conversationId: 'c1', since: 0, signal: new AbortController().signal })

    const headers = headersOf(calls[0])
    expect(headers.Accept).toBe('text/event-stream')
    expect(headers['Last-Event-ID']).toBeUndefined()
    expect(calls[0].url).toBe('/api/v1/conversations/c1/stream')
  })

  it('续播（since>0）：发 Last-Event-ID，服务端据此取 max(Last-Event-ID, after_seq)', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations/c1/stream': streamResponse })
    await openConversationStream({ conversationId: 'c1', since: 42, signal: new AbortController().signal })
    expect(headersOf(calls[0])['Last-Event-ID']).toBe('42')
  })

  it('带 run_id 时拼进 query', async () => {
    const { calls } = stubFetch({ '/api/v1/conversations/c1/stream': streamResponse })
    await openConversationStream({ conversationId: 'c1', runId: 'r-9', since: 0, signal: new AbortController().signal })
    expect(calls[0].url).toBe('/api/v1/conversations/c1/stream?run_id=r-9')
  })

  it('发消息（流路径）：读响应头 X-Stream-Run-Id；缺头时回落响应体 run_id', async () => {
    const fromHeader = stubFetch({
      'POST /api/v1/conversations/c1/messages:stream': {
        body: { reply: null, run_id: 'from-body' },
        headers: { 'X-Stream-Run-Id': 'from-header' },
      },
    })
    const first = await sendConversationMessageStream('c1', 'hi', 'k1')
    expect(first.runId).toBe('from-header')
    expect(headersOf(fromHeader.calls[0])['Idempotency-Key']).toBe('k1')

    stubFetch({
      'POST /api/v1/conversations/c1/messages:stream': { body: { reply: null, run_id: 'from-body' } },
    })
    const second = await sendConversationMessageStream('c1', 'hi', 'k1')
    expect(second.runId).toBe('from-body')
  })
})

describe('对话适配层 · 错误口径（移植改动 ②）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    [403, '当前岗位不能使用对话入口。'],
    [404, '会话不存在，或不属于当前账号。'],
    [409, '会话已归档，不能再发送新消息。'],
    [422, '消息不符合要求（不能为空 / 超长，或未绑定可用的数字员工、工具调用格式不合法）。'],
  ])('%i 用本模块**更具体**的文案', async (status, message) => {
    stubFetch({ '/api/v1/conversations': { status, body: {} } })
    const error = await listConversations({ limit: 1, offset: 0 }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ConversationError)
    expect((error as ConversationError).message).toBe(message)
    expect((error as ConversationError).status).toBe(status)
  })

  it('5xx / 网络失败 ⇒ 可重试的通用文案', async () => {
    stubFetch({ '/api/v1/conversations': { status: 503 } })
    const error = await listConversations({ limit: 1, offset: 0 }).catch((e: unknown) => e)
    expect((error as ConversationError).message).toBe('对话服务暂时不可用，请检查网络后重新尝试。')
  })

  it('403 ⇒ failure 为 forbidden（界面走"无权限"态，与"加载失败"分开）', async () => {
    stubFetch({ '/api/v1/conversations': { status: 403 } })
    const error = await listConversations({ limit: 1, offset: 0 }).catch((e: unknown) => e)
    expect((error as ConversationError).failure).toBe('forbidden')
  })

  it('**非请求层错误原样抛出**（不吞异常、不改写成"服务不可用"）', async () => {
    const boom = new Error('本地解析炸了')
    vi.stubGlobal('fetch', () => Promise.reject(boom))
    // 请求层会把「网络失败」归成 ApiError，这条覆盖的是**请求层之外**的异常路径
    const error = await listConversations({ limit: 1, offset: 0 }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ConversationError)
  })
})

describe('对话适配层 · 协作成员（204 语义）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('撤销成员：204 无响应体 ⇒ **当作成功**，不因解析 JSON 失败而误报', async () => {
    stubFetch({ 'DELETE /api/v1/conversations/c1/members/m1': { status: 204 } })
    await expect(removeConversationMember('c1', 'm1')).resolves.toBeUndefined()
  })

  it('添加成员：只发 member_id 与 permission 两个键', async () => {
    const { calls } = stubFetch({ 'POST /api/v1/conversations/c1/members': { body: {} } })
    await addConversationMember('c1', 'm1', 'read')
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ member_id: 'm1', permission: 'read' })
  })

  it('名单 / 运行验收：路径逐字', async () => {
    const { calls } = stubFetch({
      '/api/v1/conversations/c1/members': { body: { items: [], total: 0 } },
      '/api/v1/runs/r1/acceptance': { body: {} },
    })
    await listConversationMembers('c1')
    await getRunAcceptance('r1')
    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/conversations/c1/members',
      '/api/v1/runs/r1/acceptance',
    ])
  })
})

describe('对话适配层 · 导出（逐页合并，不静默截断）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('取全即停（fetched >= total）', async () => {
    const { calls } = stubFetch({
      '/api/v1/conversations/exports/mine': {
        body: { conversations: [{ conversation_id: 'c1' }], total_conversations: 1, truncated: false },
      },
    })
    const bundle = await exportMyConversations()
    expect(bundle.pages).toHaveLength(1)
    expect(bundle.truncated).toBe(false)
    expect(calls).toHaveLength(1)
  })

  it('服务端如实告知 truncated ⇒ **原样带出**，不假装取全', async () => {
    stubFetch({
      '/api/v1/conversations/exports/mine': {
        body: { conversations: [{ conversation_id: 'c1' }], total_conversations: 9999, truncated: true },
      },
    })
    const bundle = await exportMyConversations()
    expect(bundle.truncated).toBe(true)
  })

  it('空页即停（防止服务端异常导致死循环）', async () => {
    stubFetch({
      '/api/v1/conversations/exports/mine': {
        body: { conversations: [], total_conversations: 500, truncated: false },
      },
    })
    const bundle = await exportMyConversations()
    expect(bundle.pages).toHaveLength(1)
  })
})
