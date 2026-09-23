import { useCallback, useEffect, useState } from 'react'
import { listRunArtifacts } from '../runDetail/services/runService'
import { asRunError } from '../runDetail/state'
import type { RunArtifact, RunErrorShape } from '../runDetail/types'

export interface RunArtifactsState {
  items: RunArtifact[]
  loading: boolean
  error: RunErrorShape | null
  reload: () => void
}

const asString = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

/** 单条产物登记的**白名单投影**（未知 / 注入键一律丢弃；缺虚拟路径即整条丢弃）。 */
function artifactView(item: unknown): RunArtifact | null {
  if (typeof item !== 'object' || item === null) return null
  const row = item as Record<string, unknown>
  const artifactId = asString(row.artifact_id)
  const virtualPath = asString(row.virtual_path)
  const changeKind = asString(row.change_kind)
  const bytes = asNumber(row.bytes)
  const sha256 = asString(row.sha256)
  const createdAt = asString(row.created_at)
  if (!artifactId || !virtualPath || !changeKind || bytes === null || !sha256 || !createdAt) return null
  return {
    artifact_id: artifactId,
    virtual_path: virtualPath,
    change_kind: changeKind,
    bytes,
    sha256,
    created_at: createdAt,
    expires_at: asString(row.expires_at),
  }
}

/**
 * 舞台「产物登记」（P2c-3）：`GET /runs/{run_id}/artifacts`（**只读元数据**）。
 *
 * 纪律：无 run ⇒ 空态（不请求、不摆假面板）；读失败按四态渲染（可重试 / 不可重试）；
 * 响应逐条过白名单投影（服务端已不含内容与 tenant_id）。
 */
export function useRunArtifacts(runId: string | undefined, reloadToken = 0): RunArtifactsState {
  const [items, setItems] = useState<RunArtifact[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<RunErrorShape | null>(null)
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
        const loaded = await listRunArtifacts(runId)
        if (cancelled) return
        const raw = Array.isArray(loaded.items) ? loaded.items : []
        setItems(raw.map(artifactView).filter((item): item is RunArtifact => item !== null))
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
  }, [runId, reloadToken, nonce])

  return { items, loading, error, reload }
}