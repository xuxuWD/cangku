/**
 * 「Skill & MCP」适配层用例（第 8 轮）。
 *
 * 覆盖口径（与 `docs/contracts/skills-mcp-api.md` 逐条对应）：
 *  - 读：列表路径与分页参数逐字正确；形状不符即抛错（不臆测、不静默补空）；
 *  - 写：提交请求体**只有**后端允许的九键（后端 `extra="forbid"`）；审核的 `approved` 走 **query**（必填）；
 *    启用 / 停用路径逐字正确；
 *  - 失败分类：`403` ⇒ `forbidden`、`404` ⇒ `not_found`、`409` ⇒ `conflict`（保留服务端原文）、
 *    `422`（`detail` 是数组）⇒ `invalid`（回落本地固定文案，**绝不渲染校验 JSON**）；
 *  - 状态机：未知状态**不误标**成已知状态；非法动作给原因（不是静默隐藏）；
 *    提交人自审被"提交人 = 自己"预置拦下（原因文案可见）；
 *  - 样例模式：**不伪造服务端回读值**（`skill === null`）、`written === false`、**不发任何请求**。
 */
import {
  MOCK_WRITE_NOTE,
  SkillError,
  disableSkill,
  enableSkill,
  fetchSkillContent,
  fetchSkills,
  panelStateOfError,
  reviewSkill,
  setServiceMode,
  submitSkill,
} from '../services/skillsService'
import {
  SKILL_STATUS_LABEL,
  actionDisabledReason,
  looksLikeSemver,
  looksLikeSha256,
  parseSkillStatus,
} from '../types'
import type { SubmitSkillInput } from '../types'

/** 最小 `fetch` 桩（与知识库用例同口径）：记录 `(url, init)`，供逐字断言使用。 */
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

const SKILL = (over: Partial<Record<string, unknown>> = {}) => ({
  skill_key: 'summarize',
  version: '1.0.0',
  name: '摘要助手',
  description: '生成结构化摘要',
  license: 'Apache-2.0',
  allowed_tools: ['fs.read'],
  status: 'submitted',
  source_key: 'manual',
  owner_id: 'acct-0001',
  reviewed_by: null,
  created_at: '2026-09-20T02:00:00Z',
  updated_at: '2026-09-20T02:00:00Z',
  ...over,
})

const SUBMIT_INPUT: SubmitSkillInput = {
  skill_key: 'summarize',
  version: '1.0.0',
  name: '摘要助手',
  description: '生成结构化摘要',
  license: 'Apache-2.0',
  allowed_tools: ['fs.read'],
  source_key: 'manual',
  content_sha256: 'a'.repeat(64),
  content_body: '# 摘要助手',
}

describe('skillsService（读路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('技能列表：路径与分页参数逐字正确，返回服务端形状', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills': { body: { items: [SKILL()], total: 1, limit: 200, offset: 0 } },
    })

    const page = await fetchSkills({ limit: 200, offset: 0 }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills?limit=200&offset=0')
    expect(page.sample).toBe(false)
    expect(page.total).toBe(1)
    expect(page.items[0].skill_key).toBe('summarize')
    expect(page.items[0].status).toBe('submitted')
  })

  it('技能列表：`status` 过滤进 query（不合法取值由服务端判定）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills': { body: { items: [], total: 0, limit: 200, offset: 0 } },
    })

    await fetchSkills({ status: 'submitted' }, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills?status=submitted&limit=200&offset=0')
  })

  it('技能列表：形状不符（items 不是数组）⇒ 抛错，绝不静默当成空列表', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({ '/api/v1/skills': { body: { total: 3 } } })

    await expect(fetchSkills({}, fetchImpl)).rejects.toBeInstanceOf(SkillError)
  })

  it('详情正文：路径逐字正确（`content` 端点），返回正文与指纹', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/summarize/versions/1.0.0/content': {
        body: { skill_key: 'summarize', version: '1.0.0', content_body: '# 正文', content_sha256: 'b'.repeat(64) },
      },
    })

    const outcome = await fetchSkillContent('summarize', '1.0.0', fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/summarize/versions/1.0.0/content')
    expect(outcome.sample).toBe(false)
    expect(outcome.content?.content_body).toBe('# 正文')
  })

  it('详情正文：标识含特殊字符时按路径段编码（不拼进 query、不裸拼）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/a%2Fb/versions/1.0.0/content': {
        body: { skill_key: 'a/b', version: '1.0.0', content_body: '# 正文', content_sha256: '' },
      },
    })

    await fetchSkillContent('a/b', '1.0.0', fetchImpl)

    expect(calls[0].url).toContain('/api/v1/skills/a%2Fb/versions/1.0.0/content')
  })
})

describe('skillsService（写路径）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('提交：请求体只有后端允许的九个键（`extra="forbid"`）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({ '/api/v1/skills': { status: 201, body: SKILL() } })

    const outcome = await submitSkill(SUBMIT_INPUT, fetchImpl)

    const body = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>
    expect(calls[0].init.method).toBe('POST')
    expect(Object.keys(body).sort()).toEqual([
      'allowed_tools',
      'content_body',
      'content_sha256',
      'description',
      'license',
      'name',
      'skill_key',
      'source_key',
      'version',
    ])
    expect(outcome.written).toBe(true)
    // 回读值取自服务端响应（不本地拼）
    expect(outcome.skill?.status).toBe('submitted')
  })

  it('审核：`approved` 走 query（后端必填 query 参数）', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/summarize/versions/1.0.0/review': { body: SKILL({ status: 'approved', reviewed_by: 'acct-9' }) },
    })

    const outcome = await reviewSkill('summarize', '1.0.0', true, fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/summarize/versions/1.0.0/review?approved=true')
    expect(outcome.skill?.status).toBe('approved')
    expect(outcome.skill?.reviewed_by).toBe('acct-9')
  })

  it('启用 / 停用：路径与方法逐字正确', async () => {
    setServiceMode('http')
    const { calls, fetchImpl } = stubFetch({
      '/api/v1/skills/summarize/versions/1.0.0/enable': { body: SKILL({ status: 'enabled' }) },
      '/api/v1/skills/summarize/versions/1.0.0/disable': { body: SKILL({ status: 'disabled' }) },
    })

    await enableSkill('summarize', '1.0.0', fetchImpl)
    await disableSkill('summarize', '1.0.0', fetchImpl)

    expect(calls[0].url).toBe('/api/v1/skills/summarize/versions/1.0.0/enable')
    expect(calls[0].init.method).toBe('POST')
    expect(calls[1].url).toBe('/api/v1/skills/summarize/versions/1.0.0/disable')
  })
})

describe('skillsService（失败分类）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('403（自审 / 越权）⇒ `forbidden`，且保留服务端原文', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills/summarize/versions/1.0.0/review': {
        status: 403,
        body: { detail: '不能审核自己提交的技能包' },
      },
    })

    const error = await reviewSkill('summarize', '1.0.0', true, fetchImpl).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(SkillError)
    expect((error as SkillError).kind).toBe('forbidden')
    expect((error as SkillError).message).toBe('不能审核自己提交的技能包')
    expect(panelStateOfError(error)).toBe('forbidden')
  })

  it('409（状态冲突）⇒ `conflict`，保留服务端原文', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills/summarize/versions/1.0.0/review': {
        status: 409,
        body: { detail: '仅 submitted 状态的技能包可审核' },
      },
    })

    const error = (await reviewSkill('summarize', '1.0.0', true, fetchImpl).catch(
      (caught: unknown) => caught,
    )) as SkillError

    expect(error.kind).toBe('conflict')
    expect(error.message).toBe('仅 submitted 状态的技能包可审核')
  })

  it('422（`detail` 是数组）⇒ `invalid`，回落本地固定文案（绝不渲染校验 JSON）', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills': {
        status: 422,
        body: { detail: [{ loc: ['body', 'version'], msg: 'version 必须是 major.minor.patch 语义版本号' }] },
      },
    })

    const error = (await submitSkill(SUBMIT_INPUT, fetchImpl).catch((caught: unknown) => caught)) as SkillError

    expect(error.kind).toBe('invalid')
    expect(error.message).not.toContain('loc')
    expect(error.message).toBe('请求参数不合法，已拒绝。')
  })

  it('404（他人未审包按不可见）⇒ `not_found`', async () => {
    setServiceMode('http')
    const { fetchImpl } = stubFetch({
      '/api/v1/skills/other/versions/1.0.0/content': { status: 404, body: { detail: 'other@1.0.0' } },
    })

    const error = (await fetchSkillContent('other', '1.0.0', fetchImpl).catch((caught: unknown) => caught)) as SkillError

    expect(error.kind).toBe('not_found')
  })
})

describe('skillsService（样例模式）', () => {
  afterEach(() => {
    setServiceMode('mock')
  })

  it('样例模式：不发任何请求，回读值为 null、written 为 false（不伪造已写入）', async () => {
    setServiceMode('mock')
    const fetchImpl = (async () => {
      throw new Error('样例模式不应发请求')
    }) as unknown as typeof fetch

    const page = await fetchSkills({}, fetchImpl)
    const outcome = await submitSkill(SUBMIT_INPUT, fetchImpl)

    expect(page.sample).toBe(true)
    expect(page.items.length).toBeGreaterThan(0)
    expect(outcome.written).toBe(false)
    expect(outcome.skill).toBeNull()
    expect(outcome.note).toBe(MOCK_WRITE_NOTE)
  })
})

describe('技能状态机与状态保真（纯函数）', () => {
  it('未知状态落 `unknown`，绝不误标成已知状态', () => {
    expect(parseSkillStatus('approved_2')).toBe('unknown')
    expect(parseSkillStatus('enabled')).toBe('enabled')
    expect(SKILL_STATUS_LABEL.enabled).toBe('已启用')
  })

  it('复核仅 `submitted` 可执行；`rejected` 是终态（三动作全部给原因）', () => {
    expect(actionDisabledReason('review_approve', 'submitted')).toBeNull()
    expect(actionDisabledReason('review_reject', 'submitted')).toBeNull()
    expect(actionDisabledReason('review_approve', 'approved')).not.toBeNull()
    expect(actionDisabledReason('enable', 'submitted')).not.toBeNull()

    for (const action of ['review_approve', 'review_reject', 'enable', 'disable'] as const) {
      expect(actionDisabledReason(action, 'rejected')).toContain('终态')
      expect(actionDisabledReason(action, 'unknown')).not.toBeNull()
    }
  })

  it('启用 `approved` / `disabled` 可点；启用中与已停用允许幂等点击', () => {
    expect(actionDisabledReason('enable', 'approved')).toBeNull()
    expect(actionDisabledReason('enable', 'disabled')).toBeNull()
    expect(actionDisabledReason('enable', 'enabled')).toBeNull()
    expect(actionDisabledReason('disable', 'enabled')).toBeNull()
    expect(actionDisabledReason('disable', 'disabled')).toBeNull()
    expect(actionDisabledReason('disable', 'approved')).not.toBeNull()
  })

  it('易用性校验只做形状检查（最终判定在服务端）', () => {
    expect(looksLikeSemver('1.0.0')).toBe(true)
    expect(looksLikeSemver('1')).toBe(false)
    expect(looksLikeSha256('a'.repeat(64))).toBe(true)
    expect(looksLikeSha256('a'.repeat(63))).toBe(false)
  })
})