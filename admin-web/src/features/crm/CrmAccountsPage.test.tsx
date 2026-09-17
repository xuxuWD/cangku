import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CrmAccountsPage } from './CrmAccountsPage'
import type { CrmAccount, CrmActivity, CrmContact, CrmInsight, CrmOpportunity } from './types'

const computedAccount: CrmAccount = {
  account_id: 'acc-1', name: '云启科技', industry: '软件', source: 'manual', status: 'active', owner_id: 'admin',
  custom_fields: { region: '华东' }, health_score: 82, health_band: 'green', health_computed_at: '2026-09-17T00:00:00Z',
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-16T00:00:00Z',
}
// 健康度未计算：score / band 均为 null，界面必须显示「未计算」而不是 0。
const uncomputedAccount: CrmAccount = {
  ...computedAccount, account_id: 'acc-2', name: '恒远物流', health_score: null, health_band: null, health_computed_at: null,
}
const contact: CrmContact = {
  contact_id: 'ct-1', account_id: 'acc-1', name: '李经理', title: '采购总监', phone: '138****1234', email: 'l***@example.com',
  is_primary: true, birthday: null, owner_id: 'admin', custom_fields: {}, created_at: '2026-09-02T00:00:00Z',
}
const activity: CrmActivity = {
  activity_id: 'act-1', kind: 'call', subject: '初次沟通', account_id: 'acc-1', contact_id: null, opportunity_id: null,
  owner_id: 'admin', status: 'done', due_at: null, occurred_at: '2026-09-16T02:00:00Z', created_by_kind: 'human',
}
const activeOpportunity: CrmOpportunity = {
  opportunity_id: 'opp-1', account_id: 'acc-1', name: '云启一期', stage: 'negotiation', amount_cents: 1250000,
  expected_close: '2026-10-31', owner_id: 'admin', stage_entered_at: '2026-09-10T00:00:00Z', closed_at: null,
  custom_fields: {}, created_at: '2026-09-03T00:00:00Z',
}
const wonOpportunity: CrmOpportunity = { ...activeOpportunity, opportunity_id: 'opp-2', name: '云启已赢单', stage: 'won', closed_at: '2026-09-15T00:00:00Z' }

const insufficientInsight: CrmInsight = {
  insight_id: 'ins-1', account_id: 'acc-1', kind: 'followup_plan',
  content: { actions: [], summary: '依据不足，无法给出建议', insufficient_evidence: true },
  evidence_refs: [], dropped_refs: [{ reason: 'invalid_evidence_ref', raw: 'activity:other-tenant' }],
  model_key: 'mock-default', generated_by: 'admin', created_at: '2026-09-17T03:00:00Z',
}
const actionableInsight: CrmInsight = {
  insight_id: 'ins-2', account_id: 'acc-1', kind: 'followup_plan',
  content: {
    actions: [{ action_type: 'call', target_ref: 'contact:ct-1', reason: '距上次互动已 45 天', evidence_refs: ['activity:act-1'], confidence: 0.72 }],
    summary: '建议本周电话跟进',
  },
  evidence_refs: ['activity:act-1'], dropped_refs: [{ reason: 'invalid_target_ref', raw: 'opportunity:ghost' }],
  model_key: 'mock-default', generated_by: 'admin', created_at: '2026-09-17T03:10:00Z',
}

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function makeFetch(handler: (url: string, init?: RequestInit) => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init))
}

function detailFetch(insights: CrmInsight[]) {
  return makeFetch((url) => {
    if (url.includes('/crm/accounts?')) return json({ items: [computedAccount], total: 1, limit: 50, offset: 0 })
    if (url.includes('/crm/accounts/acc-1/contacts')) return json({ items: [contact], total: 1, limit: 50, offset: 0 })
    if (url.includes('/crm/accounts/acc-1/insights')) return json({ items: insights, total: insights.length, limit: 20, offset: 0 })
    if (url.includes('/crm/accounts/acc-1/followup-plan')) return json(insufficientInsight)
    if (url.includes('/crm/accounts/acc-1')) return json(computedAccount)
    if (url.includes('/crm/activities?')) return json({ items: [activity], total: 1, limit: 20, offset: 0 })
    if (url.includes('/crm/opportunities?')) return json({ items: [activeOpportunity, wonOpportunity], total: 2, limit: 200, offset: 0 })
    if (url.includes('/crm/contacts/ct-1/reveal')) return json({ contact_id: 'ct-1', field: 'phone', value: '13800001234' })
    return json({})
  })
}

describe('CrmAccountsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders accounts, showing 未计算 for null health instead of 0', async () => {
    vi.stubGlobal('fetch', makeFetch((url) => url.includes('/crm/accounts?')
      ? json({ items: [computedAccount, uncomputedAccount], total: 2, limit: 50, offset: 0 })
      : json({})))

    render(<CrmAccountsPage />)

    expect(await screen.findByText('云启科技')).toBeInTheDocument()
    expect(screen.getByText('健康 82')).toBeInTheDocument()
    expect(screen.getByText('未计算')).toBeInTheDocument()
    expect(screen.getByText(/共 2 条（第 1–2 条）/)).toBeInTheDocument()
  })

  it('shows the empty state when there are no accounts', async () => {
    vi.stubGlobal('fetch', makeFetch(() => json({ items: [], total: 0, limit: 50, offset: 0 })))

    render(<CrmAccountsPage />)

    expect(await screen.findByText('暂无客户')).toBeInTheDocument()
  })

  it('shows a failure notice and retries the same query', async () => {
    let attempts = 0
    vi.stubGlobal('fetch', makeFetch(() => {
      attempts += 1
      if (attempts === 1) return json({}, 500)
      return json({ items: [computedAccount], total: 1, limit: 50, offset: 0 })
    }))

    render(<CrmAccountsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('客户列表加载失败')
    expect(screen.getByText('CRM 服务暂时不可用，请检查网络后重新尝试。')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '重新尝试' }))

    expect(await screen.findByText('云启科技')).toBeInTheDocument()
  })

  it('opens the detail view with masked contacts, active opportunities only, timeline and 依据不足 plan', async () => {
    vi.stubGlobal('fetch', detailFetch([]))

    render(<CrmAccountsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    // 掩码值默认展示，明文仅在点击后出现。
    expect(await screen.findByText('138****1234')).toBeInTheDocument()
    expect(screen.getByText('l***@example.com')).toBeInTheDocument()
    expect(screen.queryByText('13800001234')).not.toBeInTheDocument()

    // 终态商机不进「进行中商机」。
    expect(screen.getByText('云启一期')).toBeInTheDocument()
    expect(screen.queryByText('云启已赢单')).not.toBeInTheDocument()
    expect(screen.getByText(/电话 · 初次沟通/)).toBeInTheDocument()
    expect(screen.getByText(/region: 华东/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '查看电话明文' }))
    expect(await screen.findByText('13800001234')).toBeInTheDocument()
    expect(screen.getByText('已揭示（不缓存）')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '生成跟进计划' }))
    // 依据不足时展示服务端固定文案（不伪造建议）。
    expect((await screen.findAllByText('依据不足，无法给出建议')).length).toBeGreaterThan(0)
    expect(screen.getByText(/证据引用无效或不属于本客户：activity:other-tenant/)).toBeInTheDocument()
  })

  it('renders actions with confidence and dropped references', async () => {
    vi.stubGlobal('fetch', detailFetch([actionableInsight]))

    render(<CrmAccountsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    expect(await screen.findByText('电话跟进')).toBeInTheDocument()
    expect(screen.getByText('距上次互动已 45 天')).toBeInTheDocument()
    expect(screen.getByText(/置信度：72%（模型自评，未经校准）/)).toBeInTheDocument()
    expect(screen.getByText('activity:act-1')).toBeInTheDocument()
    expect(screen.getByText(/模型引用了无效依据（1 条，已丢弃）/)).toBeInTheDocument()
    expect(screen.getByText(/目标引用无效或不属于本客户：opportunity:ghost/)).toBeInTheDocument()
  })

  it('surfaces the server 403 on reveal instead of hiding the button', async () => {
    vi.stubGlobal('fetch', makeFetch((url) => {
      if (url.includes('/crm/accounts?')) return json({ items: [computedAccount], total: 1, limit: 50, offset: 0 })
      if (url.includes('/crm/accounts/acc-1/contacts')) return json({ items: [contact], total: 1, limit: 50, offset: 0 })
      if (url.includes('/crm/accounts/acc-1/insights')) return json({ items: [], total: 0, limit: 20, offset: 0 })
      if (url.includes('/crm/accounts/acc-1')) return json(computedAccount)
      if (url.includes('/crm/activities?')) return json({ items: [], total: 0, limit: 20, offset: 0 })
      if (url.includes('/crm/opportunities?')) return json({ items: [], total: 0, limit: 200, offset: 0 })
      if (url.includes('/crm/contacts/ct-1/reveal')) return json({ detail: '数据范围外' }, 403)
      return json({})
    }))

    render(<CrmAccountsPage />)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))

    // 按钮始终可见（隐藏按钮不构成权限），越权由服务端返回并如实展示。
    await userEvent.click(await screen.findByRole('button', { name: '查看邮箱明文' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('敏感字段揭示未完成')
    expect(screen.getByText('查看明文失败：当前账号没有执行该操作的权限。')).toBeInTheDocument()
  })
})