/**
 * 「对话」适配层 —— 本模块**唯一**的接线点。
 *
 * **来源**：由 `admin-web/src/features/conversation/api.ts` 合并移植（13 个函数，契约未改）。
 *
 * ⚠️ **移植时改动的两处（都是"合并到基座"的必然结果，如实登记）**：
 *  ① **认证模型换了**。admin-web 用 `X-Tenant-Id` / `X-User-Id` / `X-User-Role` 三个自定义头
 *     自报身份；基座用**会话令牌**（`Authorization: Bearer`，见 `api/client.ts`，且它是全前端
 *     **唯一**发 HTTP 的地方）。合并后必须**只有一套认证**，故这里改用基座请求层。
 *  ② **错误对象换了**。原实现自带 `conversationErrorFromStatus`；基座请求层已经把状态码映射成
 *     中文固定文案并做过 sanitize。这里保留本模块**更具体**的文案（如 409「会话已归档」），
 *     查不到时回落到请求层给的文案 —— 口径同 `features/billing/services/billingService.ts`。
 *
 * 契约：`docs/api-contract.md`「对话式 AI 员工平台（P1）」；后端见 `app/main.py` / `app/conversation/`。
 */
import { ApiError, request, requestRaw } from '../../../api/client'
import { ServiceError, type ServiceFailure } from '../../../utils/serviceKit'
import { conversationMessageFor } from '../state'
import {
  EXPORT_MAX_PAGES,
  EXPORT_PAGE_SIZE,
} from '../types'
import type {
  Conversation,
  ConversationDeletionResult,
  ConversationDetail,
  ConversationExportPage,
  ConversationList,
  ConversationMemberGrant,
  ConversationMemberList,
  ConversationMode,
  MemberPermission,
  MessageCreateResponse,
  RunAcceptance,
} from '../types'

const API = '/api/v1'

/** 适配层错误：带**状态码**，供页面按状态分流（如 409 给"已归档"的专门提示）。 */
export class ConversationError extends ServiceError {
  readonly status: number

  constructor(message: string, failure: ServiceFailure, status: number) {
    super(message, failure)
    this.name = 'ConversationError'
    this.status = status
  }
}

/** 请求层失败 → 本层失败。**非请求层错误原样抛出**（不吞异常、不改写成"服务不可用"）。 */
function toConversationError(error: unknown): never {
  if (error instanceof ApiError) {
    // 文案表在 `state.ts`（**唯一来源**）：页面与流读端用的是同一份，避免同一状态码两种说法
    const message = conversationMessageFor(error.status, error.detail)
    throw new ConversationError(message, error.failure === 'forbidden' ? 'forbidden' : 'failed', error.status)
  }
  throw error
}

/* ------------------------------------------------------------------ 会话 */

export function listConversations(params: {
  status?: string
  limit: number
  offset: number
}): Promise<ConversationList> {
  return wrap(
    request<ConversationList>(`${API}/conversations`, {
      query: { status: params.status, limit: params.limit, offset: params.offset },
    }),
  )
}

export function getConversation(
  conversationId: string,
  params: { limit: number; offset: number },
): Promise<ConversationDetail> {
  return wrap(
    request<ConversationDetail>(`${API}/conversations/${encodeURIComponent(conversationId)}`, {
      query: { limit: params.limit, offset: params.offset },
    }),
  )
}

/** 新建会话。`agent_key` 缺省表示用默认员工；**不给未知字段**（后端 `extra=forbid`）。 */
export function createConversation(
  payload: { agent_key?: string; title?: string } = {},
): Promise<Conversation> {
  return wrap(
    request<Conversation>(`${API}/conversations`, {
      method: 'POST',
      // 与后端受控字段逐字一致：只发这两个键
      body: { agent_key: payload.agent_key, title: payload.title ?? '' },
    }),
  )
}

export function archiveConversation(conversationId: string): Promise<Conversation> {
  return wrap(
    request<Conversation>(`${API}/conversations/${encodeURIComponent(conversationId)}/archive`, {
      method: 'POST',
    }),
  )
}

/** 改每会话模式（仅本人；他人 / 跨租户 404、归档 409、非法取值 422）。 */
export function setConversationMode(
  conversationId: string,
  mode: ConversationMode,
): Promise<Conversation> {
  return wrap(
    request<Conversation>(`${API}/conversations/${encodeURIComponent(conversationId)}/mode`, {
      method: 'POST',
      body: { mode },
    }),
  )
}

/** **物理删除**本人会话的内容行（同步、幂等）：删除后列表 / 详情 / 流 / 发消息一律 404。 */
export function deleteConversation(conversationId: string): Promise<ConversationDeletionResult> {
  return wrap(
    request<ConversationDeletionResult>(
      `${API}/conversations/${encodeURIComponent(conversationId)}/delete`,
      { method: 'POST' },
    ),
  )
}

/* ------------------------------------------------------------------ 消息 */

/**
 * 发一条消息（**普通端点**）。响应直接带回 reply（含 `stub` 标注），不需要轮询。
 *
 * `Idempotency-Key`：带键 ⇒ 触发真实执行 + 幂等（201 已执行 / 202 待批）；
 * 不带键 ⇒ 后端沿用既有 `stub=true` 桩回复。键由调用方生成（同一键重放返回既有结果）。
 */
export function sendConversationMessage(
  conversationId: string,
  content: string,
  idempotencyKey?: string,
): Promise<MessageCreateResponse> {
  return wrap(
    request<MessageCreateResponse>(
      `${API}/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: 'POST',
        body: { content },
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
      },
    ),
  )
}

/* ------------------------------------------------------------------ 实时流（P2c-1） */

/**
 * 打开 SSE 读端（`GET .../stream`）。
 *
 * **不用 `EventSource`**：认证走 `Authorization` 头（`EventSource` 不支持自定义头），
 * 且续播需要自定义 `Last-Event-ID` —— 只有 `fetch` + 读流能同时满足。
 *
 * 起点：服务端取 `max(Last-Event-ID, after_seq)`，缺省 0（从第一帧补发）；
 * 这里只在续播（`since > 0`）时发头，首连不带头（即 `after_seq` 缺省 = 0）。
 *
 * 返回原始 `Response`（**不解析**）—— 帧解析在调用方（`stream.ts`）。
 */
export async function openConversationStream(params: {
  conversationId: string
  runId?: string
  since: number
  signal: AbortSignal
}): Promise<Response> {
  try {
    return await requestRaw(`${API}/conversations/${encodeURIComponent(params.conversationId)}/stream`, {
      query: { run_id: params.runId },
      signal: params.signal,
      accept: 'text/event-stream',
      // 长连接：**不设超时**，且中止转发保留到调用方中止为止（否则流停不下来）
      streaming: true,
      headers: params.since > 0 ? { 'Last-Event-ID': String(params.since) } : undefined,
    })
  } catch (error) {
    toConversationError(error)
  }
}

export interface StreamSendResult {
  body: MessageCreateResponse
  /** 本次运行 id（响应头 `X-Stream-Run-Id`；无运行时为 `null`）—— 运行面板据此加载概览与审批。 */
  runId: string | null
}

/**
 * 发消息（**实时流路径**）：请求体 / 头 / 响应体与普通端点逐字一致，
 * 唯一新增是响应头 `X-Stream-Run-Id`。带幂等键 ⇒ 真实执行并写帧。
 */
export async function sendConversationMessageStream(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<StreamSendResult> {
  try {
    const response = await requestRaw(
      `${API}/conversations/${encodeURIComponent(conversationId)}/messages:stream`,
      {
        method: 'POST',
        body: { content },
        accept: 'application/json',
        headers: { 'Idempotency-Key': idempotencyKey },
      },
    )
    const body = (await response.json()) as MessageCreateResponse
    // 响应头优先，缺省回落到响应体字段（与后端契约一致）
    const runId = response.headers?.get?.('X-Stream-Run-Id') ?? body.run_id ?? null
    return { body, runId }
  } catch (error) {
    toConversationError(error)
  }
}

/* ------------------------------------------------------------------ 导出 */

/** 取一页导出数据（页单位 = 会话；服务端 500/页、条目上限 5 万）。 */
export function exportMyConversationsPage(offset: number): Promise<ConversationExportPage> {
  return wrap(
    request<ConversationExportPage>(`${API}/conversations/exports/mine`, {
      query: { limit: EXPORT_PAGE_SIZE, offset },
    }),
  )
}

export interface ConversationExportBundle {
  pages: ConversationExportPage[]
  /** 客户端合并是否在服务端上限前停止（页数上限，或服务端如实告知截断）。 */
  truncated: boolean
}

/**
 * 导出本人全部会话数据：**逐页拉取并合并**（上限 = 服务端口径 100 页 × 500）。
 * 到顶或服务端 `truncated` 即停止 —— 界面据 `truncated` **如实告知**未取全，**不静默截断**。
 */
export async function exportMyConversations(): Promise<ConversationExportBundle> {
  const pages: ConversationExportPage[] = []
  let offset = 0
  let fetched = 0
  let truncated = false
  for (let page = 0; page < EXPORT_MAX_PAGES; page += 1) {
    const data = await exportMyConversationsPage(offset)
    pages.push(data)
    fetched += Array.isArray(data.conversations) ? data.conversations.length : 0
    offset += EXPORT_PAGE_SIZE
    if (data.truncated) {
      truncated = true
      break
    }
    // 取全即停；空页也停（防止服务端异常导致死循环）。
    if (fetched >= (data.total_conversations ?? 0) || (data.conversations ?? []).length === 0) break
  }
  return { pages, truncated }
}

/* ------------------------------------------------------------------ 运行结构判定 */

/** 运行结构判定（纯读；服务端**不调模型、不改运行状态**）。 */
export function getRunAcceptance(runId: string): Promise<RunAcceptance> {
  return wrap(request<RunAcceptance>(`${API}/runs/${encodeURIComponent(runId)}/acceptance`))
}

/* ------------------------------------------------------------------ 会话协作（P2c-6） */

/** 参与者名单（本人或成员可见；他人 / 跨租户 404）。 */
export function listConversationMembers(conversationId: string): Promise<ConversationMemberList> {
  return wrap(
    request<ConversationMemberList>(
      `${API}/conversations/${encodeURIComponent(conversationId)}/members`,
    ),
  )
}

/** 添加 / 覆盖成员（仅会话本人）：非法成员 / 非法权限档 422、归档 409、非本人 404。 */
export function addConversationMember(
  conversationId: string,
  memberId: string,
  permission: MemberPermission,
): Promise<ConversationMemberGrant> {
  return wrap(
    request<ConversationMemberGrant>(
      `${API}/conversations/${encodeURIComponent(conversationId)}/members`,
      {
        method: 'POST',
        // 与后端受控枚举逐字一致（只发这两个键，未知字段会被 422 拒绝）
        body: { member_id: memberId, permission },
      },
    ),
  )
}

/**
 * 撤销成员（仅会话本人）：成功 `204` **无响应体**；复删 / 目标不是成员同样 `204`（幂等）。
 * **已读内容不可撤回** —— 撤销只影响对方**新**的读取 / 发言请求，不做"收回"语义。
 */
export async function removeConversationMember(
  conversationId: string,
  memberId: string,
): Promise<void> {
  try {
    // 请求层对 204 直接返回 `undefined`，**刻意不解析 JSON**（解析会把成功当失败）
    await request<void>(
      `${API}/conversations/${encodeURIComponent(conversationId)}/members/${encodeURIComponent(memberId)}`,
      { method: 'DELETE' },
    )
  } catch (error) {
    toConversationError(error)
  }
}

/** 统一的失败映射出口：`await` 到 `ApiError` 就转成本层错误，其余原样抛。 */
async function wrap<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise
  } catch (error) {
    toConversationError(error)
  }
}
