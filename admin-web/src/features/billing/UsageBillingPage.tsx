import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { getUsageSummary } from './api'
import { asBillingError, formatCents, initialBillingState } from './state'
import type { BillingState } from './types'

export function UsageBillingPage({ onNavigate }: { onNavigate?: (view: AppView) => void }) {
  const [state, setState] = useState<BillingState>(initialBillingState)

  const load = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: null }))
    try {
      const usage = await getUsageSummary()
      setState({ usage, loading: false, error: null })
    } catch (error) {
      setState({ usage: null, loading: false, error: asBillingError(error) })
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const usage = state.usage
  const isEmpty = usage !== null && usage.units === 0 && usage.cost_cents === 0
  const notRegistered = state.error?.status === 404

  return <AppShell activeView="billing" onNavigate={onNavigate}>
    <main className="main-content content-history usage-billing">
      <div className="page-head">
        <div>
          <div className="eyebrow">经营与成本</div>
          <h1 className="page-title">用量与费用</h1>
          <p className="page-desc">本租户的累计用量与累计费用，数据来自追加式用量账本（含冲正记录）。本页只读，不提供冲正、额度调整或计费口径变更入口。</p>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => void load()}>刷新</button></div>
      </div>

      {state.loading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载用量与费用…</div>}

      {!state.loading && notRegistered && <div className="notice" role="status">
        <div>
          <strong>本租户尚未登记用量账本</strong>
          <p>商业化模块里还没有本租户的登记记录，因此没有可展示的用量与费用。这通常说明当前环境尚未初始化商业化数据，<b>不是故障</b>；已登记租户即使没有任何计量事件也会返回 0。</p>
        </div>
      </div>}

      {!state.loading && state.error && !notRegistered && <div className="notice notice-error" role="alert">
        <div>
          <strong>{state.error.status === 403 ? '暂时无法查看用量与费用' : '用量与费用加载失败'}</strong>
          <p>{state.error.message}</p>
        </div>
        {state.error.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
      </div>}

      {!state.loading && usage && <section className="history-panel usage-billing__panel" aria-label="用量与费用汇总">
        <div className="panel-header"><h2>租户累计</h2><span>{usage.tenant_id}</span></div>
        <div className="usage-billing__grid">
          <div className="usage-billing__item">
            <span className="usage-billing__label">累计用量</span>
            <b className="usage-billing__value">{usage.units}</b>
            <small>账本记录的原始单位，页面不做业务含义解释。</small>
          </div>
          <div className="usage-billing__item">
            <span className="usage-billing__label">累计费用</span>
            <b className="usage-billing__value">{formatCents(usage.cost_cents)}</b>
            <small>账本以整数分记账；发生过冲正时累计可能为负。</small>
          </div>
        </div>
        {isEmpty && <div className="empty-state"><strong>本期还没有用量记录</strong><span>有计量事件写入账本后，这里会显示累计用量与费用。</span></div>}
      </section>}

      <p className="usage-billing__footnote">模型清单尚未实现：模型由配置注入（内容侧与规划侧两套），没有实体表与接口，属下一期立项。按时间 / 模型 / 任务的花费维度、预算与告警、冲正入口同样未做。</p>
    </main>
  </AppShell>
}
