/**
 * 「审计日志」适配层用例（第 10 轮）。
 *
 * 覆盖口径（与 `docs/contracts/audit-log-api.md` §1 / §6 逐条对应）：
 *  - 读：路径与查询参数逐字正确；**动作多选走重复键**（`action=a&action=b`，非逗号拼接）；
 *    时间参数**原样透传**（前端一律 `toISOString()` 的 `Z` 形态）；
 *  - 动作目录：`GET /api/v1/audits/actions` 逐字正确；`items` 非数组即抛错；
 *  - 形状不符即抛错（不臆测、不静默补空）；`403` ⇒ `forbidden` 并保留服务端原文；
 *  - 样例模式：**不发任何请求**，`sample: true`。
 */
import {
  AUDITS_EMPTY_NOTE,
  AUDITS_NO_MATCH_NOTE,
  AUDIT_EXPORT_HINT,
  AUDIT_EXPORT_ONLY_ADMIN_NOTE,
  AUDIT_PERMISSION_REASON,
  AuditError,
  CONNECTED_DESCRIPTION,
  CONNECTED_NOTICE,
  MOCK_EXPORT_NOTE,
  MY_AUDITS_EMPTY_NOTE,
  MY_AUDITS_NO_MATCH_NOTE,
  SAMPLE_DESCRIPTION,
  SELF_SCOPE_NOTE,
  exportAudits,
  fetchAuditActions,
  fetchAudits,
  setServiceMode,
} from '../services/auditService'
import { detailEntries, isBlankQuery } from '../types'
import type { AuditQuery } from '../types'

/** 最小 `fetch` 桩（与其它模块同口径）：记录 `(url, init)` 供逐字断言。 */
function stubFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init })
    const path = Object.keys(routes).find((key) => String(url).startsWith(key))
    if (!path) throw new Error(`未预期的请求：${url}`)
    const { status = 200, body } = routes[path]
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    }
  }) as unknown as typeof fetch
  return { calls, fetchImpl }
}

const RECORD = (over: Partial<Record<string, unknown>> = {}) => ({
  record_id: '1856',
  action: 'skill.enabled',
  actor_id: 'acct-1',
  target_type: 'skill',
  target_id: 'summarize@1.0.0',
  phone_masked: null,
  detail: { skill_key: 'summarize' },
  occurred_at: '2026-09-20T18:00:12.092031Z',
  ...over,
})

const BLANK: AuditQuery = { actions: [] }
const PAGE = { limit: 50, offset: 0 }

describe('审计适配层（读路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('空条件：只带分页参数', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/audits': { body: { items: [RECORD()], total: 1, limit: 50, offset: 0 } },
    })

    const page = await fetchAudits(BLANK, PAGE, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/audits?limit=50&offset=0')
    expect(page.sample).toBe(false)
    expect(page.total).toBe(1)
    expect(page.items[0].action).toBe('skill.enabled')
    expect(page.items[0].detail).toEqual({ skill_key: 'summarize' })
  })

  it('动作多选：**重复键**展开（不是逗号拼接）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/audits': { body: { items: [], total: 0, limit: 50, offset: 0 } },
    })

    await fetchAudits({ actions: ['plan.approved', 'account.login.succeeded'] }, PAGE, fetchImpl)

    expect(calls[0].url).toBe(
      '/api/v1/audits?action=plan.approved&action=account.login.succeeded&limit=50&offset=0',
    )
  })

  it('全条件：目标 / 操作人 / 时间范围逐字进 query（时间为 Z 形态）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/audits': { body: { items: [], total: 0, limit: 50, offset: 0 } },
    })

    await fetchAudits(
      {
        actions: ['skill.enabled'],
        target_type: 'skill',
        target_id: 'summarize@1.0.0',
        actor_id: 'acct-1',
        since: '2026-09-20T00:00:00.000Z',
        until: '2026-09-21T00:00:00.000Z',
      },
      { limit: 200, offset: 100 },
      fetchImpl,
    )

    expect(calls[0].url).toBe(
      '/api/v1/audits?action=skill.enabled&target_type=skill&target_id=summarize%401.0.0' +
        '&actor_id=acct-1&since=2026-09-20T00%3A00%3A00.000Z&until=2026-09-21T00%3A00%3A00.000Z&limit=200&offset=100',
    )
  })

  it('形状不符（items 不是数组）⇒ 抛错，绝不静默当成空列表', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({ '/api/v1/audits': { body: { total: 3 } } })

    await expect(fetchAudits(BLANK, PAGE, fetchImpl)).rejects.toBeInstanceOf(AuditError)
  })

  it('403 ⇒ `forbidden`，保留服务端原文（不吞成"没有记录"）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/audits': { status: 403, body: { detail: '当前岗位不能查看审计日志' } },
    })

    const error = (await fetchAudits(BLANK, PAGE, fetchImpl).catch((caught: unknown) => caught)) as AuditError

    expect(error.kind).toBe('forbidden')
    expect(error.message).toBe('当前岗位不能查看审计日志')
  })

  it('动作目录：路径逐字正确，返回码值全集', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/audits/actions': { body: { items: ['account.login.succeeded', 'skill.enabled'], total: 2 } },
    })

    const catalog = await fetchAuditActions(fetchImpl)

    expect(calls[0].url).toBe('/api/v1/audits/actions')
    expect(catalog.items).toEqual(['account.login.succeeded', 'skill.enabled'])
    expect(catalog.total).toBe(2)
  })

  it('样例模式：不发任何请求，`sample: true`', async () => {
    setServiceMode('mock')
    const fetchImpl = (async () => {
      throw new Error('样例模式不应发请求')
    }) as unknown as typeof fetch

    const page = await fetchAudits(BLANK, PAGE, fetchImpl)
    const catalog = await fetchAuditActions(fetchImpl)

    expect(page.sample).toBe(true)
    expect(page.items.length).toBeGreaterThan(0)
    expect(catalog.sample).toBe(true)
  })
})

describe('明细渲染与空条件判定（纯函数）', () => {
  it('明细键值对：键按字典序、非字符串值 JSON 化（不当 HTML 渲染）', () => {
    const entries = detailEntries({ version: '1.0.0', count: 2, flags: { a: true }, missing: null })

    expect(entries.map((entry) => entry.key)).toEqual(['count', 'flags', 'missing', 'version'])
    expect(entries.find((entry) => entry.key === 'count')?.value).toBe('2')
    expect(entries.find((entry) => entry.key === 'flags')?.value).toBe('{"a":true}')
    expect(entries.find((entry) => entry.key === 'missing')?.value).toBe('null')
  })

  it('明细为空或缺失 ⇒ 空列表（由界面给"该记录没有明细"）', () => {
    expect(detailEntries({})).toEqual([])
    expect(detailEntries(null)).toEqual([])
  })

  it('空条件判定：区分"没有记录"与"筛选未命中"', () => {
    expect(isBlankQuery({ actions: [] })).toBe(true)
    expect(isBlankQuery({ actions: ['skill.enabled'] })).toBe(false)
    expect(isBlankQuery({ actions: [], actor_id: 'acct-1' })).toBe(false)
    expect(isBlankQuery({ actions: [], since: '2026-09-20T00:00:00.000Z' })).toBe(false)
  })
})

describe('界面文案（真机走查修正的回归钉，2026-09-21）', () => {
  /** 本模块**全部**导出文案（新增常量请一并登记，否则守卫覆盖不到）。 */
  const COPY: [string, string][] = [
    ['CONNECTED_NOTICE', CONNECTED_NOTICE],
    ['CONNECTED_DESCRIPTION', CONNECTED_DESCRIPTION],
    ['SAMPLE_DESCRIPTION', SAMPLE_DESCRIPTION],
    ['AUDITS_EMPTY_NOTE', AUDITS_EMPTY_NOTE],
    ['AUDITS_NO_MATCH_NOTE', AUDITS_NO_MATCH_NOTE],
    ['MY_AUDITS_EMPTY_NOTE', MY_AUDITS_EMPTY_NOTE],
    ['MY_AUDITS_NO_MATCH_NOTE', MY_AUDITS_NO_MATCH_NOTE],
    ['SELF_SCOPE_NOTE', SELF_SCOPE_NOTE],
    ['AUDIT_EXPORT_HINT', AUDIT_EXPORT_HINT],
    ['AUDIT_EXPORT_ONLY_ADMIN_NOTE', AUDIT_EXPORT_ONLY_ADMIN_NOTE],
    ['MOCK_EXPORT_NOTE', MOCK_EXPORT_NOTE],
    ['AUDIT_PERMISSION_REASON', AUDIT_PERMISSION_REASON],
  ]

  it('不得含 Markdown 标记（** / __）—— 渲染处是纯文本，星号会原样显示给用户', () => {
    // 背景：员工档说明原文写作 `**你自己**`，界面把星号原样渲染出来（真机走查发现）。
    const offenders = COPY.filter(([, text]) => /\*\*|__/.test(text)).map(([name]) => name)

    expect(offenders).toEqual([])
  })

  it('强调用「」而不是 Markdown（员工档说明的既定写法）', () => {
    expect(SELF_SCOPE_NOTE).toContain('「你自己」')
  })
})

describe('审计导出（第 13 轮）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  /** 文件下载的桩：要 `headers.get` 与 `blob()`，与普通 JSON 桩不同。 */
  function stubExport(headers: Record<string, string>, body = 'record_id,action\n1,skill.enabled\n') {
    const calls: string[] = []
    const fetchImpl = (async (url: string) => {
      calls.push(String(url))
      return {
        status: 200,
        ok: true,
        headers: { get: (name: string) => headers[name] ?? null },
        blob: async () => new Blob([body]),
        text: async () => body,
      }
    }) as unknown as typeof fetch
    return { calls, fetchImpl }
  }

  it('空条件：默认 csv + 上限 5000', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubExport({
      'Content-Disposition': 'attachment; filename="audit-t-1-20260921T000000Z.csv"',
      'X-Exported-Rows': '7',
    })

    const outcome = await exportAudits({ actions: [] }, {}, fetchImpl)

    expect(calls[0]).toBe('/api/v1/audits/export?format=csv&limit=5000')
    expect(outcome.downloaded).toBe(true)
    expect(outcome.rows).toBe(7)
    expect(outcome.filename).toBe('audit-t-1-20260921T000000Z.csv')
    expect(outcome.blob).not.toBeNull()
  })

  it('筛选与格式逐字拼进查询串（动作多选走**重复键**）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubExport({})

    await exportAudits(
      {
        actions: ['skill.enabled', 'skill.disabled'],
        target_type: 'skill',
        actor_id: 'acct-1',
        since: '2026-09-01T00:00:00.000Z',
      },
      { format: 'json', limit: 20 },
      fetchImpl,
    )

    expect(calls[0]).toBe(
      '/api/v1/audits/export?action=skill.enabled&action=skill.disabled&target_type=skill' +
        '&actor_id=acct-1&since=2026-09-01T00%3A00%3A00.000Z&format=json&limit=20',
    )
  })

  it('缺响应头时：行数回落 0、文件名回落默认值（不编造）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubExport({})

    const outcome = await exportAudits({ actions: [] }, {}, fetchImpl)

    expect(outcome.rows).toBe(0)
    expect(outcome.filename).toBe('audit-export.csv')
  })

  it('403 ⇒ forbidden；超限 422 ⇒ 保留服务端原文（failed）', async () => {
    setServiceMode('http')
    const forbidden = (async () => ({
      status: 403,
      ok: false,
      headers: { get: () => null },
      text: async () => JSON.stringify({ detail: '只有超级管理员可以导出审计日志' }),
    })) as unknown as typeof fetch
    await expect(exportAudits({ actions: [] }, {}, forbidden)).rejects.toMatchObject({
      kind: 'forbidden',
      message: '只有超级管理员可以导出审计日志',
    })

    const overflow = (async () => ({
      status: 422,
      ok: false,
      headers: { get: () => null },
      text: async () =>
        JSON.stringify({ detail: '命中 5821 条，超过单次导出上限 5000 条；请缩小时间范围后重试' }),
    })) as unknown as typeof fetch
    await expect(exportAudits({ actions: [] }, {}, overflow)).rejects.toMatchObject({
      kind: 'failed',
      message: '命中 5821 条，超过单次导出上限 5000 条；请缩小时间范围后重试',
    })
  })

  it('样例模式：不发任何请求，也不假装成功', async () => {
    setServiceMode('mock')
    const fetchImpl = (async () => {
      throw new Error('样例模式不应发请求')
    }) as unknown as typeof fetch

    const outcome = await exportAudits({ actions: [] }, {}, fetchImpl)

    expect(outcome.downloaded).toBe(false)
    expect(outcome.blob).toBeNull()
    expect(outcome.note).toBe(MOCK_EXPORT_NOTE)
  })
})