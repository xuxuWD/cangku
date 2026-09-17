import type { ConversationErrorShape, ConversationState } from './types'

const DEFAULT_CONVERSATION_ERROR = '对话服务暂时不可用，请检查网络后重新尝试。'

export const initialConversationState: ConversationState = {
  conversations: [],
  conversationsTotal: 0,
  conversationsLoading: true,
  conversationsError: null,
  statusFilter: 'all',
  listOffset: 0,
  detail: null,
  detailLoading: false,
  detailError: null,
  createError: null,
  sending: false,
  sendError: null,
  streamNotice: null,
  archiving: false,
  toast: null,
  // P2c-6 会话协作：参与者名单初始为空（未选中会话 / 未加载完成都不得凭空造名单）。
  participants: [],
  participantsTotal: 0,
  participantsLoading: false,
  participantsError: null,
  sharing: false,
  shareError: null,
}

// 按 HTTP 状态码映射为固定中文提示，不把堆栈、URL 或原始异常文本透到界面。
// 仅当服务端返回的 `detail` 是**字符串**时才透出（那是后端自己写的中文原因）。
export function conversationErrorFromStatus(status: number, detail?: string | null): ConversationErrorShape {
  if (status === 401) return { status, message: '登录态已失效，请重新登录。', retryable: false }
  if (status === 403) return { status, message: detail || '当前岗位不能使用对话入口。', retryable: false }
  if (status === 404) return { status, message: detail || '会话不存在，或不属于当前账号。', retryable: false }
  if (status === 409) return { status, message: detail || '会话已归档，不能再发送新消息。', retryable: false }
  if (status === 422) return { status, message: detail || '消息不符合要求（不能为空 / 超长，或未绑定可用的数字员工、工具调用格式不合法）。', retryable: false }
  if (status === 0 || status >= 500) return { status, message: DEFAULT_CONVERSATION_ERROR, retryable: true }
  return { status, message: detail || `请求未被接受（${status}）。`, retryable: false }
}

// 把任意异常规整成页面可直接展示的中文提示。
export function asConversationError(error: unknown): ConversationErrorShape {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const candidate = error as { status?: unknown; message?: unknown; retryable?: unknown }
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const message = typeof candidate.message === 'string' && candidate.message ? candidate.message : DEFAULT_CONVERSATION_ERROR
    return { status, message, retryable: candidate.retryable !== false }
  }
  return { status: 0, message: DEFAULT_CONVERSATION_ERROR, retryable: true }
}
