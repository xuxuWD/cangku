import {
  SAMPLE_DATA_BADGE,
  SCHEDULE_ABSENT,
  TODO_LIMIT,
  WorkbenchServiceError,
  fetchQuickActions,
  fetchRecent,
  fetchSchedule,
  fetchTodos,
  mode,
  panelStateOfError,
  setServiceMode,
} from '../services/myWorkbenchService'

/** 递归收集所有字符串（含键名），用于"样例数据不含敏感信息"的自检。 */
function collectText(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(collectText)
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, nested]) => [key, ...collectText(nested)])
  }
  return []
}

/**
 * 最小 `fetch` 桩：只实现请求层用到的三样（`status` / `ok` / `text`），
 * 不引 MSW，也**不发真实网络请求**。返回它收到的 `(url, init)`，供"路径与参数逐字正确"的断言使用。
 */
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
  return { fetchImpl, calls }
}

const INBOX_ITEM = {
  inbox_id: 'inbox-0001',
  kind: 'task.approved',
  title: '任务已通过：整理客户反馈',
  target_type: 'task',
  target_id: 'task-0002',
  target_conversation_id: null,
  target_approval_id: null,
  created_at: '2026-09-18T17:05:00+08:00',
  read_at: null,
}

const APPROVAL_ITEM = {
  kind: 'task_approval',
  target_id: 'approval-0001',
  title: '待审批：整理本周选题',
  requested_by: null,
  created_at: '2026-09-19T09:20:00+08:00',
  detail: {},
}

describe('myWorkbenchService 适配层', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('默认 mock：样例数据带 sample 硬标记，页面据此显示标识', async () => {
    expect(mode).toBe('mock')
    expect(SAMPLE_DATA_BADGE).toBe('示例数据（未接后端）')

    const todos = await fetchTodos()
    const recent = await fetchRecent()
    expect(todos.sample).toBe(true)
    expect(recent.sample).toBe(true)
    expect(todos.items.length).toBeGreaterThan(0)
    expect(recent.items.length).toBeGreaterThan(0)
  })

  it('样例数据不含敏感信息（手机号 / 租户 / 用户 / 凭据字段）', async () => {
    const payloads = [
      await fetchTodos(),
      await fetchRecent(),
      { items: await fetchQuickActions() },
      await fetchSchedule(),
    ]
    const text = payloads.flatMap(collectText).join('\n')

    expect(text).not.toMatch(/1[3-9]\d{9}/) // 手机号
    expect(text).not.toMatch(/tenant_id|user_id|password|token|secret|api[_-]?key/i)
  })

  it('http 模式：待办走真接口 —— 未读通知 + 待审批，路径与参数逐字正确，合并按时间倒序', async () => {
    setServiceMode('http')
    const { fetchImpl, calls } = stubFetch({
      '/api/v1/inbox': { body: { items: [INBOX_ITEM], unread_count: 1 } },
      '/api/v1/approvals/pending': { body: { items: [APPROVAL_ITEM], counts: { task_approval: 1 } } },
    })

    const todos = await fetchTodos(fetchImpl)

    expect(calls.map((call) => call.url)).toEqual([
      `/api/v1/inbox?unread_only=true&limit=${TODO_LIMIT}`,
      `/api/v1/approvals/pending?limit=${TODO_LIMIT}`,
    ])
    // 真实数据**不得**被标成样例
    expect(todos.sample).toBe(false)
    // 合并后按 `created_at` 倒序：09-19 的审批在前，09-18 的通知在后
    expect(todos.items.map((item) => item.title)).toEqual([APPROVAL_ITEM.title, INBOX_ITEM.title])
    // 站内通知可"标记已读"（带 inbox_id）；审批类没有已读概念（inbox_id 为 null）
    expect(todos.items[0]).toMatchObject({ source: 'approval', kind: 'task_approval', inbox_id: null })
    expect(todos.items[1]).toMatchObject({
      source: 'notification',
      kind: 'notification_result',
      inbox_id: INBOX_ITEM.inbox_id,
    })
  })

  it('http 模式：未知审批 kind 落到 `other`，不误标成已知类型', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/inbox': { body: { items: [], unread_count: 0 } },
      '/api/v1/approvals/pending': { body: { items: [{ ...APPROVAL_ITEM, kind: 'brand_new_kind' }], counts: {} } },
    })

    const todos = await fetchTodos(fetchImpl)
    expect(todos.items[0].kind).toBe('other')
  })

  it('http 模式：任一取数失败即整体失败，不静默漏掉一半待办', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/inbox': { body: { items: [INBOX_ITEM], unread_count: 1 } },
      '/api/v1/approvals/pending': { status: 403, body: { detail: '无权限' } },
    })

    await expect(fetchTodos(fetchImpl)).rejects.toMatchObject({ status: 403, failure: 'forbidden' })
  })

  it('http 模式：最近使用**如实抛"尚未接入"**，不返回空数组假装"没有内容"', async () => {
    setServiceMode('http')

    await expect(fetchRecent()).rejects.toBeInstanceOf(WorkbenchServiceError)
    await expect(fetchRecent()).rejects.toMatchObject({ failure: 'not_connected' })
    await expect(fetchRecent()).rejects.toThrow(/尚未接入/)
  })

  it('http 模式：快捷入口是前端静态目录（与后端无关），因此仍然可用', async () => {
    setServiceMode('http')

    const actions = await fetchQuickActions()
    expect(actions.length).toBeGreaterThan(0)
    expect(actions.some((action) => action.kind === 'admin')).toBe(true)
  })

  it('日程：两种模式都返回"无实体"标记（不抛错、不返回空数组）', async () => {
    await expect(fetchSchedule()).resolves.toEqual(SCHEDULE_ABSENT)

    setServiceMode('http')
    const schedule = await fetchSchedule()
    expect(schedule.backend_entity).toBe('absent')
    expect(schedule.note).toMatch(/尚未接入/)
    expect(schedule.note).toMatch(/后端暂无日程实体/)
  })

  it('错误映射：forbidden → 界面 forbidden 态，其余一律 error 态', () => {
    expect(panelStateOfError(new WorkbenchServiceError('无权限', 'forbidden'))).toBe('forbidden')
    expect(panelStateOfError(new WorkbenchServiceError('未接线', 'not_connected'))).toBe('error')
    expect(panelStateOfError(new WorkbenchServiceError('失败', 'failed'))).toBe('error')
    expect(panelStateOfError(new Error('未知错误'))).toBe('error')
  })
})