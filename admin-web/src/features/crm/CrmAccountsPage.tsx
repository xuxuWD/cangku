import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { formatLocalTime } from '../../utils/time'
import { generateFollowupPlan, getAccount, listAccounts, listActivities, listContacts, listInsights, listOpportunities, revealContact } from './api'
import { CrmNotice, Pagination } from './CrmShared'
import { asCrmError, CRM_LIMIT_OPTIONS, formatCents, scalarEntries } from './state'
import {
  ACTIVITY_KIND_LABELS,
  ACTIVITY_STATUS_LABELS,
  ACTIVE_OPPORTUNITY_STAGES,
  crmLabel,
  DROPPED_REF_LABELS,
  FOLLOWUP_ACTION_LABELS,
  HEALTH_BAND_LABELS,
  ACCOUNT_STATUS_LABELS,
  OPPORTUNITY_STAGE_LABELS,
  type CrmAccount,
  type CrmActivity,
  type CrmContact,
  type CrmErrorShape,
  type CrmInsight,
  type CrmOpportunity,
  type CrmPage,
  type CrmRevealField,
} from './types'

export function CrmAccountsPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  const [selectedId, setSelectedId] = useState<string | null>(null)
  if (selectedId) return <AccountDetail accountId={selectedId} onBack={() => setSelectedId(null)} />
  return <AccountList onOpen={setSelectedId} />
}

// ---------------------------------------------------------------- 列表

interface AccountPageState extends CrmPage<CrmAccount> {
  loading: boolean
  error: CrmErrorShape | null
}

function AccountList({ onOpen }: { onOpen: (accountId: string) => void }) {
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState<AccountPageState>({ items: [], total: 0, limit: 50, offset: 0, loading: true, error: null })

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await listAccounts({ status, limit, offset })
      setState({
        items: Array.isArray(data.items) ? data.items : [],
        total: typeof data.total === 'number' ? data.total : 0,
        limit: typeof data.limit === 'number' ? data.limit : limit,
        offset: typeof data.offset === 'number' ? data.offset : offset,
        loading: false,
        error: null,
      })
    } catch (error) {
      setState({ items: [], total: 0, limit, offset, loading: false, error: asCrmError(error) })
    }
  }, [status, limit, offset])

  useEffect(() => { void load() }, [load])

  // 关键字检索在**当前页内**过滤：列表接口按契约只接受 status / owner_id / limit / offset，不编造查询参数。
  const visible = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    if (!text) return state.items
    return state.items.filter((account) => account.name.toLowerCase().includes(text) || account.industry.toLowerCase().includes(text))
  }, [state.items, keyword])

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">客户</h1>
        <p className="page-desc">客户主数据列表：健康度未计算时显示「未计算」（不是 0 分）；联系人电话 / 邮箱在列表与详情中一律掩码。</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
    </div>

    <div className="toolbar">
      <label className="history-filter">状态
        <select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>
          <option value="">全部</option>
          <option value="active">活跃</option>
          <option value="inactive">停用</option>
        </select>
      </label>
      <label className="history-filter">关键字
        <input type="text" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="按名称 / 行业筛选当前页" />
      </label>
      <label className="history-filter">每页条数
        <select value={String(limit)} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0) }}>
          {CRM_LIMIT_OPTIONS.map((size) => <option value={size} key={size}>{size} 条</option>)}
        </select>
      </label>
      <span className="history-count">当前页 {visible.length} 条 / 共 {state.total} 条</span>
    </div>

    {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载客户列表…</div>}
    {!state.loading && state.error && <CrmNotice
      tone="error"
      title="客户列表加载失败"
      action={state.error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{state.error.message}</p>
    </CrmNotice>}
    {!state.loading && !state.error && <section className="history-panel crm__panel" aria-label="客户列表">
      <div className="panel-header"><h2>客户列表</h2><span>{state.total} 条</span></div>
      {state.items.length === 0
        ? <div className="empty-state"><strong>暂无客户</strong><span>调整筛选条件，或先从线索转化 / 接口建客户。</span></div>
        : visible.length === 0
          ? <div className="empty-state"><strong>当前页没有匹配的客户</strong><span>关键字只过滤当前页；可翻页或清空关键字。</span></div>
          : <div className="panel-body"><table className="workforce__table">
            <thead><tr><th>名称</th><th>行业</th><th>状态</th><th>健康度</th><th>负责人</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>{visible.map((account) => <tr key={account.account_id}>
              <td><span className="workforce__key">{account.name}</span></td>
              <td>{account.industry || '—'}</td>
              <td><span className={`status-badge ${account.status === 'active' ? 'status-active' : 'status-disabled'}`}>{crmLabel(ACCOUNT_STATUS_LABELS, account.status)}</span></td>
              <td><HealthBadge score={account.health_score} band={account.health_band} /></td>
              <td>{account.owner_id}</td>
              <td>{formatLocalTime(account.updated_at) || '—'}</td>
              <td><button className="text-action" type="button" onClick={() => onOpen(account.account_id)}>查看详情</button></td>
            </tr>)}</tbody>
          </table></div>}
      <Pagination total={state.total} limit={state.limit} offset={state.offset} loading={state.loading} onPrev={() => setOffset(Math.max(0, state.offset - state.limit))} onNext={() => setOffset(state.offset + state.limit)} />
    </section>}
  </main>
}

function HealthBadge({ score, band }: { score: number | null; band: string | null }) {
  if (score === null || band === null) return <span className="status-badge status-disabled" title="健康度尚未计算，不等于 0 分">未计算</span>
  const tone = band === 'green' ? 'status-confirmed' : band === 'yellow' ? 'status-pending' : 'status-failed'
  return <span className={`status-badge ${tone}`}>{crmLabel(HEALTH_BAND_LABELS, band)} {score}</span>
}

// ---------------------------------------------------------------- 详情

function AccountDetail({ accountId, onBack }: { accountId: string; onBack: () => void }) {
  const [account, setAccount] = useState<CrmAccount | null>(null)
  const [contacts, setContacts] = useState<CrmContact[]>([])
  const [activities, setActivities] = useState<CrmActivity[]>([])
  const [opportunities, setOpportunities] = useState<CrmOpportunity[]>([])
  const [insights, setInsights] = useState<CrmInsight[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<CrmErrorShape | null>(null)
  const [planBusy, setPlanBusy] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [revealed, setRevealed] = useState<Record<string, string>>({})
  const [revealError, setRevealError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [accountData, contactPage, activityPage, opportunityPage, insightPage] = await Promise.all([
        getAccount(accountId),
        listContacts(accountId, 50, 0),
        listActivities({ accountId, limit: 20, offset: 0 }),
        listOpportunities({ accountId, limit: 200, offset: 0, stage: '' }),
        listInsights(accountId, 20, 0),
      ])
      setAccount(accountData)
      setContacts(Array.isArray(contactPage.items) ? contactPage.items : [])
      setActivities(Array.isArray(activityPage.items) ? activityPage.items : [])
      setOpportunities(Array.isArray(opportunityPage.items) ? opportunityPage.items : [])
      setInsights(Array.isArray(insightPage.items) ? insightPage.items : [])
    } catch (err) {
      setError(asCrmError(err))
    } finally {
      setLoading(false)
    }
  }, [accountId])

  useEffect(() => { void load() }, [load])

  const generatePlan = async () => {
    setPlanBusy(true)
    setPlanError(null)
    setToast(null)
    try {
      const insight = await generateFollowupPlan(accountId)
      setInsights((old) => [insight, ...old])
      setToast('跟进计划已生成；历史生成记录为追加式，不覆盖旧记录。')
    } catch (err) {
      // 网关失败 ⇒ 服务端 502（不降级、不落库）：如实展示错误，不伪造建议。
      setPlanError(asCrmError(err).message)
    } finally {
      setPlanBusy(false)
    }
  }

  const reveal = async (contactId: string, field: CrmRevealField) => {
    setRevealError(null)
    try {
      const result = await revealContact(contactId, field)
      setRevealed((old) => ({ ...old, [`${contactId}:${field}`]: result.value }))
    } catch (err) {
      // 服务端独立判定（403 / 404）：如实展示，不因按钮可见就假定有权。
      setRevealError(`查看明文失败：${asCrmError(err).message}`)
    }
  }

  if (loading) return <main className="main-content content-history crm"><div className="loading-state" role="status"><span className="loading-dot" />正在加载客户详情…</div></main>
  if (error || !account) return <main className="main-content content-history crm">
    <div className="page-head"><div><h1 className="page-title">客户详情</h1></div><div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div></div>
    <CrmNotice
      tone="error"
      title="客户详情加载失败"
      action={error?.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{error?.message ?? '没有找到该客户。'}</p>
    </CrmNotice>
  </main>

  const activeOpportunities = opportunities.filter((item) => ACTIVE_OPPORTUNITY_STAGES.includes(item.stage))
  const fields = scalarEntries(account.custom_fields)
  const latestPlan = insights[0]

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">{account.name}</h1>
        <p className="page-desc">客户详情：健康度、进行中商机、活动时间线、跟进计划（人工触发）与历史生成记录。</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div>
    </div>

    {revealError && <CrmNotice tone="error" title="敏感字段揭示未完成"><p>{revealError}</p></CrmNotice>}

    <section className="history-panel crm__panel" aria-label="客户信息">
      <div className="panel-header"><h2>基本信息</h2><span>{account.account_id}</span></div>
      <div className="panel-body">
        <div className="run-detail__grid">
          <div className="run-detail__item"><span className="run-detail__label">行业</span><span className="run-detail__value">{account.industry || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">来源</span><span className="run-detail__value">{account.source}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">状态</span><span className="run-detail__value">{crmLabel(ACCOUNT_STATUS_LABELS, account.status)}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">负责人</span><span className="run-detail__value">{account.owner_id}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">创建时间</span><span className="run-detail__value">{formatLocalTime(account.created_at) || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">健康度</span><span className="run-detail__value"><HealthBadge score={account.health_score} band={account.health_band} /></span></div>
        </div>
        {fields.length > 0 && <p className="crm__chips">{fields.map((entry) => <span className="workforce__chip" key={entry.key}>{`${entry.key}: ${entry.text}`}</span>)}</p>}
      </div>
    </section>

    <section className="history-panel crm__panel" aria-label="健康度">
      <div className="panel-header"><h2>健康度</h2><span>四维规则分（参考值，不作客户价值排名）</span></div>
      <div className="panel-body"><div className="stat-grid">
        <div className="stat-tile"><span className="stat-label">健康分</span><b className="stat-value">{account.health_score === null ? '未计算' : account.health_score}</b><p className="stat-hint">未计算 = 尚未跑过重算任务，不是 0 分。</p></div>
        <div className="stat-tile"><span className="stat-label">分档</span><b className="stat-value">{account.health_band === null ? '未计算' : crmLabel(HEALTH_BAND_LABELS, account.health_band)}</b><p className="stat-hint">green ≥ 80 / yellow 60–79 / red &lt; 60。</p></div>
        <div className="stat-tile"><span className="stat-label">计算时间</span><b className="stat-value">{formatLocalTime(account.health_computed_at) || '未计算'}</b><p className="stat-hint">由周期任务 crm-health-recompute 重算。</p></div>
      </div></div>
    </section>

    <section className="history-panel crm__panel" aria-label="进行中商机">
      <div className="panel-header"><h2>进行中商机</h2><span>{activeOpportunities.length} 条</span></div>
      {activeOpportunities.length === 0
        ? <div className="empty-state"><strong>没有进行中的商机</strong><span>终态（赢单 / 输单）商机不计入。</span></div>
        : <div className="panel-body"><table className="workforce__table">
          <thead><tr><th>名称</th><th>阶段</th><th>金额</th><th>预计成交</th><th>进入阶段时间</th></tr></thead>
          <tbody>{activeOpportunities.map((item) => <tr key={item.opportunity_id}>
            <td><span className="workforce__key">{item.name}</span></td>
            <td><span className="status-badge status-reviewing">{crmLabel(OPPORTUNITY_STAGE_LABELS, item.stage)}</span></td>
            <td>{formatCents(item.amount_cents)}</td>
            <td>{item.expected_close || '—'}</td>
            <td>{formatLocalTime(item.stage_entered_at) || '—'}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>

    <section className="history-panel crm__panel" aria-label="跟进计划">
      <div className="panel-header"><h2>跟进计划</h2><span>人工触发 · 建议永不自动执行</span></div>
      <div className="panel-body">
        <div className="actions crm__actions">
          <button className="button primary" type="button" disabled={planBusy} onClick={() => void generatePlan()}>{planBusy ? '正在生成…' : '生成跟进计划'}</button>
          <span className="role-note">服务端逐条校验证据引用真实性；无效引用会被丢弃并标注。</span>
        </div>
        {planError && <CrmNotice tone="error" title="跟进计划生成失败"><p>{planError}</p></CrmNotice>}
        {!planError && !latestPlan && <div className="empty-state"><strong>还没有生成记录</strong><span>点击「生成跟进计划」后，结果与证据引用会展示在这里。</span></div>}
        {!planError && latestPlan && <InsightBody insight={latestPlan} />}
      </div>
    </section>

    <section className="history-panel crm__panel" aria-label="历史生成记录">
      <div className="panel-header"><h2>历史生成记录</h2><span>{insights.length} 条（追加式）</span></div>
      {insights.length === 0
        ? <div className="empty-state"><strong>暂无生成记录</strong><span>每次生成都会追加一条，不覆盖旧记录。</span></div>
        : <div className="history-list" role="list">{insights.map((insight) => <article className="history-row crm-insight" role="listitem" key={insight.insight_id}>
          <div className="history-row-main">
            <strong>{insight.content.insufficient_evidence ? '依据不足，无法给出建议' : insight.content.summary || '（无摘要）'}</strong>
            <div className="history-meta">
              <span>{formatLocalTime(insight.created_at) || '—'}</span>
              <span>模型：{insight.model_key}</span>
              <span>触发者：{insight.generated_by}</span>
              <span>建议 {insight.content.actions?.length ?? 0} 条</span>
              <span>有效证据 {insight.evidence_refs?.length ?? 0} 条</span>
              {insight.dropped_refs?.length > 0 && <span className="crm-insight__drop">丢弃引用 {insight.dropped_refs.length} 条</span>}
            </div>
          </div>
        </article>)}</div>}
    </section>

    <section className="history-panel crm__panel" aria-label="活动时间线">
      <div className="panel-header"><h2>活动时间线</h2><span>最近 {activities.length} 条</span></div>
      {activities.length === 0
        ? <div className="empty-state"><strong>暂无跟进活动</strong><span>登记活动后会按时间倒序展示在这里。</span></div>
        : <div className="panel-body crm__timeline"><div className="timeline">{activities.map((activity) => <article className="audit-event" key={activity.activity_id}>
          <time>{formatLocalTime(activity.occurred_at) || '—'}</time>
          <strong>{crmLabel(ACTIVITY_KIND_LABELS, activity.kind)} · {activity.subject || '（无主题）'}</strong>
          <p>
            <span className={`status-badge ${activity.status === 'done' ? 'status-confirmed' : activity.status === 'planned' ? 'status-pending' : 'status-cancelled'}`}>{crmLabel(ACTIVITY_STATUS_LABELS, activity.status)}</span>
            {activity.due_at && <span>到期：{formatLocalTime(activity.due_at)}</span>}
            {activity.created_by_kind === 'agent' && <span>由数字员工写入</span>}
          </p>
        </article>)}</div></div>}
    </section>

    <section className="history-panel crm__panel" aria-label="联系人">
      <div className="panel-header"><h2>联系人</h2><span>电话 / 邮箱默认掩码；明文经专用端点获取并落审计</span></div>
      {contacts.length === 0
        ? <div className="empty-state"><strong>暂无联系人</strong><span>联系人可由线索转化或接口创建。</span></div>
        : <div className="panel-body"><table className="workforce__table">
          <thead><tr><th>姓名</th><th>称谓</th><th>电话</th><th>邮箱</th><th>主联系人</th></tr></thead>
          <tbody>{contacts.map((contact) => <tr key={contact.contact_id}>
            <td><span className="workforce__key">{contact.name}</span></td>
            <td>{contact.title || '—'}</td>
            <td><RevealCell contactId={contact.contact_id} field="phone" masked={contact.phone} value={revealed[`${contact.contact_id}:phone`]} onReveal={reveal} /></td>
            <td><RevealCell contactId={contact.contact_id} field="email" masked={contact.email} value={revealed[`${contact.contact_id}:email`]} onReveal={reveal} /></td>
            <td>{contact.is_primary ? '是' : '否'}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>

    <Toast message={toast} />
  </main>
}

// 掩码值展示 + 「查看明文」按钮：按钮**始终可见**（隐藏按钮不构成权限），越权由服务端返回 403/404 并如实展示。
function RevealCell({ contactId, field, masked, value, onReveal }: { contactId: string; field: CrmRevealField; masked: string; value?: string; onReveal: (contactId: string, field: CrmRevealField) => void }) {
  const shown = value ?? masked
  return <span className="crm-reveal">
    <span className={value ? 'crm-reveal__plain' : ''}>{shown || '—'}</span>
    {value
      ? <small className="crm-reveal__flag">已揭示（不缓存）</small>
      : <button className="text-action" type="button" aria-label={`查看${field === 'phone' ? '电话' : '邮箱'}明文`} onClick={() => onReveal(contactId, field)}>查看明文</button>}
  </span>
}

function InsightBody({ insight }: { insight: CrmInsight }) {
  const content = insight.content ?? { actions: [], summary: '' }
  const actions = content.actions ?? []
  return <div className="crm-plan">
    <p className="crm-plan__summary">{content.summary || '（无摘要）'}</p>
    {content.insufficient_evidence
      ? <CrmNotice tone="info" title="依据不足，无法给出建议"><p>服务端在引用校验后判定：没有可用的有效依据。系统不会用规则文本冒充模型建议。</p></CrmNotice>
      : actions.length === 0
        ? <CrmNotice tone="info" title="没有可展示的建议"><p>本次生成未产出通过校验的动作。</p></CrmNotice>
        : <ul className="crm-plan__actions" role="list">{actions.map((action) => <li key={`${action.target_ref}-${action.action_type}`}>
          <div className="crm-plan__head">
            <strong>{crmLabel(FOLLOWUP_ACTION_LABELS, action.action_type)}</strong>
            <span className="history-meta"><span>目标：{action.target_ref}</span><span>置信度：{(action.confidence * 100).toFixed(0)}%（模型自评，未经校准）</span></span>
          </div>
          <p className="crm-plan__reason">{action.reason || '（无理由）'}</p>
          {action.evidence_refs.length > 0 && <div className="crm__chips">{action.evidence_refs.map((ref) => <span className="workforce__chip" key={ref}>{ref}</span>)}</div>}
        </li>)}</ul>}
    <div className="history-meta">
      <span>模型：{insight.model_key}</span>
      <span>触发者：{insight.generated_by}</span>
      <span>{formatLocalTime(insight.created_at) || '—'}</span>
    </div>
    {insight.dropped_refs?.length > 0 && <div className="crm-plan__dropped">
      <strong>模型引用了无效依据（{insight.dropped_refs.length} 条，已丢弃）</strong>
      <div className="crm__chips">{insight.dropped_refs.map((item, index) => <span className="workforce__chip" key={`${item.reason}-${index}`}>
        {`${crmLabel(DROPPED_REF_LABELS, item.reason)}：${formatRawRef(item.raw)}`}
      </span>)}</div>
    </div>}
    <p className="role-note">建议仅供参考，系统不提供「采纳 → 自动执行」路径；引用对象需人工核查。</p>
  </div>
}

function formatRawRef(raw: unknown): string {
  if (typeof raw === 'string') return raw
  if (raw === null || raw === undefined) return '—'
  return '…'
}