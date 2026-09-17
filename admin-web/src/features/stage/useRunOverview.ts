import { useCallback, useEffect, useState } from 'react'
import { getRunMetrics, getTask } from '../runDetail/api'
import { asRunError } from '../runDetail/state'
import type { RunErrorShape, RunMetrics, RunTask } from '../runDetail/types'

export interface RunOverviewState {
  metrics: RunMetrics | null
  task: RunTask | null
  loading: boolean
  error: RunErrorShape | null
  /** 运行发起人是不是当前用户（审批卡据此决定是否展示决议按钮；服务端仍会 403 兜底）。 */
  isInitiator: boolean
  reload: () => void
}

/**
 * 舞台「运行概览」：指标（既有 `GET /runs/{run_id}/metrics`）+ 承载任务（判断发起人）。
 * 任务取不到只影响发起人判断（决议按钮照显，服务端仍是权威），不升级为整块错误。
 */
export function useRunOverview(runId: string | undefined, reloadToken = 0): RunOverviewState {
  const [metrics, setMetrics] = useState<RunMetrics | null>(null)
  const [task, setTask] = useState<RunTask | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<RunErrorShape | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!runId) {
      setMetrics(null)
      setTask(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const loaded = await getRunMetrics(runId)
        if (cancelled) return
        setMetrics(loaded)
        try {
          const owner = await getTask(loaded.task_id)
          if (!cancelled) setTask(owner)
        } catch {
          if (!cancelled) setTask(null)
        }
      } catch (cause) {
        if (!cancelled) {
          setMetrics(null)
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

  const currentUserId = import.meta.env.VITE_USER_ID || 'admin'
  return { metrics, task, loading, error, isInitiator: task?.created_by === currentUserId, reload }
}