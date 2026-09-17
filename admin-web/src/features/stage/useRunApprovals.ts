import { useCallback, useEffect, useState } from 'react'
import { decideRunApproval, listRunApprovals } from '../runDetail/api'
import { asRunError } from '../runDetail/state'
import type { RunApproval, RunErrorShape } from '../runDetail/types'

export interface RunApprovalsState {
  items: RunApproval[]
  loading: boolean
  error: RunErrorShape | null
  decidingId: string | null
  /** 决议（无本地乐观更新：无论成败都以服务端回流为准）。返回错误文案；成功返回 null。 */
  decide: (approvalId: string, approved: boolean) => Promise<string | null>
  reload: () => void
}

/** 运行审批（既有 `GET/POST /runs/{run_id}/approvals...`，**不新增后端契约**）。 */
export function useRunApprovals(runId: string | undefined): RunApprovalsState {
  const [items, setItems] = useState<RunApproval[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<RunErrorShape | null>(null)
  const [decidingId, setDecidingId] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!runId) {
      setItems([])
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const data = await listRunApprovals(runId)
        if (!cancelled) setItems(Array.isArray(data.items) ? data.items : [])
      } catch (cause) {
        if (!cancelled) {
          setItems([])
          setError(asRunError(cause))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId, nonce])

  const decide = useCallback(
    async (approvalId: string, approved: boolean) => {
      if (!runId) return '缺少运行标识，无法决议。'
      setDecidingId(approvalId)
      try {
        await decideRunApproval(runId, approvalId, approved)
        reload()
        return null
      } catch (cause) {
        const mapped = asRunError(cause)
        // 409 表示已被决议 / 运行已终态：刷新拿最新状态（与运行详情页同一口径）。
        if (mapped.status === 409) reload()
        return mapped.message
      } finally {
        setDecidingId(null)
      }
    },
    [runId, reload],
  )

  return { items, loading, error, decidingId, decide, reload }
}