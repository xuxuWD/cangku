import { useState } from 'react'
import { cancelRun, pauseRun, resumeRun } from './api'
import { asRunError } from './state'
import type { RunErrorShape } from './types'

/**
 * S4 运行干预：暂停 / 恢复 / 取消。运行详情页与对话右栏共用同一个组件（同源、同文案口径）。
 *
 * 纪律（规格 §S4）：
 * - **服务端权威**：调用成功后只重取概览 / 事件 / 审批（`onRefresh`），**不做本地乐观更新**；
 *   按钮的显示与隐藏按「服务端返回的运行状态」分支，而不是按点击后的本地猜测。
 * - **取消是危险操作**：先二次确认（不可撤销、已完成步骤不回滚），确认后才发请求。
 * - **不做「隐藏即权限」**：`canOperate` 只是体验层的预判，服务端仍会独立判定（越权以 404 收敛），
 *   失败时把服务端的结论原样展示在按钮旁边，不静默吞掉。
 * - **无假按钮**：运行处于终态（已完成 / 失败 / 已取消）时不渲染任何干预按钮——终态的运行没有可干预项。
 */

// 暂停 / 取消的原因由前端给定业务口径文案（服务端要求 1..500 字且非空），
// 它会进入运行事件时间线，因此**如实描述来源**，不写「系统自动」。
const PAUSE_REASON = '在工作台上手动暂停'
const CANCEL_REASON = '在工作台上手动取消'

const CANCEL_CONFIRM = '取消后该运行会立即停止，已完成的步骤不会撤销，也无法恢复。确定取消吗？'

type ActionKind = 'pause' | 'resume' | 'cancel'

const BUSY_LABELS: Record<ActionKind, string> = {
  pause: '正在暂停…',
  resume: '正在恢复…',
  cancel: '正在取消…',
}

const DONE_NOTICES: Record<ActionKind, string> = {
  pause: '已暂停该运行',
  resume: '已恢复该运行',
  cancel: '已取消该运行',
}

/** 终态 = 服务端不会再推进；此时不提供干预入口。 */
export function isTerminalRunStatus(status: string | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}

export function RunActions({
  runId,
  status,
  canOperate = true,
  onRefresh,
  onNotice,
}: {
  runId: string
  status: string | undefined
  /** 体验层预判（创建人 / CEO / 超管）；服务端仍是权威。 */
  canOperate?: boolean
  /** 干预成功后重取权威态（概览 / 事件 / 审批）；失败不调用。 */
  onRefresh?: () => void | Promise<void>
  /** 成功提示（宿主页面的 Toast）；失败提示固定就地展示在本组件内。 */
  onNotice?: (message: string) => void
}) {
  const [busy, setBusy] = useState<ActionKind | null>(null)
  const [error, setError] = useState<RunErrorShape | null>(null)

  if (!canOperate || !status || isTerminalRunStatus(status)) return null

  const paused = status === 'paused'

  const run = async (kind: ActionKind) => {
    if (kind === 'cancel' && !window.confirm(CANCEL_CONFIRM)) return
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'pause') await pauseRun(runId, PAUSE_REASON)
      else if (kind === 'resume') await resumeRun(runId)
      else await cancelRun(runId, CANCEL_REASON)
      await onRefresh?.()
      onNotice?.(DONE_NOTICES[kind])
    } catch (cause) {
      setError(asRunError(cause))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="run-actions">
      <div className="actions">
        {paused ? (
          <button className="btn btn--secondary" type="button" disabled={busy !== null} onClick={() => void run('resume')}>
            {busy === 'resume' ? BUSY_LABELS.resume : '恢复运行'}
          </button>
        ) : (
          <button className="btn btn--secondary" type="button" disabled={busy !== null} onClick={() => void run('pause')}>
            {busy === 'pause' ? BUSY_LABELS.pause : '暂停运行'}
          </button>
        )}
        <button className="btn btn--danger" type="button" disabled={busy !== null} onClick={() => void run('cancel')}>
          {busy === 'cancel' ? BUSY_LABELS.cancel : '取消运行'}
        </button>
      </div>
      {error && (
        <div className="notice notice-error" role="alert">
          <div>
            <strong>操作未生效</strong>
            <p>{error.message}</p>
          </div>
          {error.retryable && (
            <button className="text-action" type="button" onClick={() => setError(null)}>
              知道了
            </button>
          )}
        </div>
      )}
    </div>
  )
}