import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Toast } from '../../components/Toast'
import { formatLocalTime } from '../../utils/time'
import { getContract, listContracts, registerPayment, registerSignature, submitContractForSign, voidContract } from './api'
import { CrmNotice, Pagination } from './CrmShared'
import { asCrmError, CRM_LIMIT_OPTIONS, formatCents, formatRatio, parseYuanToCents } from './state'
import { CONTRACT_STATUS_LABELS, crmLabel, type CrmContract, type CrmErrorShape, type CrmPage } from './types'

const STATUS_OPTIONS = ['draft', 'pending_sign', 'signed', 'voided', 'expired']

interface ContractPageState extends CrmPage<CrmContract> {
  loading: boolean
  error: CrmErrorShape | null
}

export function CrmContractsPage({ onNavigate }: { onNavigate?: (view: AppView) => void } = {}) {
  void onNavigate
  const [selectedId, setSelectedId] = useState<string | null>(null)
  if (selectedId) return <ContractDetail contractId={selectedId} onBack={() => setSelectedId(null)} />
  return <ContractList onOpen={setSelectedId} />
}

function ContractList({ onOpen }: { onOpen: (contractId: string) => void }) {
  const [status, setStatus] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState<ContractPageState>({ items: [], total: 0, limit: 50, offset: 0, loading: true, error: null })

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const data = await listContracts({ status, limit, offset })
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

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">合同</h1>
        <p className="page-desc">合同金额与回款一律整数分；签署结果与回款均为人工登记，系统只做台账，不承诺法律效力。</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
    </div>

    <div className="toolbar">
      <label className="history-filter">状态
        <select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>
          <option value="">全部</option>
          {STATUS_OPTIONS.map((option) => <option value={option} key={option}>{crmLabel(CONTRACT_STATUS_LABELS, option)}</option>)}
        </select>
      </label>
      <label className="history-filter">每页条数
        <select value={String(limit)} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0) }}>
          {CRM_LIMIT_OPTIONS.map((size) => <option value={size} key={size}>{size} 条</option>)}
        </select>
      </label>
      <span className="history-count">共 {state.total} 条</span>
    </div>

    {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载合同列表…</div>}
    {!state.loading && state.error && <CrmNotice
      tone="error"
      title="合同列表加载失败"
      action={state.error.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{state.error.message}</p>
    </CrmNotice>}
    {!state.loading && !state.error && <section className="history-panel crm__panel" aria-label="合同列表">
      <div className="panel-header"><h2>合同列表</h2><span>{state.total} 条</span></div>
      {state.items.length === 0
        ? <div className="empty-state"><strong>暂无合同</strong><span>调整状态筛选，或从已确认报价转合同。</span></div>
        : <div className="panel-body"><table className="workforce__table">
          <thead><tr><th>合同号</th><th>标题</th><th>客户</th><th>状态</th><th>合同金额</th><th>已回款</th><th>回款进度</th><th>到期日</th><th>操作</th></tr></thead>
          <tbody>{state.items.map((item) => <tr key={item.contract_id}>
            <td><span className="workforce__key">{item.contract_no}</span></td>
            <td>{item.title}</td>
            <td>{item.account_id}</td>
            <td><span className={`status-badge ${contractTone(item.status)}`}>{crmLabel(CONTRACT_STATUS_LABELS, item.status)}</span></td>
            <td>{formatCents(item.amount_cents)}</td>
            <td>{formatCents(item.paid_cents)}</td>
            <td>{paymentProgress(item)}</td>
            <td>{item.ends_on || '—'}</td>
            <td><button className="text-action" type="button" onClick={() => onOpen(item.contract_id)}>查看详情</button></td>
          </tr>)}</tbody>
        </table></div>}
      <Pagination total={state.total} limit={state.limit} offset={state.offset} loading={state.loading} onPrev={() => setOffset(Math.max(0, state.offset - state.limit))} onNext={() => setOffset(state.offset + state.limit)} />
    </section>}
  </main>
}

function contractTone(status: string): string {
  if (status === 'signed') return 'status-confirmed'
  if (status === 'pending_sign') return 'status-pending'
  if (status === 'voided') return 'status-failed'
  if (status === 'expired') return 'status-cancelled'
  return 'status-reviewing'
}

// 回款进度是比例展示（非金额运算）：金额本身始终整数分。
function paymentProgress(contract: CrmContract): string {
  if (!contract.amount_cents) return '—'
  return formatRatio(contract.paid_cents / contract.amount_cents, 'percent')
}

// ---------------------------------------------------------------- 详情

function ContractDetail({ contractId, onBack }: { contractId: string; onBack: () => void }) {
  const [contract, setContract] = useState<CrmContract | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<CrmErrorShape | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [signedAt, setSignedAt] = useState('')
  const [documentKey, setDocumentKey] = useState('')
  const [paymentYuan, setPaymentYuan] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setContract(await getContract(contractId))
    } catch (err) {
      setError(asCrmError(err))
    } finally {
      setLoading(false)
    }
  }, [contractId])

  useEffect(() => { void load() }, [load])

  const apply = useCallback((next: CrmContract) => setContract(next), [])

  const run = async (action: () => Promise<void>, conflictMessage = '状态已被变更，请刷新') => {
    setBusy(true)
    setToast(null)
    try {
      await action()
    } catch (err) {
      const info = asCrmError(err)
      setToast(info.status === 409 ? conflictMessage : info.message)
      if (info.status === 409) await load()
    } finally {
      setBusy(false)
    }
  }

  const submitSignature = async () => {
    if (!signedAt) { setToast('请先选择签署时间'); return }
    const parsed = new Date(signedAt)
    if (Number.isNaN(parsed.getTime())) { setToast('签署时间格式无法解析'); return }
    await run(async () => {
      apply(await registerSignature(contractId, { signed_at: parsed.toISOString(), document_object_key: documentKey.trim() || undefined }))
      setToast('已登记签署结果（人工台账，系统不承诺法律效力）')
    })
  }

  const submitPayment = async () => {
    const cents = parseYuanToCents(paymentYuan)
    if (cents === null || cents <= 0) { setToast('回款金额需为大于 0 的元金额（最多 2 位小数）'); return }
    await run(async () => {
      apply(await registerPayment(contractId, cents))
      setPaymentYuan('')
      setToast('回款已登记（人工输入）')
    }, '回款登记被拒绝：仅已签署合同可登记，且累计回款不能超过合同金额。')
  }

  if (loading) return <main className="main-content content-history crm"><div className="loading-state" role="status"><span className="loading-dot" />正在加载合同详情…</div></main>
  if (error || !contract) return <main className="main-content content-history crm">
    <div className="page-head"><div><h1 className="page-title">合同详情</h1></div><div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div></div>
    <CrmNotice
      tone="error"
      title="合同详情加载失败"
      action={error?.retryable ? <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button> : undefined}
    >
      <p>{error?.message ?? '没有找到该合同。'}</p>
    </CrmNotice>
  </main>

  return <main className="main-content content-history crm">
    <div className="page-head">
      <div>
        <h1 className="page-title">{contract.contract_no}</h1>
        <p className="page-desc">{contract.title} · 客户 {contract.account_id} · 状态 {crmLabel(CONTRACT_STATUS_LABELS, contract.status)}</p>
      </div>
      <div className="actions"><button className="button" type="button" onClick={onBack}>返回列表</button></div>
    </div>

    <CrmNotice tone="info" title="签署为人工登记，系统不承诺法律效力">
      <p>本段没有电子签章 provider：签署时间与签署件由人工上传 / 输入后登记；后台只做台账，不对签署效力或存证效力作任何承诺。</p>
    </CrmNotice>

    <section className="history-panel crm__panel" aria-label="合同要素">
      <div className="panel-header"><h2>合同要素</h2><span>{contract.contract_id}</span></div>
      <div className="panel-body">
        <div className="run-detail__grid">
          <div className="run-detail__item"><span className="run-detail__label">合同金额</span><span className="run-detail__value">{formatCents(contract.amount_cents)}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">已回款</span><span className="run-detail__value">{formatCents(contract.paid_cents)}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">回款进度</span><span className="run-detail__value">{paymentProgress(contract)}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">起始日</span><span className="run-detail__value">{contract.starts_on || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">到期日</span><span className="run-detail__value">{contract.ends_on || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">签署时间（人工登记）</span><span className="run-detail__value">{formatLocalTime(contract.signed_at) || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">关联报价</span><span className="run-detail__value">{contract.quote_id || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">关联商机</span><span className="run-detail__value">{contract.opportunity_id || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">负责人</span><span className="run-detail__value">{contract.owner_id}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">附件对象键</span><span className="run-detail__value">{contract.document_object_key || '—'}</span></div>
          <div className="run-detail__item"><span className="run-detail__label">创建时间</span><span className="run-detail__value">{formatLocalTime(contract.created_at) || '—'}</span></div>
        </div>
      </div>
    </section>

    <section className="history-panel crm__panel" aria-label="合同状态操作">
      <div className="panel-header"><h2>状态操作</h2><span>单向推进 · 人工登记</span></div>
      <div className="panel-body">
        {contract.status === 'draft' && <div className="actions crm__actions">
          <button className="button primary" type="button" disabled={busy} onClick={() => void run(async () => {
            apply(await submitContractForSign(contractId))
            setToast('已提交待签（线下签署进行中）')
          })}>提交待签</button>
          <button className="button danger" type="button" disabled={busy} onClick={() => void run(async () => {
            apply(await voidContract(contractId))
            setToast('合同已作废')
          })}>作废合同</button>
        </div>}

        {contract.status === 'pending_sign' && <div className="crm-signature">
          <label className="ws-field">签署时间（必填）
            <input aria-label="签署时间" type="datetime-local" value={signedAt} onChange={(event) => setSignedAt(event.target.value)} />
          </label>
          <label className="ws-field">签署件对象键（可选）
            <input aria-label="签署件对象键" type="text" value={documentKey} onChange={(event) => setDocumentKey(event.target.value)} placeholder="对象存储引用，人工上传后填写" />
          </label>
          <div className="actions crm__actions">
            <button className="button primary" type="button" disabled={busy} onClick={() => void submitSignature()}>登记签署结果</button>
            <button className="button danger" type="button" disabled={busy} onClick={() => void run(async () => {
              apply(await voidContract(contractId))
              setToast('合同已作废')
            })}>作废合同</button>
          </div>
        </div>}

        {contract.status === 'signed' && <div className="crm-signature">
          <label className="ws-field">本次回款金额（元）
            <input aria-label="回款金额（元）" type="text" inputMode="decimal" value={paymentYuan} onChange={(event) => setPaymentYuan(event.target.value)} placeholder="例如 12000.00" />
          </label>
          <div className="actions crm__actions">
            <button className="button primary" type="button" disabled={busy} onClick={() => void submitPayment()}>登记回款</button>
            <button className="button danger" type="button" disabled={busy} onClick={() => void run(async () => {
              apply(await voidContract(contractId))
              setToast('合同已作废（登记为终止 / 撤销，系统不解释法律后果）')
            })}>作废合同</button>
          </div>
        </div>}

        {(contract.status === 'voided' || contract.status === 'expired') && <span className="role-note">{crmLabel(CONTRACT_STATUS_LABELS, contract.status)}（终态，无可执行操作）</span>}
      </div>
    </section>

    <Toast message={toast} />
  </main>
}