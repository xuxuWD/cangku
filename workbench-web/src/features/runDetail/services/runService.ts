/**
 * 「运行详情 / 运行干预 / 验收决议 / 沉淀」适配层 —— 本模块**唯一**的接线点。
 *
 * **来源**：由 `admin-web/src/features/runDetail/api.ts` 合并移植（13 个函数，契约未改）。
 *
 * ⚠️ **移植时改动的两处**（与 `features/conversation/services/conversationService.ts` 同一口径）：
 *  ① **认证模型**：admin-web 的 `X-Tenant-Id` / `X-User-Id` / `X-User-Role` 自报头 → 基座的
 *     **会话令牌**（合并后只能留一套认证）；
 *  ② **错误对象**：改抛带状态码的 `RunError`（`asRunError` 据此分流可重试性）。
 *
 * **两类操作的错误口径不同，必须分开**（原实现的设计，保留）：
 *  - **读取类**（`getRunMetrics` / `listRunEvents` / …）用 `runErrorFromStatus`；
 *  - **干预类**（暂停 / 恢复 / 取消 / 验收决议 / 沉淀）用 `runActionErrorFromStatus` —— 它们的 409
 *    是「当前状态不允许」、422 是「入参不合法」，服务端会带中文原因，**优先原样展示**。
 *
 * 契约：`docs/api-contract.md`「运行干预」「运行验收决议（S2 · 人工验收）」「运行沉淀（S2 · 存成任务）」。
 */
import { ApiError, request } from '../../../api/client'
import type { ServiceFailure } from '../../../utils/serviceKit'
import { RunError, runActionErrorFromStatus, runErrorFromStatus } from '../state'
import type {
  RunAcceptanceDecision,
  RunAcceptanceDecisionKind,
  RunAcceptanceDecisionList,
  RunActionAck,
  RunApprovalDecision,
  RunApprovalList,
  RunArtifactList,
  RunEvent,
  RunMetrics,
  RunPromotionResult,
  RunTask,
} from '../types'

const API = '/api/v1'

/** 读取类失败 → `RunError`（固定文案，403 优先服务端友好文案）。 */
function toRunError(error: unknown): never {
  if (error instanceof ApiError) {
    // ⚠️ 用 `error.detail`（**只在服务端真写了原因时才有值**），不用 `error.message`
    // —— 后者是"服务端 detail 或基座兜底文案"二选一，分不出是哪个
    const shape = runErrorFromStatus(error.status, error.status === 403 ? error.detail : null)
    throw new RunError(shape.message, failureOf(error), error.status)
  }
  throw error
}

/** 干预类失败 → `RunError`（409 / 422 优先原样展示服务端原因）。 */
function toRunActionError(error: unknown): never {
  if (error instanceof ApiError) {
    // 干预类：409/422 **优先服务端原因**（没有才用本模块兜底文案）
    const shape = runActionErrorFromStatus(error.status, error.detail)
    throw new RunError(shape.message, failureOf(error), error.status)
  }
  throw error
}

function failureOf(error: ApiError): ServiceFailure {
  return error.failure === 'forbidden' ? 'forbidden' : 'failed'
}

async function wrapRead<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise
  } catch (error) {
    toRunError(error)
  }
}

async function wrapAction<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise
  } catch (error) {
    toRunActionError(error)
  }
}

/* ------------------------------------------------------------------ 读取 */

export function getRunMetrics(runId: string): Promise<RunMetrics> {
  return wrapRead(request<RunMetrics>(`${API}/runs/${encodeURIComponent(runId)}/metrics`))
}

export function getTask(taskId: string): Promise<RunTask> {
  return wrapRead(request<RunTask>(`${API}/tasks/${encodeURIComponent(taskId)}`))
}

export function listRunEvents(runId: string): Promise<RunEvent[]> {
  return wrapRead(request<RunEvent[]>(`${API}/runs/${encodeURIComponent(runId)}/events`))
}

export function listRunApprovals(runId: string): Promise<RunApprovalList> {
  return wrapRead(request<RunApprovalList>(`${API}/runs/${encodeURIComponent(runId)}/approvals`))
}

/** P2c-3：产物登记只读列表（**只含元数据**；保留期已到的条目服务端不再返回）。 */
export function listRunArtifacts(runId: string): Promise<RunArtifactList> {
  return wrapRead(request<RunArtifactList>(`${API}/runs/${encodeURIComponent(runId)}/artifacts`))
}

export function listRunAcceptanceDecisions(runId: string): Promise<RunAcceptanceDecisionList> {
  return wrapRead(
    request<RunAcceptanceDecisionList>(
      `${API}/runs/${encodeURIComponent(runId)}/acceptance/decisions`,
    ),
  )
}

/* ------------------------------------------------------------------ 审批决议 */

export function decideRunApproval(
  runId: string,
  approvalId: string,
  approved: boolean,
): Promise<RunApprovalDecision> {
  return wrapAction(
    request<RunApprovalDecision>(
      `${API}/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/approval`,
      { method: 'POST', body: { approved } },
    ),
  )
}

/* ------------------------------------------------------------------ 运行干预（S4） */

/**
 * 暂停 / 恢复 / 取消。
 *
 * 三端点都是 POST，服务端判定操作权（任务创建人 / CEO / 超管；越权以 `404` 收敛 —— **不泄露运行是否存在**）。
 * 暂停与取消的 `reason` 是**必填**（1..500 字，服务端 `extra=forbid`），由调用方给定业务口径文案。
 */
export function pauseRun(runId: string, reason: string): Promise<RunActionAck> {
  return wrapAction(
    request<RunActionAck>(`${API}/runs/${encodeURIComponent(runId)}/pause`, {
      method: 'POST',
      body: { reason },
    }),
  )
}

export function resumeRun(runId: string): Promise<RunActionAck> {
  return wrapAction(
    request<RunActionAck>(`${API}/runs/${encodeURIComponent(runId)}/resume`, { method: 'POST' }),
  )
}

export function cancelRun(runId: string, reason: string): Promise<RunActionAck> {
  return wrapAction(
    request<RunActionAck>(`${API}/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
      body: { reason },
    }),
  )
}

/* ------------------------------------------------------------------ 验收决议（S2） */

/**
 * 人工验收决议：**只记录「人怎么判的」**，不改运行状态、不触发重跑；
 * 同幂等键重放返回既有决议（`created: false`）。
 */
export function decideRunAcceptance(
  runId: string,
  payload: { decision: RunAcceptanceDecisionKind; reason?: string; idempotencyKey: string },
): Promise<RunAcceptanceDecision & { run_id: string; created: boolean }> {
  return wrapAction(
    request<RunAcceptanceDecision & { run_id: string; created: boolean }>(
      `${API}/runs/${encodeURIComponent(runId)}/acceptance/decisions`,
      {
        method: 'POST',
        // 与后端受控字段逐字一致：只发这三个键
        body: {
          decision: payload.decision,
          reason: payload.reason ?? '',
          idempotency_key: payload.idempotencyKey,
        },
      },
    ),
  )
}

/** 每次决议生成一个新幂等键：同一次点击重放由服务端返回既有决议，不产生第二行。 */
export function newAcceptanceIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `acceptance-${crypto.randomUUID()}`
  }
  return `acceptance-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/* ------------------------------------------------------------------ 沉淀（S2） */

/**
 * 把**已确认完成**的这次运行存成一个可再跑的任务。
 *
 * 幂等由**服务端**保证（一个运行只沉淀一次）：重复提交返回既有任务且 `created: false`
 * ⇒ 前端因此**不需要幂等键**。
 */
export function promoteRunToTask(runId: string, title: string): Promise<RunPromotionResult> {
  return wrapAction(
    request<RunPromotionResult>(`${API}/runs/${encodeURIComponent(runId)}/acceptance/tasks`, {
      method: 'POST',
      body: { title },
    }),
  )
}
