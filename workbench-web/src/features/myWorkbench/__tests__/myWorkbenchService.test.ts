import {
  SAMPLE_DATA_BADGE,
  SCHEDULE_ABSENT,
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

  it('http 模式：三块取数**抛"尚未接入"**，不静默返回空数组', async () => {
    setServiceMode('http')

    for (const load of [fetchTodos, fetchRecent, fetchQuickActions]) {
      await expect(load()).rejects.toBeInstanceOf(WorkbenchServiceError)
      await expect(load()).rejects.toMatchObject({ failure: 'not_connected' })
      await expect(load()).rejects.toThrow(/尚未接入/)
    }
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