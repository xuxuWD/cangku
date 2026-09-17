import type { ReactNode } from 'react'

/** 列表分页条：契约要求列表必须分页（`limit` 1–200 + `offset` + `total`）。 */
export function Pagination({
  total,
  limit,
  offset,
  loading,
  onPrev,
  onNext,
}: {
  total: number
  limit: number
  offset: number
  loading: boolean
  onPrev: () => void
  onNext: () => void
}) {
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + limit, total)
  return (
    <div className="history-pagination">
      <button className="button" type="button" disabled={loading || offset <= 0} onClick={onPrev}>上一页</button>
      <span>共 {total} 条（第 {start}–{end} 条）</span>
      <button className="button" type="button" disabled={loading || offset + limit >= total} onClick={onNext}>下一页</button>
    </div>
  )
}

/** 提示条：失败 / 中性说明（不承载权限判定结论）；`action` 与正文并排（沿用既有 notice 结构）。 */
export function CrmNotice({ tone = 'info', title, children, action }: { tone?: 'info' | 'error' | 'success'; title: string; children?: ReactNode; action?: ReactNode }) {
  const className = tone === 'error' ? 'notice notice-error' : tone === 'success' ? 'notice notice-success' : 'notice'
  return (
    <div className={className} role={tone === 'error' ? 'alert' : 'status'}>
      <div><strong>{title}</strong>{children}</div>
      {action}
    </div>
  )
}