/**
 * 「对话」模块的**文案表与错误形状**（模块级唯一来源）。
 *
 * **来源**：由 `admin-web/src/features/conversation/state.ts` 合并移植。
 *
 * ⚠️ **为什么文案表在这里、而不是在服务层**：`conversationService` 抛的是 `ConversationError`（一个 Error），
 * 而页面与 `useRunStream` 需要的是 **值对象** `ConversationErrorShape`（可存进 state、可渲染）。
 * 两者必须用**同一份文案**，否则会出现"同一状态码两种说法"。⇒ 表放在这里，
 * 服务层 import 它，两边只有一份。
 */
import type { ConversationErrorShape, ConversationState } from './types'

export const DEFAULT_CONVERSATION_ERROR = '对话服务暂时不可用，请检查网络后重新尝试。'

/** 按状态码的固定中文文案（**不透出堆栈 / URL / 原始异常文本**）。 */
export const CONVERSATION_FIXED_MESSAGES: Record<number, string> = {
  401: '登录态已失效，请重新登录。',
  403: '当前岗位不能使用对话入口。',
  404: '会话不存在，或不属于当前账号。',
  409: '会话已归档，不能再发送新消息。',
  422: '消息不符合要求（不能为空 / 超长，或未绑定可用的数字员工、工具调用格式不合法）。',
  0: DEFAULT_CONVERSATION_ERROR,
}

/** 取某状态码的文案；查不到时用 `fallback`（通常是请求层已 sanitize 的 `message`）。 */
export function conversationMessageFor(status: number, fallback?: string): string {
  const fixed = CONVERSATION_FIXED_MESSAGES[status]
  if (fixed) return fixed
  if (status >= 500) return DEFAULT_CONVERSATION_ERROR
  return fallback || `请求未被接受（${status}）。`
}

/** 是否值得重试：网络失败与 5xx 可重试；其余（含 401/403/404/409/422）不重试。 */
export function conversationRetryable(status: number): boolean {
  return status === 0 || status >= 500
}

export const initialConversationState: ConversationState = {
  detail: null,
  detailLoading: false,
  detailError: null,
  createError: null,
  exportError: null,
  sending: false,
  sendError: null,
  streamNotice: null,
  archiving: false,
  toast: null,
  // P2c-6 会话协作：参与者名单初始为空（未选中会话 / 未加载完成都**不得凭空造名单**）。
  participants: [],
  participantsTotal: 0,
  participantsLoading: false,
  participantsError: null,
  sharing: false,
  shareError: null,
}

/**
 * HTTP 状态码 → 值对象形状。
 * 仅当服务端 `detail` 是**字符串**时才透出（那是后端自己写的中文原因）。
 */
export function conversationErrorFromStatus(status: number, detail?: string | null): ConversationErrorShape {
  return {
    status,
    message: conversationMessageFor(status, detail ?? undefined),
    retryable: conversationRetryable(status),
  }
}

/** 把任意异常规整成页面可直接展示的中文提示（**不吞异常语义**，只做形状归一）。 */
export function asConversationError(error: unknown): ConversationErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message =
      typeof candidate.message === 'string' && candidate.message
        ? candidate.message
        : DEFAULT_CONVERSATION_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_CONVERSATION_ERROR, retryable: true }
}
