import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { EmptyState } from '../../components/ui/EmptyState'
import { formatLocalTime } from '../../utils/time'
import { confirmQuote, convertQuoteToContract, getQuote, listQuotes, replaceQuoteLines, voidQuote, type QuoteLineInput } from './api'
import { CrmNotice, Pagination, AccountName, useAccountNames, type AccountNames } from './CrmShared'
import { asCrmError, centsToYuanInput, CRM_LIMIT_OPTIONS, formatCents, parseYuanToCents } from './state'
import { crmLabel, QUOTE_STATUS_LABELS, type CrmErrorShape, type CrmPage, type CrmQuote, type CrmQuoteLine } from './types'

const STATUS_OPTIONS = ['draft', 'confirmed', 'converted', 'voided']

interface QuotePageState extends CrmPage<CrmQuote> {
  loading: boolean
  error: CrmErrorShape | null
}

export function CrmQuotesPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 客户名映射只在页面挂载时取一次：列表与详情共用，切换视图不重复请求。
  const accountNames = useAccountNames()
  if (selectedId) return <QuoteDetail quoteId={selectedId} accountNames={accountNames} onBack={() => setSelectedId(null)} />
  return <QuoteList accountNames={accountNames} onOpen={setSelectedId} />
}

function QuoteList({ accountNames, onOpen }: { accountNames: AccountNames; onOpen: (quoteId: string) => void }) {
  const [status, setStatus] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState<QuotePageState>({ items: [], total: 0, limit: 50, offset: 0, loading: true, error: null })

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await listQuotes({ status, limit, offset })
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

  // 统计条数字来源：命中总数取服务端 total；其余按本页已加载列表现算。
  const draftOnPage = state.items.filter((item) => item.status === 'draft').length
  const confirmedOnPage = state.items.filter((item) => item.status === 'confirmed').length

  return <main className="main-content t3 crm">
    <div className="t3__intro">
      <p className="page-desc">报价金额一律以整数分存储与传输，页面按整数运算换算为元展示；行金额与税额由服务端重算，确认后冻结（不可改行 / 改金额）。</p>
      <div className="t3__actions">
        <button className="btn btn--secondary" type="button" disabled={state.loading} onClick={() => void load()}>刷新</button>
      </div>
    </div>

    <div className="metrics">
      <div className="metric">
        <div className="metric__label">命中总数</div>
        <div className="metric__value">{state.loading ? '—' : state.total}</div>
        <div className="metric__hint">当前状态筛选下服务端返回的总条数</div>
      </div>
      <div className="metric">
        <div className="metric__label">本页报价</div>
        <div className="metric__value">{state.loading ? '—' : state.items.length}</div>
        <div className="metric__hint">按本页统计：当前页展示的报价单数</div>
      </div>
      <div className="metric">
        <div className="metric__label">本页草稿</div>
        <div className="metric__value">{state.loading ? '—' : draftOnPage}</div>
        <div className="metric__hint">按本页统计：仍可编辑报价行的单数</div>
      </div>
      <div className="metric">
        <div className="metric__label">本页已确认</div>
        <div className="metric__value">{state.loading ? '—' : confirmedOnPage}</div>
        <div className="metric__hint">按本页统计：已确认并冻结、尚未转合同的单数</div>
      </div>
    </div>

    <div className="toolbar">
      <label className="history-filter">状态
        <select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>
          <option value="">全部</option>
          {STATUS_OPTIONS.map((option) => <option value={option} key={option}>{crmLabel(QUOTE_STATUS_LABELS, option)}</option>)}
        </select>
      </label>
      <label className="history-filter">每页条数
        <select value={String(limit)} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0) }}>
          {CRM_LIMIT_OPTIONS.map((size) => <option value={size} key={size}>{size} 条</option>)}
        </select>
      </label>
      <span className="history-count">共 {state.total} 条</span>
    </div>

    <section className="card" aria-label="报价列表">
      <div className="card__head"><h2>报价列表</h2><span className="badge">{state.total} 条</span></div>

      {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载报价列表…</div>}

      {!state.loading && state.error && <div className="card__body">
        <CrmNotice
          tone="error"
          title={state.error.status === 403 ? '当前账号无权查看报价列表' : '报价列表加载失败'}
          action={state.error.status !== 403 && state.error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
        >
          <p>{state.error.message}</p>
        </CrmNotice>
      </div>}

      {!state.loading && !state.error && (state.items.length === 0
        ? <EmptyState illustration="list" title="暂无报价" text="调整状态筛选，或先为客户建立报价。">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => void load()}>刷新</button>
          </EmptyState>
        : <div className="card__body"><table className="workforce__table">
          <thead><tr><th>单号</th><th>客户</th><th>状态</th><th>合计金额</th><th>有效期至</th><th>确认时间</th><th>操作</th></tr></thead>
          <tbody>{state.items.map((item) => <tr key={item.quote_id}>
            <td><span className="workforce__key">{item.quote_no}</span></td>
            <td><AccountName accountId={item.account_id} names={accountNames} /></td>
            <td><span className={`status-badge ${quoteTone(item.status)}`}>{crmLabel(QUOTE_STATUS_LABELS, item.status)}</span></td>
            <td>{formatCents(item.total_cents)}</td>
            <td>{item.valid_until || '—'}</td>
            <td>{formatLocalTime(item.confirmed_at) || '—'}</td>
            <td><button className="text-action" type="button" onClick={() => onOpen(item.quote_id)}>查看详情</button></td>
          </tr>)}</tbody>
        </table></div>)}

      {!state.loading && !state.error && <Pagination total={state.total} limit={state.limit} offset={state.offset} loading={state.loading} onPrev={() => setOffset(Math.max(0, state.offset - state.limit))} onNext={() => setOffset(state.offset + state.limit)} />}
    </section>
  </main>
}

function quoteTone(status: string): string {
  if (status === 'confirmed') return 'status-confirmed'
  if (status === 'converted') return 'status-approved'
  if (status === 'voided') return 'status-cancelled'
  return 'status-reviewing'
}

// ---------------------------------------------------------------- 详情（draft 可编辑行）

interface EditableLine {
  description: string
  qty: string
  unit_price_yuan: string
  tax_rate_bp: string
}

function toEditable(line: CrmQuoteLine): EditableLine {
  return {
    description: line.description,
    qty: String(line.qty),
    unit_price_yuan: centsToYuanInput(line.unit_price_cents),
    tax_rate_bp: String(line.tax_rate_bp),
  }
}

function QuoteDetail({ quoteId, accountNames, onBack }: { quoteId: string; accountNames: AccountNames; onBack: () => void }) {
  const [quote, setQuote] = useState<CrmQuote | null>(null)
  const [lines, setLines] = useState<CrmQuoteLine[]>([])
  const [draftLines, setDraftLines] = useState<EditableLine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<CrmErrorShape | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const apply = useCallback((data: { quote: CrmQuote; lines: CrmQuoteLine[] }) => {
    setQuote(data.quote)
    const nextLines = Array.isArray(data.lines) ? data.lines : []
    setLines(nextLines)
    setDraftLines(nextLines.map(toEditable))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      apply(await getQuote(quoteId))
    } catch (err) {
      setError(asCrmError(err))
    } finally {
      setLoading(false)
    }
  }, [quoteId, apply])

  useEffect(() => { void load() }, [load])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setToast(null)
    try {
      await action()
    } catch (err) {
      const info = asCrmError(err)
      setToast(info.status === 409 ? '状态已被变更，请刷新' : info.message)
      if (info.status === 409) await load()
    } finally {
      setBusy(false)
    }
  }

  const saveLines = async () => {
    const payload: QuoteLineInput[] = []
    for (const [index, line] of draftLines.entries()) {
      const unitPrice = parseYuanToCents(line.unit_price_yuan)
      const taxText = line.tax_rate_bp.trim()
      if (!line.description.trim()) { setToast(`第 ${index + 1} 行缺少描述`); return }
      if (!/^\d+(\.\d{1,3})?$/.test(line.qty.trim()) || Number(line.qty) <= 0) { setToast(`第 ${index + 1} 行数量不合法（最多 3 位小数且大于 0）`); return }
      if (unitPrice === null) { setToast(`第 ${index + 1} 行单价不合法（元，最多 2 位小数）`); return }
      if (!/^\d{1,5}$/.test(taxText) || Number(taxText) > 10000) { setToast(`第 ${index + 1} 行税率必须是 0–10000 的整数万分比`); return }
      payload.push({ description: line.description.trim(), qty: line.qty.trim(), unit_price_cents: unitPrice, tax_rate_bp: Number(taxText) })
    }
    if (payload.length === 0) { setToast('至少保留 1 行'); return }
    await run(async () => {
      apply(await replaceQuoteLines(quoteId, payload))
      setToast('报价行已全量替换，金额由服务端重算')
    })
  }

  if (loading) return <main className="main-content t3 crm"><div className="loading-state" role="status"><span className="loading-dot" />正在加载报价详情…</div></main>
  if (error || !quote) return <main className="main-content t3 crm">
    <div className="t3__intro">
      <p className="page-desc">报价明细：报价行、税额与合计，以及确认 / 转合同 / 作废的状态操作。</p>
      <div className="t3__actions"><button className="btn btn--secondary" type="button" onClick={onBack}>返回列表</button></div>
    </div>
    <CrmNotice
      tone="error"
      title={error?.status === 403 ? '当前账号无权查看该报价' : '报价详情加载失败'}
      action={error?.status !== 403 && error?.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{error?.message ?? '没有找到该报价。'}</p>
    </CrmNotice>
  </main>

  const editable = quote.status === 'draft'

  return <main className="main-content t3 crm">
    <div className="t3__intro">
      <p className="page-desc">报价 <span className="page-code">{quote.quote_no}</span> · 客户 <AccountName accountId={quote.account_id} names={accountNames} /> · 状态 {crmLabel(QUOTE_STATUS_LABELS, quote.status)} · 负责人 {quote.owner_id}</p>
      <div className="t3__actions"><button className="btn btn--secondary" type="button" onClick={onBack}>返回列表</button></div>
    </div>

    {!editable && <CrmNotice tone="info" title="报价已冻结">
      <p>确认后的报价不允许修改行或金额，如需变更请作废后重新开单。</p>
    </CrmNotice>}

    <section className="card" aria-label="报价行">
      <div className="card__head"><h2>报价行</h2><span className="badge">{editable ? '草稿：可编辑行' : '只读'}</span></div>
      <div className="card__body">
        <table className="workforce__table">
          <thead><tr><th>序号</th><th>描述</th><th>数量</th><th>单价（元）</th><th>税率（万分比）</th><th>小计</th><th>税额</th>{editable && <th>操作</th>}</tr></thead>
          <tbody>{draftLines.map((line, index) => <tr key={index}>
            <td>{index + 1}</td>
            <td>{editable
              ? <input className="crm-input" type="text" aria-label={`第 ${index + 1} 行描述`} value={line.description} onChange={(event) => setDraftLines((old) => old.map((row, i) => i === index ? { ...row, description: event.target.value } : row))} />
              : (lines[index]?.description ?? '—')}</td>
            <td>{editable
              ? <input className="crm-input" type="text" inputMode="decimal" aria-label={`第 ${index + 1} 行数量`} value={line.qty} onChange={(event) => setDraftLines((old) => old.map((row, i) => i === index ? { ...row, qty: event.target.value } : row))} />
              : String(lines[index]?.qty ?? '—')}</td>
            <td>{editable
              ? <input className="crm-input" type="text" inputMode="decimal" aria-label={`第 ${index + 1} 行单价`} value={line.unit_price_yuan} onChange={(event) => setDraftLines((old) => old.map((row, i) => i === index ? { ...row, unit_price_yuan: event.target.value } : row))} />
              : formatCents(lines[index]?.unit_price_cents)}</td>
            <td>{editable
              ? <input className="crm-input" type="number" min={0} max={10000} aria-label={`第 ${index + 1} 行税率`} value={line.tax_rate_bp} onChange={(event) => setDraftLines((old) => old.map((row, i) => i === index ? { ...row, tax_rate_bp: event.target.value } : row))} />
              : String(lines[index]?.tax_rate_bp ?? 0)}</td>
            <td>{formatCents(lines[index]?.line_subtotal_cents)}</td>
            <td>{formatCents(lines[index]?.line_tax_cents)}</td>
            {editable && <td><button className="text-action" type="button" disabled={draftLines.length <= 1} onClick={() => setDraftLines((old) => old.filter((_, i) => i !== index))}>删除</button></td>}
          </tr>)}</tbody>
        </table>

        <div className="crm-totals">
          <span>小计 {formatCents(quote.subtotal_cents)}</span>
          <span>税额 {formatCents(quote.tax_cents)}</span>
          <b>合计 {formatCents(quote.total_cents)}</b>
        </div>

        {editable && <div className="actions crm__actions">
          <button className="btn btn--secondary" type="button" disabled={busy} onClick={() => setDraftLines((old) => [...old, { description: '', qty: '1', unit_price_yuan: '0.00', tax_rate_bp: '0' }])}>新增一行</button>
          <button className="btn btn--primary" type="button" disabled={busy} onClick={() => void saveLines()}>保存报价行</button>
        </div>}
      </div>
    </section>

    <section className="card" aria-label="报价动作">
      <div className="card__head"><h2>状态操作</h2><span className="page-meta">单向推进 · 联动人工触发</span></div>
      <div className="card__body">
        <div className="actions crm__actions">
          {quote.status === 'draft' && <button className="btn btn--primary" type="button" disabled={busy} onClick={() => void run(async () => {
            setQuote(await confirmQuote(quoteId))
            setToast('报价已确认并冻结')
          })}>确认报价</button>}
          {quote.status === 'confirmed' && <button className="btn btn--primary" type="button" disabled={busy} onClick={() => void run(async () => {
            const contract = await convertQuoteToContract(quoteId)
            setToast(`已转合同：${contract.contract_no}`)
            await load()
          })}>转合同</button>}
          {(quote.status === 'draft' || quote.status === 'confirmed') && <button className="btn btn--danger" type="button" disabled={busy} onClick={() => void run(async () => {
            setQuote(await voidQuote(quoteId))
            setToast('报价已作废')
          })}>作废报价</button>}
          {quote.status === 'converted' && <span className="role-note">已转合同{quote.converted_contract_id ? `：${quote.converted_contract_id}` : ''}（终态）</span>}
          {quote.status === 'voided' && <span className="role-note">已作废（终态）</span>}
        </div>
      </div>
    </section>

    <Toast message={toast} />
  </main>
}