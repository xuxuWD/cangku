/**
 * 「协同动态」适配层用例。
 *
 * 覆盖口径：
 *  - 读：`GET /api/v1/collaboration-dynamics`，`limit` 参数逐字正确；
 *  - **形状不符即抛错**（服务端返回裸数组；非数组 = 契约被破坏，**不得**静默当成"没有动态"）；
 *  - `403` ⇒ `forbidden`；
 *  - 样例模式：不发任何请求。
 */
import { ServiceError } from '../../../utils/serviceKit'
import { DYNAMICS_LIMIT, fetchDynamics, isConnected, setServiceMode } from '../services/dynamicsService'

function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return { status, ok: status >= 200 && status < 300, text: async () => (body === undefined ? '' : JSON.stringify(body)) }
  }) as unknown as typeof fetch
  return { calls, fetchImpl }
}

const ROW = {
  event_id: 'dyn-1',
  aggregate_id: 'task-1',
  action: 'task.queued',
  title: '任务进入执行队列',
  employee_key: 'content-writer',
  status: 'queued',
  tenant_id: 'demo-tenant',
  project_id: null,
  created_by: 'acct-1',
  occurred_at: '2026-09-23T02:05:00Z',
}

describe('协同动态适配层', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('样例模式：不发任何请求', async () => {
    const { calls, fetchImpl } = stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW] } })
    setServiceMode('mock')

    const items = await fetchDynamics(DYNAMICS_LIMIT, fetchImpl)

    expect(calls).toHaveLength(0)
    expect(items.length).toBeGreaterThan(0)
  })

  it('读路径：limit 逐字正确，返回裸数组', async () => {
    const { calls, fetchImpl } = stubFetch({ '/api/v1/collaboration-dynamics': { body: [ROW] } })
    setServiceMode('http')

    const items = await fetchDynamics(20, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/collaboration-dynamics?limit=20')
    expect(calls[0].init.method).toBe('GET')
    expect(items).toHaveLength(1)
    expect(items[0].event_id).toBe('dyn-1')
  })

  it('响应不是数组 ⇒ 抛错（**不得**静默当成"没有动态"）', async () => {
    const { fetchImpl } = stubFetch({ '/api/v1/collaboration-dynamics': { body: { items: [] } } })
    setServiceMode('http')

    await expect(fetchDynamics(DYNAMICS_LIMIT, fetchImpl)).rejects.toThrow()
  })

  it('403 ⇒ forbidden', async () => {
    const { fetchImpl } = stubFetch({ '/api/v1/collaboration-dynamics': { status: 403 } })
    setServiceMode('http')

    const error = await fetchDynamics(DYNAMICS_LIMIT, fetchImpl).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ServiceError)
    expect((error as ServiceError).failure).toBe('forbidden')
  })

  it('isConnected 随模式切换', () => {
    setServiceMode('http')
    expect(isConnected()).toBe(true)
    setServiceMode('mock')
    expect(isConnected()).toBe(false)
  })
})
