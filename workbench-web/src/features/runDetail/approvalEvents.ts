/**
 * 审批决议事件（S1「三处一致」的前端失效机制）。
 *
 * 背景：视图槽常驻（D19）⇒ 对话页、右侧舞台与运行详情可能**同时在挂载状态**。
 * 任一处决议后，其余各处必须刷新为**服务端权威态**（不做乐观更新、不做本地合并）。
 * 本模块只广播「某运行的某个审批刚被决议」这一事实，订阅方各自重取。
 */
export interface ApprovalDecidedEvent {
  runId: string
  approvalId: string
}

type Listener = (event: ApprovalDecidedEvent) => void

const listeners = new Set<Listener>()

/** 决议成功（服务端已确认）后广播；失败不广播。 */
export function publishApprovalDecided(runId: string, approvalId: string): void {
  for (const listener of [...listeners]) listener({ runId, approvalId })
}

export function subscribeApprovalDecided(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}