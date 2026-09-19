import { useCallback, useEffect, useState } from 'react'
import { decideRunAcceptance, listRunAcceptanceDecisions, newAcceptanceIdempotencyKey, promoteRunToTask } from './api'
import { asRunError } from './state'
import { acceptanceDecisionLabel, type RunAcceptanceDecision, type RunAcceptancePromotion, type RunErrorShape } from './types'
import { formatLocalTime } from '../../utils/time'

/**
 * S2 人工验收决议 + 沉淀入口（运行详情「交付」区块内的写入口）。
 *
 * 纪律（契约「运行验收决议（S2 · 人工验收）」/「运行沉淀（S2 · 存成任务）」）：
 * - **服务端权威**：决议 / 沉淀成功后重取权威态（`onRefresh` 由宿主页刷新交付与结构判定），不做本地乐观更新；
 * - **打回必须写原因**：前端只是提前拦住空原因，服务端仍会独立校验（422 原样展示）；
 * - **按钮隐藏 ≠ 权限**：`canDecide` 只是体验层预判，服务端会再判一次（越权一律 404）；
 * - **只记录不改状态**：本组件不承诺「重跑」——重做入口在发起这次运行的对话页（那儿持有原调用）；
 * - **先确认完成才给沉淀**：只有最新决议是「已确认完成」时才出现「存成任务」；
 * - **无假按钮**：「设为自动化」属自动化调度（未交付）⇒ 只给行内说明，不摆按钮。
 */

const REASON_MAX = 500
const TITLE_MAX = 120

export function AcceptanceDecisionPanel({
  runId,
  runStatus,
  canDecide,
  defaultTitle,
  onRefresh,
  onNotice,
}: {
  runId: string
  /** 服务端返回的运行状态；只有终态（已完成 / 失败 / 已取消）才给决议入口。 */
  runStatus: string | undefined
  /** 体验层预判（发起人 / CEO / 超管）；服务端仍是权威。 */
  canDecide: boolean
  /** 沉淀任务的标题默认值（来源承载任务标题）；用户可改。 */
  defaultTitle?: string
  /** 加载 / 决议 / 沉淀成功后重取权威态（交付物、结构判定、概览）。 */
  onRefresh?: () => void | Promise<void>
  onNotice?: (message: string) => void
}) {
  const [items, setItems] = useState<RunAcceptanceDecision[]>([])
  const [promotion, setPromotion] = useState<RunAcceptancePromotion | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<RunErrorShape | null>(null)
  const [busy, setBusy] = useState<null | 'confirmed' | 'rejected'>(null)
  const [actionError, setActionError] = useState<RunErrorShape | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [title, setTitle] = useState('')
  const [promoting, setPromoting] = useState(false)
  const [promoteError, setPromoteError] = useState<RunErrorShape | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listRunAcceptanceDecisions(runId)
      setItems(Array.isArray(data.items) ? data.items : [])
      setPromotion(data.promotion ?? null)
    } catch (cause) {
      setItems([])
      setPromotion(null)
      setError(asRunError(cause))
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => { void load() }, [load])

  // 标题默认填来源承载任务标题（服务端权威数据）；用户改过之后不再被覆盖。
  useEffect(() => {
    setTitle((current) => (current.trim() ? current : (defaultTitle ?? '')))
  }, [defaultTitle])

  const decide = async (decision: 'confirmed' | 'rejected') => {
    setBusy(decision)
    setActionError(null)
    try {
      const stored = await decideRunAcceptance(runId, {
        decision,
        reason: decision === 'rejected' ? reason.trim() : '',
        idempotencyKey: newAcceptanceIdempotencyKey(),
      })
      // 服务端权威：重取决议历史与交付判定（不做本地拼接）。
      await load()
      await onRefresh?.()
      setRejectOpen(false)
      setReason('')
      const label = stored.created ? acceptanceDecisionLabel(stored.decision) : `${acceptanceDecisionLabel(stored.decision)}（此前已记录）`
      onNotice?.(label)
    } catch (cause) {
      setActionError(asRunError(cause))
    } finally {
      setBusy(null)
    }
  }

  // 沉淀：不做本地拼接——成功后重取（拿到服务端的 promotion 视图与任务标识）。
  const promote = async () => {
    setPromoting(true)
    setPromoteError(null)
    try {
      const result = await promoteRunToTask(runId, title.trim())
      await load()
      await onRefresh?.()
      onNotice?.(result.created ? `已存成任务：${result.promotion.title}` : '这次运行此前已存成任务，未重复创建')
    } catch (cause) {
      setPromoteError(asRunError(cause))
    } finally {
      setPromoting(false)
    }
  }

  const latest = items[0] ?? null
  const terminal = runStatus === 'completed' || runStatus === 'failed' || runStatus === 'cancelled'
  const confirmed = latest?.decision === 'confirmed'

  return (
    <div className="acceptance">
      {loading && (
        <div className="loading-state" role="status"><span className="loading-dot" />正在读取验收记录…</div>
      )}

      {!loading && error && (
        <div className="notice notice-error" role="alert">
          <div><strong>验收记录读取失败</strong><p>{error.message}</p></div>
          {error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
        </div>
      )}

      {!loading && !error && (
        <p className="acceptance__state">
          {latest ? (
            <>
              <span className={`status-badge status-${latest.decision === 'confirmed' ? 'completed' : 'failed'}`}>
                {acceptanceDecisionLabel(latest.decision)}
              </span>
              <span className="acceptance__meta">
                {latest.decided_by} · {formatLocalTime(latest.decided_at)}
                {items.length > 1 ? ` · 共 ${items.length} 次决议（历史保留）` : ''}
              </span>
              {latest.reason && <span className="acceptance__reason">原因：{latest.reason}</span>}
            </>
          ) : (
            <span className="acceptance__meta">尚未验收：这次交付还没有人给出结论。</span>
          )}
        </p>
      )}

      {!loading && !error && !terminal && (
        <p className="stage-hint">运行尚未结束，暂不能验收；结束后再回来判「确认完成」或「打回重做」。</p>
      )}

      {!loading && !error && terminal && !canDecide && (
        <p className="stage-hint">仅任务发起人、CEO 或超级管理员可以验收（服务端仍会独立判定）。</p>
      )}

      {!loading && !error && terminal && canDecide && (
        <>
          <div className="acceptance__actions">
            <button
              className="btn btn--primary"
              type="button"
              disabled={busy !== null}
              onClick={() => void decide('confirmed')}
            >
              {busy === 'confirmed' ? '正在记录…' : '确认完成'}
            </button>
            <button
              className="btn btn--secondary"
              type="button"
              disabled={busy !== null}
              onClick={() => setRejectOpen((open) => !open)}
            >
              打回重做
            </button>
          </div>

          {rejectOpen && (
            <div className="acceptance__reject">
              <label className="ws-field">
                打回原因（必填）
                <textarea
                  aria-label="打回原因"
                  rows={3}
                  maxLength={REASON_MAX}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="写清哪里不符合要求，便于重做时对照"
                />
              </label>
              <div className="acceptance__reject-foot">
                <span className="ws-counter">{reason.trim().length} / {REASON_MAX}</span>
                <button
                  className="btn btn--danger"
                  type="button"
                  disabled={busy !== null || reason.trim().length === 0}
                  onClick={() => void decide('rejected')}
                >
                  {busy === 'rejected' ? '正在记录…' : '确认打回'}
                </button>
              </div>
              <p className="stage-hint">打回只记录结论与原因：原运行的状态、产物都不会被改动；重做请回发起这次运行的对话页（那儿还持有原调用）。</p>
            </div>
          )}
        </>
      )}

      {actionError && (
        <div className="notice notice-error" role="alert">
          <div><strong>验收未记录</strong><p>{actionError.message}</p></div>
        </div>
      )}

      {/* ② 沉淀入口（S2）：先是「确认完成」，才谈「存成任务」——未确认时如实说明缺哪一步。 */}
      {!loading && !error && !confirmed && (
        <p className="stage-hint">沉淀入口（存成任务）在「确认完成」之后出现：这次交付还没有被确认。</p>
      )}

      {!loading && !error && confirmed && (
        <div className="acceptance__promote">
          {promotion ? (
            <>
              <p className="acceptance__state">
                <span className="status-badge status-completed">已存成任务</span>
                <span className="acceptance__meta">
                  {promotion.title} · {promotion.promoted_by} · {formatLocalTime(promotion.promoted_at)}
                  {` · ${promotion.task_id}`}
                </span>
              </p>
              {/* 不摆「打开任务」：平任务的列表 / 详情页属任务中心（未立项），点过去只会落空。 */}
              <p className="stage-hint">
                任务已建好并登记了这次运行的来源；任务的列表与详情页属后续范围（任务中心），现在可在审计与这里按编号追溯。
              </p>
            </>
          ) : (
            <>
              <label className="ws-field">
                任务标题
                <input
                  aria-label="任务标题"
                  type="text"
                  maxLength={TITLE_MAX}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="给这个可再跑的任务起个名字"
                />
              </label>
              <div className="acceptance__actions">
                <button
                  className="btn btn--primary"
                  type="button"
                  disabled={promoting || title.trim().length === 0}
                  onClick={() => void promote()}
                >
                  {promoting ? '正在沉淀…' : '存成任务'}
                </button>
              </div>
              <p className="stage-hint">
                新任务的执行员工、风险档与预算由服务端按这次运行自动带过来（页面上改不了）；一个运行只能沉淀一次，重复点击不会多建任务。
              </p>
            </>
          )}
          {promoteError && (
            <div className="notice notice-error" role="alert">
              <div><strong>沉淀未完成</strong><p>{promoteError.message}</p></div>
            </div>
          )}
          <p className="stage-hint">「设为自动化」属定时调度（尚未交付）：现在先把这次做法存成任务，调度能力交付后再挂。</p>
        </div>
      )}
    </div>
  )
}