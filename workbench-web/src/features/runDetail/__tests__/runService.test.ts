/**
 * 「运行详情 / 干预 / 验收 / 沉淀」适配层用例（切片 2a）。
 *
 * 覆盖口径：
 *  - **13 条路径逐字**（读取 6 + 干预 3 + 验收 2 + 沉淀 1 + 幂等键 1）；
 *  - **两类错误口径必须分开**：读取类的 403/404 用固定文案；干预类的 409/422 **优先服务端原因**；
 *  - ⚠️ **本次修掉的一个缺陷**：原 `asRunError` 靠 `candidate.retryable !== false` 判定，
 *    而基座 `ApiError` 没有该字段 ⇒ 恒为可重试，**403 也会被重试**。改为按状态码判定；
 *  - **认证走会话令牌**，不再发 `X-User-Role` 等自报头；
 *  - 验收决议**只发三个受控键**（后端 `extra=forbid`）。
 */
import { signInAs, signOutForTest } from '../../../test/renderWithProviders'
import { asRunError, runActionErrorFromStatus, runErrorFromStatus, RunError } from '../state'
import {
  cancelRun,
  decideRunAcceptance,
  decideRunApproval,
  getRunMetrics,
  getTask,
  listRunAcceptanceDecisions,
  listRunArtifacts,
  listRunApprovals,
  listRunEvents,
  newAcceptanceIdempotencyKey,
  pauseRun,
  promoteRunToTask,
  resumeRun,
} from '../services/runService'

function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
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
    const { status = 200, body } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchImpl)
  return { calls }
}

const headersOf = (call: { init: RequestInit }) => (call.init.headers ?? {}) as Record<string, string>

describe('运行适配层 · 认证模型（与对话同一口径）', () => {
  beforeEach(() => signInAs('employee', 'acct-1'))
  afterEach(() => {
    signOutForTest()
    vi.unstubAllGlobals()
  })

  it('走会话令牌，且**不发**任何自报身份头', async () => {
    const { calls } = stubFetch({ '/api/v1/runs/r1/metrics': { body: {} } })
    await getRunMetrics('r1')

    const headers = headersOf(calls[0])
    expect(headers.Authorization).toBe('Bearer test-token')
    expect(headers['X-User-Role']).toBeUndefined()
    expect(headers['X-User-Id']).toBeUndefined()
    expect(headers['X-Tenant-Id']).toBeUndefined()
  })
})

describe('运行适配层 · 路径逐字', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('读取六条：路径与方法', async () => {
    const { calls } = stubFetch({
      '/api/v1/runs/r1/metrics': { body: {} },
      '/api/v1/tasks/t1': { body: {} },
      '/api/v1/runs/r1/events': { body: [] },
      '/api/v1/runs/r1/approvals': { body: { items: [] } },
      '/api/v1/runs/r1/artifacts': { body: { items: [] } },
      '/api/v1/runs/r1/acceptance/decisions': { body: { items: [] } },
    })
    await getRunMetrics('r1')
    await getTask('t1')
    await listRunEvents('r1')
    await listRunApprovals('r1')
    await listRunArtifacts('r1')
    await listRunAcceptanceDecisions('r1')

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/runs/r1/metrics',
      '/api/v1/tasks/t1',
      '/api/v1/runs/r1/events',
      '/api/v1/runs/r1/approvals',
      '/api/v1/runs/r1/artifacts',
      '/api/v1/runs/r1/acceptance/decisions',
    ])
    for (const call of calls) expect(call.init.method ?? 'GET').toBe('GET')
  })

  it('id 走 encodeURIComponent', async () => {
    const { calls } = stubFetch({ '/api/v1/runs/': { body: {} } })
    await getRunMetrics('a/b')
    expect(calls[0].url).toBe('/api/v1/runs/a%2Fb/metrics')
  })

  it('审批决议：POST + `{approved}`；干预三端点：POST；暂停/取消带 `reason`', async () => {
    const { calls } = stubFetch({
      'POST /api/v1/runs/r1/approvals/a1/approval': { body: {} },
      'POST /api/v1/runs/r1/pause': { body: {} },
      'POST /api/v1/runs/r1/resume': { body: {} },
      'POST /api/v1/runs/r1/cancel': { body: {} },
    })
    await decideRunApproval('r1', 'a1', true)
    await pauseRun('r1', '需要人工确认')
    await resumeRun('r1')
    await cancelRun('r1', '不再需要')

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/runs/r1/approvals/a1/approval',
      '/api/v1/runs/r1/pause',
      '/api/v1/runs/r1/resume',
      '/api/v1/runs/r1/cancel',
    ])
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ approved: true })
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ reason: '需要人工确认' })
    // 恢复**不带** body（服务端无需 reason）
    expect(calls[2].init.body).toBeUndefined()
    expect(JSON.parse(String(calls[3].init.body))).toEqual({ reason: '不再需要' })
  })

  it('验收决议：只发三个受控键；沉淀：POST + `{title}`', async () => {
    const { calls } = stubFetch({
      'POST /api/v1/runs/r1/acceptance/decisions': { body: { created: true } },
      'POST /api/v1/runs/r1/acceptance/tasks': { body: { created: true } },
    })
    await decideRunAcceptance('r1', { decision: 'confirmed', idempotencyKey: 'k-1' })
    await promoteRunToTask('r1', '存成任务：季度内容排期')

    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      decision: 'confirmed',
      reason: '',
      idempotency_key: 'k-1',
    })
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ title: '存成任务：季度内容排期' })
  })

  it('幂等键：格式带前缀且**每次不同**', () => {
    const a = newAcceptanceIdempotencyKey()
    const b = newAcceptanceIdempotencyKey()
    expect(a.startsWith('acceptance-')).toBe(true)
    expect(a).not.toBe(b)
  })
})

describe('运行适配层 · 两类错误口径（必须分开）', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('**读取类** 403：优先服务端文案；404 用固定文案', async () => {
    stubFetch({ '/api/v1/runs/r1/metrics': { status: 403, body: { detail: '只有发起人可以查看这个运行' } } })
    const forbidden = await getRunMetrics('r1').catch((e: unknown) => e)
    expect((forbidden as RunError).message).toBe('只有发起人可以查看这个运行')

    stubFetch({ '/api/v1/runs/r1/metrics': { status: 404, body: { detail: '内部细节不该透出' } } })
    const notFound = await getRunMetrics('r1').catch((e: unknown) => e)
    expect((notFound as RunError).message).toBe('运行不存在，或你没有权限查看。')
  })

  it('**干预类** 409 / 422：**优先原样展示服务端原因**（如"运行已结束"）', async () => {
    stubFetch({ 'POST /api/v1/runs/r1/pause': { status: 409, body: { detail: '运行已结束' } } })
    const conflict = await pauseRun('r1', 'x').catch((e: unknown) => e)
    expect((conflict as RunError).message).toBe('运行已结束')

    stubFetch({ 'POST /api/v1/runs/r1/cancel': { status: 422, body: { detail: '取消原因不能为空' } } })
    const invalid = await cancelRun('r1', '').catch((e: unknown) => e)
    expect((invalid as RunError).message).toBe('取消原因不能为空')
  })

  it('干预类 409 无服务端原因时用兜底文案', async () => {
    stubFetch({ 'POST /api/v1/runs/r1/resume': { status: 409, body: {} } })
    const error = await resumeRun('r1').catch((e: unknown) => e)
    expect((error as RunError).message).toBe('该运行当前的状态不允许此操作，正在刷新最新状态。')
  })
})

describe('⚠️ 本次修掉的缺陷：可重试性判定的口径', () => {
  it('**403 绝不标成可重试**（原实现 `candidate.retryable !== false` 恒真 ⇒ 会重试）', () => {
    expect(runErrorFromStatus(403).retryable).toBe(false)
    expect(runActionErrorFromStatus(403).retryable).toBe(false)
    expect(asRunError(new RunError('无权限', 'forbidden', 403)).retryable).toBe(false)
  })

  it('409 / 422 / 404 / 401 一律不可重试', () => {
    for (const status of [401, 404, 409, 422]) {
      expect(asRunError(new RunError('x', 'failed', status)).retryable).toBe(false)
    }
  })

  it('网络失败（0）与 5xx 可重试', () => {
    expect(asRunError(new RunError('x', 'failed', 0)).retryable).toBe(true)
    expect(asRunError(new RunError('x', 'failed', 503)).retryable).toBe(true)
  })

  it('非本层对象按状态码判定，**不看** retryable 字段', () => {
    // 一个"声称可重试的 403"也必须被判定为不可重试
    expect(asRunError({ status: 403, message: '无权限', retryable: true }).retryable).toBe(false)
    // 未知形状 ⇒ 兜底可重试（网络类）
    expect(asRunError(new Error('boom')).retryable).toBe(true)
  })
})
