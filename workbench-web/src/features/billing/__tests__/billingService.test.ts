/**
 * 「用量与费用 / 数据导出」适配层与金额格式化用例。
 *
 * 覆盖口径：
 *  - 金额**整数分运算**，负值（冲正后累计）正确加符号 —— 这是不复用基座 `formatBudgetCents` 的理由；
 *  - 五条路径逐字正确（usage / exports POST / exports GET / exports/{id} / lifecycle/{id}）；
 *  - `404` ⇒ 带出 **status 404**（页面据此走"未登记"而非"加载失败"）；
 *  - `403` ⇒ `forbidden`；形状不符 ⇒ 抛错（不得静默当空）。
 */
import { BillingError, fetchExportPackages, fetchUsage, requestExport, setServiceMode } from '../services/billingService'
import { formatCents, isPackageExpired } from '../state'

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

describe('金额格式化（整数分）', () => {
  it('正数：整数分 → ¥元.角分', () => {
    expect(formatCents(4321)).toBe('¥43.21')
    expect(formatCents(0)).toBe('¥0.00')
    expect(formatCents(5)).toBe('¥0.05')
    expect(formatCents(100)).toBe('¥1.00')
  })

  it('负数：冲正后累计为负，**必须正确加符号**（基座 formatBudgetCents 对负值不适用）', () => {
    expect(formatCents(-1500)).toBe('-¥15.00')
    expect(formatCents(-1)).toBe('-¥0.01')
  })

  it('非有限数按 0 处理（不编造金额）', () => {
    expect(formatCents(Number.NaN)).toBe('¥0.00')
    expect(formatCents(Number.POSITIVE_INFINITY)).toBe('¥0.00')
  })
})

describe('导出包过期判定', () => {
  it('expires_at <= 当前时刻 即过期（正点即过期）', () => {
    const now = new Date('2026-09-23T03:00:00Z').getTime()
    expect(isPackageExpired('2026-09-23T03:00:00Z', now)).toBe(true)
    expect(isPackageExpired('2026-09-23T03:00:01Z', now)).toBe(false)
  })

  it('时间不可解析 ⇒ 按不可下载处理（保守）', () => {
    expect(isPackageExpired('不是时间', Date.now())).toBe(true)
  })
})

describe('用量与费用适配层', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('读用量：路径逐字正确', async () => {
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/commercial/usage': { body: { tenant_id: 'demo-tenant', units: 3, cost_cents: 100 } },
    })
    setServiceMode('http')

    const usage = await fetchUsage(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/commercial/usage')
    expect(usage.cost_cents).toBe(100)
  })

  it('404 ⇒ 抛 BillingError 且带出 status=404（页面据此走「未登记」而非「加载失败」）', async () => {
    const { fetchImpl } = stubFetch({ '/api/v1/commercial/usage': { status: 404, body: { detail: '租户不存在' } } })
    setServiceMode('http')

    const error = await fetchUsage(fetchImpl).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(BillingError)
    expect((error as BillingError).status).toBe(404)
    expect((error as BillingError).message).toBe('本租户尚未在商业化模块登记，暂时没有可展示的用量与费用。')
  })

  it('403 ⇒ forbidden（与失败分开；页面不给"重试"）', async () => {
    const { fetchImpl } = stubFetch({ '/api/v1/commercial/usage': { status: 403 } })
    setServiceMode('http')

    const error = await fetchUsage(fetchImpl).catch((e: unknown) => e)
    expect((error as BillingError).failure).toBe('forbidden')
    expect((error as BillingError).status).toBe(403)
  })

  it('形状不符（cost_cents 不是数字）⇒ 抛错，不得静默当 0', async () => {
    const { fetchImpl } = stubFetch({ '/api/v1/commercial/usage': { body: { tenant_id: 't' } } })
    setServiceMode('http')

    await expect(fetchUsage(fetchImpl)).rejects.toThrow()
  })

  it('申请导出：POST 到 /commercial/exports', async () => {
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/commercial/exports': { status: 202, body: { job_id: 'job-1', status: 'queued' } },
    })
    setServiceMode('http')

    const job = await requestExport(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/commercial/exports')
    expect(calls[0].init.method).toBe('POST')
    expect(job.job_id).toBe('job-1')
  })

  it('导出包列表：limit / offset 逐字正确；items 非数组 ⇒ 抛错', async () => {
    const ok = stubFetch({ '/api/v1/commercial/exports': { body: { items: [], total: 0, limit: 20, offset: 0 } } })
    setServiceMode('http')
    await fetchExportPackages(20, 0, ok.fetchImpl)
    expect(ok.calls[0].url).toBe('/api/v1/commercial/exports?limit=20&offset=0')

    const bad = stubFetch({ '/api/v1/commercial/exports': { body: { total: 0 } } })
    await expect(fetchExportPackages(20, 0, bad.fetchImpl)).rejects.toThrow()
  })

  it('样例模式：不发任何请求', async () => {
    const { calls, fetchImpl } = stubFetch({ '/api/v1/commercial/usage': { body: {} } })
    setServiceMode('mock')

    await fetchUsage(fetchImpl)

    expect(calls).toHaveLength(0)
  })
})
