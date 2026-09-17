import { useCallback, useEffect, useState } from 'react'
import { getRunAcceptance } from '../conversation/api'
import type { RunAcceptance } from '../conversation/types'
import type { RunErrorShape } from '../runDetail/types'
import { asRunError } from '../runDetail/state'

export interface RunAcceptanceState {
  acceptance: RunAcceptance | null
  loading: boolean
  error: RunErrorShape | null
  reload: () => void
}

const asBool = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null)
const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

/**
 * 结构判定的**白名单投影**：字段形态不符即整条丢弃（不猜测、不补默认值）；
 * `verdict` 只接受服务端两个受控取值，未知取值一律丢弃（界面回落为「判定不可用」）。
 */
function acceptanceView(raw: unknown): RunAcceptance | null {
  if (typeof raw !== 'object' || raw === null) return null
  const row = raw as Record<string, unknown>
  const runId = typeof row.run_id === 'string' && row.run_id ? row.run_id : null
  const verdict = row.verdict === 'met' || row.verdict === 'unmet' ? row.verdict : null
  const checks = (typeof row.checks === 'object' && row.checks !== null ? row.checks : {}) as Record<string, unknown>
  const steps = (typeof row.steps === 'object' && row.steps !== null ? row.steps : {}) as Record<string, unknown>
  const stepsComplete = asBool(checks.steps_complete)
  const noPending = asBool(checks.no_pending_approvals)
  const finishOk = asBool(checks.finish_reason_ok)
  const completed = asNumber(steps.completed)
  const total = asNumber(steps.total)
  const pending = asNumber(row.pending_approvals)
  if (!runId || !verdict || stepsComplete === null || noPending === null || finishOk === null) return null
  if (completed === null || total === null || pending === null) return null
  return {
    run_id: runId,
    verdict,
    checks: { steps_complete: stepsComplete, no_pending_approvals: noPending, finish_reason_ok: finishOk },
    steps: { completed, total },
    pending_approvals: pending,
    finish_reason: typeof row.finish_reason === 'string' ? row.finish_reason : null,
    status: typeof row.status === 'string' ? row.status : '',
  }
}

/**
 * 舞台「收尾检查」的**结构判定**（P2c-4）：`GET /runs/{run_id}/acceptance`（**纯读**）。
 *
 * 纪律：判定在服务端（不调模型、不改运行状态），前端**不自行复算规则**；无 run ⇒ 空态（不请求）；
 * 读失败按四态渲染（可重试 / 不可重试），**不谎报达标**。
 */
export function useRunAcceptance(runId: string | undefined, reloadToken = 0): RunAcceptanceState {
  const [acceptance, setAcceptance] = useState<RunAcceptance | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<RunErrorShape | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!runId) {
      setAcceptance(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const loaded = await getRunAcceptance(runId)
        if (cancelled) return
        setAcceptance(acceptanceView(loaded))
      } catch (cause) {
        if (!cancelled) {
          setAcceptance(null)
          setError(asRunError(cause))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId, reloadToken, nonce])

  return { acceptance, loading, error, reload }
}