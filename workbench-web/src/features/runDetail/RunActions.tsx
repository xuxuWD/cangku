/**
 * S4 运行干预：暂停 / 恢复 / 取消。运行详情页与舞台共用同一个组件（同源、同文案口径）。
 *
 * **来源**：由 `admin-web/src/features/runDetail/RunActions.tsx` 合并移植（行为等价）。
 * 呈现层从手写 CSS + **`window.confirm`**，换成 **AntD `Button` / `Alert` + 项目组件库的 `DangerConfirm`**
 * —— 基座对「危险操作二次确认」有统一组件（`DangerConfirm`），不该自造一个原生弹窗。
 *
 * **纪律（原实现，保留）**：
 * - **服务端权威**：成功后只重取（`onRefresh`），**不做本地乐观更新**；按钮分支按**服务端返回的运行状态**；
 * - **取消是危险操作**：先二次确认（**不可撤销、已完成步骤不回滚**），确认后才发请求；
 * - **不做「隐藏即权限」**：`canOperate` 只是体验层预判，服务端仍独立判定（越权以 `404` 收敛），
 *   失败时把服务端结论**原样展示**在操作区旁，不静默吞掉；
 * - **无假按钮**：运行处于终态（已完成 / 失败 / 已取消）时不渲染任何干预按钮。
 */
import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { DangerConfirm } from '../../components'
import { asRunError } from './state'
import { cancelRun, pauseRun, resumeRun } from './services/runService'
import type { RunErrorShape } from './types'

// 暂停 / 取消的原因由前端给定业务口径文案（服务端要求 1..500 字且非空），
// 它会进入运行事件时间线，因此**如实描述来源**，不写「系统自动」。
const PAUSE_REASON = '在工作台上手动暂停'
const CANCEL_REASON = '在工作台上手动取消'

const CANCEL_TITLE = '取消运行'
const CANCEL_DESCRIPTION = '取消后该运行会立即停止，已完成的步骤不会撤销，也无法恢复。确定取消吗？'
const CANCEL_ACK = '我明白：取消后已完成的步骤不会撤销，也无法恢复'

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
  /** 体验层预判（创建人 / CEO / 超管）；**服务端仍是权威**。 */
  canOperate?: boolean
  /** 干预成功后重取权威态（概览 / 事件 / 审批）；**失败不调用**。 */
  onRefresh?: () => void | Promise<void>
  /** 成功提示（宿主页面的 Toast）；**失败提示固定就地展示在本组件内**（不依赖宿主）。 */
  onNotice?: (message: string) => void
}) {
  const [busy, setBusy] = useState<ActionKind | null>(null)
  const [error, setError] = useState<RunErrorShape | null>(null)
  const [confirming, setConfirming] = useState(false)

  if (!canOperate || !status || isTerminalRunStatus(status)) return null

  const paused = status === 'paused'

  const run = async (kind: ActionKind) => {
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
    <div>
      <Space>
        {paused ? (
          <Button disabled={busy !== null} onClick={() => void run('resume')}>
            {busy === 'resume' ? BUSY_LABELS.resume : '恢复运行'}
          </Button>
        ) : (
          <Button disabled={busy !== null} onClick={() => void run('pause')}>
            {busy === 'pause' ? BUSY_LABELS.pause : '暂停运行'}
          </Button>
        )}
        <Button danger disabled={busy !== null} onClick={() => setConfirming(true)}>
          {busy === 'cancel' ? BUSY_LABELS.cancel : '取消运行'}
        </Button>
      </Space>

      {error && (
        <Alert
          style={{ marginTop: 8 }}
          type="error"
          showIcon
          message="操作未生效"
          description={error.message}
          // 与原文一致：只有**可重试**的失败才给「知道了」；不可重试的（如无权限）让用户去看原因
          action={
            error.retryable ? (
              <Button size="small" onClick={() => setError(null)}>
                知道了
              </Button>
            ) : undefined
          }
        />
      )}

      <DangerConfirm
        open={confirming}
        title={CANCEL_TITLE}
        description={CANCEL_DESCRIPTION}
        acknowledgeText={CANCEL_ACK}
        confirmText="取消运行"
        onCancel={() => setConfirming(false)}
        onConfirm={async () => {
          setConfirming(false)
          await run('cancel')
        }}
      />
    </div>
  )
}
