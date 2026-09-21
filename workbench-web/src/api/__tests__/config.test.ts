/**
 * 查询参数拼装用例（`buildUrl`）—— 第 10 轮补：**数组值 ⇒ 重复键**。
 *
 * 为什么单列：审计接口的 `action` 是「可重复 query」（`?action=a&action=b`），
 * 逗号拼接**不被 FastAPI 识别**（会当成一个未知动作码 ⇒ 422）；
 * 而 `buildUrl` 是**全前端唯一的 URL 拼装点**，行为必须被钉住。
 */
import { buildUrl } from '../config'

describe('buildUrl', () => {
  it('标量：逐键编码；`undefined` / `null` / 空串不拼进 URL', () => {
    expect(buildUrl('/api/v1/audits', { limit: 50, offset: 0 })).toBe('/api/v1/audits?limit=50&offset=0')
    expect(buildUrl('/api/v1/audits', { a: undefined, b: null, c: '' })).toBe('/api/v1/audits')
    expect(buildUrl('/api/v1/audits')).toBe('/api/v1/audits')
  })

  it('数组：展开为重复键（审计 `action` 多选的唯一正确形态）', () => {
    expect(buildUrl('/api/v1/audits', { action: ['a.b', 'c.d'], limit: 50 })).toBe(
      '/api/v1/audits?action=a.b&action=c.d&limit=50',
    )
  })

  it('数组：空项与空数组不拼（不产生 `action=` 这种空值参数）', () => {
    expect(buildUrl('/api/v1/audits', { action: [] })).toBe('/api/v1/audits')
    expect(buildUrl('/api/v1/audits', { action: ['', 'a.b'] })).toBe('/api/v1/audits?action=a.b')
  })

  it('键与值都过 encodeURIComponent（含 `@` / `:` / `+`）', () => {
    expect(buildUrl('/api/v1/audits', { target_id: 'summarize@1.0.0' })).toBe(
      '/api/v1/audits?target_id=summarize%401.0.0',
    )
    expect(buildUrl('/api/v1/audits', { since: '2026-09-20T00:00:00.000Z' })).toBe(
      '/api/v1/audits?since=2026-09-20T00%3A00%3A00.000Z',
    )
  })
})