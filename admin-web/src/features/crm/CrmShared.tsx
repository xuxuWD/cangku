import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { listAccounts } from './api'

/** account_id → 客户名 映射。 */
export type AccountNames = Record<string, string>

/**
 * 客户名映射：页面挂载时取一次客户列表（limit 200）构建 account_id → name。
 * 名称只是可读性辅助：请求失败**静默降级**（回落显示 ID），不弹错、不阻塞主数据加载。
 */
export function useAccountNames(): AccountNames {
  const [names, setNames] = useState<AccountNames>({})

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const page = await listAccounts({ status: '', limit: 200, offset: 0 })
        if (!active) return
        const next: AccountNames = {}
        for (const account of Array.isArray(page.items) ? page.items : []) {
          if (account?.account_id && account.name) next[account.account_id] = account.name
        }
        setNames(next)
      } catch {
        // 名称读取失败不影响页面：保持空映射，界面回落显示 account_id。
      }
    })()
    return () => { active = false }
  }, [])

  return names
}

/** 客户展示：优先客户名，映射缺失回落 account_id（不报错）；ID 始终保留在 title 便于核对。 */
export function AccountName({ accountId, names }: { accountId: string | null | undefined; names: AccountNames }) {
  if (!accountId) return <>—</>
  return <span title={accountId}>{names[accountId] ?? accountId}</span>
}

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
      <button className="btn btn--secondary btn--sm" type="button" disabled={loading || offset <= 0} onClick={onPrev}>上一页</button>
      <span>共 {total} 条（第 {start}–{end} 条）</span>
      <button className="btn btn--secondary btn--sm" type="button" disabled={loading || offset + limit >= total} onClick={onNext}>下一页</button>
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