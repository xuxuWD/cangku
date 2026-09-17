import { changeKindLabel } from '../runDetail/types'
import type { RunArtifactsState } from './useRunArtifacts'

/**
 * 舞台「产物登记」面板（P2c-3 §2.7）：只读元数据（虚拟路径 / 变更类型 / 字节 / sha256 / 时间）。
 *
 * 纪律（§2.5 / §2.7）：
 * - **四态齐备**：加载 / 空 / 错误（可重试）/ 无运行（不渲染——无数据不摆假面板）；
 * - **只渲染白名单字段**（`useRunArtifacts` 已逐条投影），不渲染内容 / `tenant_id` / 宿主路径；
 * - **保留期如实告知**：面板只展示服务端返回的条目（过期条目服务端已不再返回）。
 */
export function ArtifactPanel({
  runId,
  artifacts,
  onOpenRunDetail,
}: {
  runId?: string
  artifacts: RunArtifactsState
  onOpenRunDetail?: (runId: string) => void
}) {
  if (!runId) return null
  const { items, loading, error } = artifacts

  return (
    <section className="history-panel stage-panel" aria-label="产物登记">
      <div className="panel-header">
        <h2>产物登记</h2>
        {items.length > 0 && <span>{items.length} 项</span>}
      </div>

      {loading && items.length === 0 && (
        <div className="loading-state" role="status">
          <span className="loading-dot" />
          正在加载产物登记…
        </div>
      )}

      {!loading && error && (
        <div className="notice notice-error" role="alert">
          <div>
            <strong>产物登记加载失败</strong>
            <p>{error.message}</p>
          </div>
          {error.retryable && (
            <button className="text-action" type="button" onClick={artifacts.reload}>
              重新尝试
            </button>
          )}
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="empty-state">
          <strong>本次运行没有登记产物</strong>
          <span>只有真正写文件的工具（新建 / 覆盖 / 删除）才会登记产物。</span>
        </div>
      )}

      {!error && items.length > 0 && (
        <div className="panel-body">
          <ul className="artifact-list">
            {items.map((item) => (
              <li className="artifact-row" key={item.artifact_id}>
                <span className="artifact-row__path">{item.virtual_path}</span>
                <span className="artifact-row__kind">{changeKindLabel(item.change_kind)}</span>
                <span className="artifact-row__bytes">{item.bytes} B</span>
                <span className="artifact-row__sha" title={item.sha256}>
                  {item.sha256.slice(0, 19)}…
                </span>
              </li>
            ))}
          </ul>
          <p className="stage-hint">只登记元数据（虚拟路径 / 类型 / 字节 / 摘要），不含文件内容；过期后不再返回。</p>
        </div>
      )}

      {onOpenRunDetail && (
        <div className="panel-body">
          <button className="text-action" type="button" onClick={() => onOpenRunDetail(runId)}>
            在运行详情中打开
          </button>
        </div>
      )}
    </section>
  )
}