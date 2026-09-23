/**
 * 「通知（收件箱）」适配层用例（阶段 1 合并移植）。
 *
 * 覆盖口径（与 `docs/api-contract.md`「站内通知（收件箱）」逐条对应）：
 *  - 读：`GET /api/v1/inbox`，查询参数逐字正确（`unread_only` / `limit`）；
 *  - 写：`POST /api/v1/inbox/{inbox_id}/read`（id 必须 `encodeURIComponent`）、
 *        `POST /api/v1/inbox/read-all`；
 *  - 形状不符**即抛错**（不臆测、不静默补空 —— 静默空会伪装成"真的没有通知"）；
 *  - `403` ⇒ `forbidden`（界面走"无权限"态，与"加载失败"分开）；`5xx` ⇒ `failed`；
 *  - 样例模式：**不发任何请求**，`sample: true`。
 */
import { ServiceError } from '../../../utils/serviceKit'
import {
  INBOX_LIMIT,
  fetchInbox,
  isConnected,
  markAllInboxRead,
  markInboxRead,
  resetMockInbox,
  setServiceMode,
} from '../services/inboxService'

/** 最小 `fetch` 桩（与基座其它模块同口径）：记录 `(url, init)` 供逐字断言。 */
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

const ITEM = (over: Partial<Record<string, unknown>> = {}) => ({
  inbox_id: 'inbox-1',
  kind: 'task.approved',
  title: '任务已通过审批',
  target_type: 'task',
  target_id: 'task-1',
  target_conversation_id: null,
  target_approval_id: null,
  created_at: '2026-09-23T02:10:00Z',
  read_at: null,
  ...over,
})

const LIST = { items: [ITEM()], unread_count: 1 }

describe('通知适配层', () => {
  beforeEach(() => {
    resetMockInbox()
  })

  afterEach(() => {
    setServiceMode('mock')
    resetMockInbox()
  })

  describe('样例模式', () => {
    it('不发任何请求，且 sample 为 true', async () => {
      const { calls, fetchImpl } = stubFetch({ '/api/v1/inbox': { body: LIST } })
      setServiceMode('mock')

      const result = await fetchInbox(false, INBOX_LIMIT, fetchImpl)

      expect(calls).toHaveLength(0)
      expect(result.sample).toBe(true)
    })

    it('未读数取自样例数据本身（不写死）', async () => {
      setServiceMode('mock')
      const result = await fetchInbox()
      expect(result.unread_count).toBe(result.items.filter((item) => item.read_at === null).length)
    })

    it('样例状态是**有状态**的：标已读后重新取数，未读数真的减少', async () => {
      // 回归：样例数据若无状态，写成功后重新取数会复原 ⇒ 开发期看着像"点了没用"
      // （2026-09-23 真机走查实测到，故补此用例锁住）
      setServiceMode('mock')
      const before = await fetchInbox()
      expect(before.unread_count).toBeGreaterThan(0)

      const target = before.items.find((item) => item.read_at === null)!
      await markInboxRead(target.inbox_id)

      const after = await fetchInbox()
      expect(after.unread_count).toBe(before.unread_count - 1)
      expect(after.items.find((item) => item.inbox_id === target.inbox_id)?.read_at).not.toBeNull()
    })

    it('样例状态下「全部标记已读」把未读清零', async () => {
      setServiceMode('mock')
      await markAllInboxRead()
      const after = await fetchInbox()
      expect(after.unread_count).toBe(0)
      expect(after.items.every((item) => item.read_at !== null)).toBe(true)
    })

    it('isConnected 随模式切换', () => {
      setServiceMode('mock')
      expect(isConnected()).toBe(false)
      setServiceMode('http')
      expect(isConnected()).toBe(true)
    })
  })

  describe('读路径', () => {
    it('默认参数：unread_only=false 且 limit 为单页上限', async () => {
      const { calls, fetchImpl } = stubFetch({ '/api/v1/inbox': { body: LIST } })
      setServiceMode('http')

      const result = await fetchInbox(false, INBOX_LIMIT, fetchImpl)

      expect(calls).toHaveLength(1)
      expect(calls[0].url).toBe(`/api/v1/inbox?unread_only=false&limit=${INBOX_LIMIT}`)
      expect(calls[0].init.method).toBe('GET')
      expect(result.sample).toBe(false)
      expect(result.unread_count).toBe(1)
    })

    it('unreadOnly=true 时按服务端参数传，而不是前端过滤', async () => {
      const { calls, fetchImpl } = stubFetch({ '/api/v1/inbox': { body: { items: [], unread_count: 0 } } })
      setServiceMode('http')

      await fetchInbox(true, 10, fetchImpl)

      expect(calls[0].url).toBe('/api/v1/inbox?unread_only=true&limit=10')
    })

    it('形状不符（items 非数组）⇒ 抛错，**不得**降级成空列表', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/inbox': { body: { unread_count: 1 } } })
      setServiceMode('http')

      await expect(fetchInbox(false, INBOX_LIMIT, fetchImpl)).rejects.toThrow()
    })

    it('403 ⇒ forbidden（与"加载失败"分开）', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/inbox': { status: 403, body: { detail: '无权限' } } })
      setServiceMode('http')

      const error = await fetchInbox(false, INBOX_LIMIT, fetchImpl).catch((e: unknown) => e)
      expect(error).toBeInstanceOf(ServiceError)
      expect((error as ServiceError).failure).toBe('forbidden')
    })

    it('503 ⇒ failed', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/inbox': { status: 503 } })
      setServiceMode('http')

      const error = await fetchInbox(false, INBOX_LIMIT, fetchImpl).catch((e: unknown) => e)
      expect((error as ServiceError).failure).toBe('failed')
    })
  })

  describe('写路径', () => {
    it('单条标已读：POST 到 /read，且 inbox_id 走 encodeURIComponent', async () => {
      const { calls, fetchImpl } = stubFetch({
        '/api/v1/inbox/': { body: ITEM({ read_at: '2026-09-23T03:00:00Z' }) },
      })
      setServiceMode('http')

      const updated = await markInboxRead('inbox-1/2', fetchImpl)

      expect(calls[0].url).toBe('/api/v1/inbox/inbox-1%2F2/read')
      expect(calls[0].init.method).toBe('POST')
      expect(updated.read_at).toBe('2026-09-23T03:00:00Z')
    })

    it('单条标已读：形状不符 ⇒ 抛错', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/inbox/': { body: { ok: true } } })
      setServiceMode('http')

      await expect(markInboxRead('inbox-1', fetchImpl)).rejects.toThrow()
    })

    it('全部标已读：POST 到 /read-all，返回 updated', async () => {
      const { calls, fetchImpl } = stubFetch({ '/api/v1/inbox/read-all': { body: { updated: 3 } } })
      setServiceMode('http')

      const result = await markAllInboxRead(fetchImpl)

      expect(calls[0].url).toBe('/api/v1/inbox/read-all')
      expect(calls[0].init.method).toBe('POST')
      expect(result.updated).toBe(3)
    })

    it('全部标已读：缺少 updated 数字 ⇒ 抛错（不把缺失读成 0）', async () => {
      const { fetchImpl } = stubFetch({ '/api/v1/inbox/read-all': { body: {} } })
      setServiceMode('http')

      await expect(markAllInboxRead(fetchImpl)).rejects.toThrow()
    })
  })
})
