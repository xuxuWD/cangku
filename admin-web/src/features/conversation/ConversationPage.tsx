import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import { ApprovalCard } from '../stage/ApprovalCard'
import { StagePanel } from '../stage/StagePanel'
import { ArtifactChips } from '../stage/ArtifactChips'
import { useRunAcceptance } from '../stage/useRunAcceptance'
import { useRunArtifacts } from '../stage/useRunArtifacts'
import { useRunApprovals } from '../stage/useRunApprovals'
import { useRunOverview } from '../stage/useRunOverview'
import {
  addConversationMember,
  archiveConversation,
  createConversation,
  deleteConversation,
  exportMyConversations,
  getConversation,
  listConversationMembers,
  listConversations,
  removeConversationMember,
  sendConversationMessage,
  sendConversationMessageStream,
  setConversationMode,
} from './api'
import { parseToolInvocation } from './invocation'
import { ProcessBar } from './ProcessBar'
import { asConversationError, initialConversationState } from './state'
import { useRunStream } from './useRunStream'
import { useSlotVisible } from './useSlotVisible'
import {
  CONVERSATION_MODE_HINTS,
  CONVERSATION_MODE_LABELS,
  CONVERSATION_PAGE_SIZE,
  MAX_MESSAGE_LENGTH,
  MESSAGE_PAGE_SIZE,
  STUB_NOTICE,
  conversationModeLabel,
  conversationStatusLabel,
  conversationTitle,
  formatMessageTime,
  speakerLabel,
  type ConversationMode,
  type ConversationState,
  type ConversationStatus,
  type MemberPermission,
} from './types'

const STATUS_FILTERS: Array<{ value: ConversationStatus | 'all'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '进行中' },
  { value: 'archived', label: '已归档' },
]

const MODE_OPTIONS: ConversationMode[] = ['craft', 'goal', 'plan', 'ask']

// 每条消息生成一个新幂等键（§3.2 第四条）：同一键重放由服务端返回既有结果，
// 因此重试/双击不会产生第二次真实执行。优先用 `crypto.randomUUID`，不可用时回落。
function newIdempotencyKey(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function ConversationPage({
  conversationId,
  onNavigate,
  onSelectConversation,
}: {
  conversationId?: string
  onNavigate?: (view: AppView, taskId?: string, runId?: string) => void
  onSelectConversation: (conversationId: string | undefined) => void
}) {
  const [state, setState] = useState<ConversationState>(initialConversationState)
  const [draft, setDraft] = useState('')
  const [messagesLimit, setMessagesLimit] = useState(MESSAGE_PAGE_SIZE)
  const [creating, setCreating] = useState(false)
  // P2c-1：本次会话的「当前 run」由发送响应（`X-Stream-Run-Id`）给出；舞台与审批据此加载。
  const [streamRunId, setStreamRunId] = useState<string | undefined>(undefined)
  const [streamActive, setStreamActive] = useState(false)
  const [restartToken, setRestartToken] = useState(0)
  const [terminalToken, setTerminalToken] = useState(0)
  // 窄屏时舞台折叠为抽屉（默认收起）；宽屏由 CSS 强制展示，按钮不可见。
  const [stageOpen, setStageOpen] = useState(false)
  // P2c-4：模式切换 / 删除 / 导出各自独立忙碌位（互不阻塞；失败不改动已加载列表）。
  const [modeSaving, setModeSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  // P2c-4 §2.5：**一键重做**仅当本页仍持有原结构化调用时可用（内存态，刷新即失；不落库）。
  const [lastInvocation, setLastInvocation] = useState<string | null>(null)

  const rootRef = useRef<HTMLElement | null>(null)
  const messagesLimitRef = useRef(messagesLimit)
  messagesLimitRef.current = messagesLimit
  const stateRef = useRef(state)
  stateRef.current = state
  const messageFrameSeqRef = useRef(0)

  // 切走即断开（§2.3）：视图槽 hidden / 标签页不可见时不保持长连接。
  const visible = useSlotVisible(rootRef)

  const loadList = useCallback(async (status: ConversationStatus | 'all', offset: number) => {
    setState((old) => ({ ...old, conversationsLoading: true, conversationsError: null }))
    try {
      const data = await listConversations({
        status: status === 'all' ? undefined : status,
        limit: CONVERSATION_PAGE_SIZE,
        offset,
      })
      setState((old) => ({
        ...old,
        conversations: Array.isArray(data.items) ? data.items : [],
        conversationsTotal: typeof data.total === 'number' ? data.total : 0,
        statusFilter: status,
        listOffset: offset,
        conversationsLoading: false,
        conversationsError: null,
      }))
    } catch (error) {
      setState((old) => ({ ...old, conversationsLoading: false, conversationsError: asConversationError(error) }))
    }
  }, [])

  const loadDetail = useCallback(async (id: string, limit: number) => {
    setState((old) => ({ ...old, detailLoading: true, detailError: null }))
    try {
      const detail = await getConversation(id, { limit, offset: 0 })
      setState((old) => ({ ...old, detail, detailLoading: false, detailError: null }))
      return detail
    } catch (error) {
      setState((old) => ({ ...old, detail: null, detailLoading: false, detailError: asConversationError(error) }))
      return null
    }
  }, [])

  // P2c-6：参与者名单独立加载（发言人回溯与分享区块共用同一份数据）。
  // 名单失败**不阻断**会话读取，也不编造姓名：界面按「会话成员 / 发起人」如实回落。
  const loadParticipants = useCallback(async (id: string) => {
    setState((old) => ({ ...old, participantsLoading: true, participantsError: null }))
    try {
      const data = await listConversationMembers(id)
      setState((old) => ({
        ...old,
        participants: Array.isArray(data.items) ? data.items : [],
        participantsLoading: false,
        participantsError: null,
      }))
    } catch (error) {
      setState((old) => ({
        ...old,
        participants: [],
        participantsLoading: false,
        participantsError: asConversationError(error),
      }))
    }
  }, [])

  useEffect(() => { void loadList('all', 0) }, [loadList])

  // URL 里带 conversation 时直接打开该会话；切换会话时清空残留详情、草稿与流状态。
  useEffect(() => {
    setDraft('')
    setMessagesLimit(MESSAGE_PAGE_SIZE)
    setStreamRunId(undefined)
    // P2c-4 §2.5：跨会话不携带「原结构化调用」（一键重做只在**本页当次**持有原件时可用）。
    setLastInvocation(null)
    // P2c-2：进入会话即开启读端做**回放**（§2.3 打开（回放））——历史会话由此解析出
    // 「最新 run」（响应头 `X-Stream-Run-Id` / 帧内 `run_id`），运行概览与审批随之可用。
    setStreamActive(Boolean(conversationId))
    setRestartToken((value) => value + 1)
    messageFrameSeqRef.current = 0
    setState((old) => ({ ...old, detail: null, detailError: null, sendError: null, streamNotice: null }))
    // P2c-6：跨会话不沿用上一份参与者名单（名单只作展示，不本地造）。
    setState((old) => ({ ...old, participants: [], participantsError: null, shareError: null }))
    if (conversationId) {
      void loadDetail(conversationId, MESSAGE_PAGE_SIZE)
      void loadParticipants(conversationId)
    }
  }, [conversationId, loadDetail, loadParticipants])

  // 终态帧 ⇒ 关流后重取「消息 + 列表 + 运行概览」（消息权威仍在消息表）。
  const handleTerminal = () => {
    setTerminalToken((value) => value + 1)
    const id = conversationId
    if (!id) return
    void loadDetail(id, messagesLimitRef.current)
    void loadList(stateRef.current.statusFilter, stateRef.current.listOffset)
  }

  const stream = useRunStream({
    conversationId,
    runId: streamRunId,
    enabled: visible && streamActive,
    restartToken,
    // 发送进行中⇒缺 run 时继续等（边执行边看）；历史会话回放则缺 run 即如实告知（P2c-2）。
    awaitRun: state.sending,
    onTerminal: handleTerminal,
  })

  // `message.*` 帧只作「已落定」信号：触发一次详情重取（正文由消息表权威提供，帧不落正文）。
  useEffect(() => {
    const latest = stream.frames
      .filter((frame) => frame.kind === 'message.user' || frame.kind === 'message.assistant')
      .reduce((max, frame) => Math.max(max, frame.seq), 0)
    if (latest <= messageFrameSeqRef.current) return
    messageFrameSeqRef.current = latest
    if (conversationId) void loadDetail(conversationId, messagesLimitRef.current)
  }, [stream.frames, conversationId, loadDetail])

  // P2c-2：显式 run（本次发送）优先；否则用读端解析出的 run（响应头 `X-Stream-Run-Id` / 帧内 `run_id`），
  // 使**历史会话**（未发生本次发送）也能加载运行概览与审批（此前只有过程时间线可用）。
  const effectiveRunId = streamRunId ?? stream.runId ?? undefined
  const overview = useRunOverview(effectiveRunId, terminalToken)
  const approvals = useRunApprovals(effectiveRunId)
  // P2c-3：产物登记（运行级元数据；随运行终态重取——写文件的工具多在审批后推进才产出）。
  const artifacts = useRunArtifacts(effectiveRunId, terminalToken)
  // P2c-4：结构判定（服务端只读端点；随终态与决议后重取——未决审批与推进都会改变结论）。
  const acceptance = useRunAcceptance(effectiveRunId, terminalToken)
  const role = import.meta.env.VITE_USER_ROLE || 'super_admin'
  const canDecide = (role === 'ceo' || role === 'super_admin') && !overview.isInitiator
  const pendingApprovals = approvals.items.filter((item) => item.status === 'pending')

  // 决议后**重开读端**尾随推进帧（P2c-2 §2.8：推进在同一 run 续写；成功后才有帧可看）。
  const handleDecide = async (approvalId: string, approved: boolean): Promise<string | null> => {
    const failure = await approvals.decide(approvalId, approved)
    if (failure === null) {
      setStreamActive(true)
      setRestartToken((value) => value + 1)
    }
    return failure
  }
  // 舞台与对话流**共用同一决议入口**（两处同源；重开读端的副作用只在一处）。
  const approvalsView = { ...approvals, decide: handleDecide }

  const forbidden = state.conversationsError?.status === 403
  const archived = state.detail?.status !== 'active'
  const canSend = draft.trim().length > 0 && !state.sending && !archived
  const draftInvocation = parseToolInvocation(draft)

  const startConversation = async () => {
    setCreating(true)
    setState((old) => ({ ...old, createError: null }))
    try {
      // 新建会话不需要选入员工：agent_key 缺省即用默认员工。
      const created = await createConversation({})
      await loadList(state.statusFilter, state.listOffset)
      onSelectConversation(created.conversation_id)
    } catch (error) {
      setState((old) => ({ ...old, createError: asConversationError(error) }))
    } finally {
      setCreating(false)
    }
  }

  const send = async (override?: string) => {
    // P2c-4 §2.5：`override` 只由**一键重做**传入（本页仍持有的原结构化调用原文）；
    // 重做走的是同一条正常发送路径 + **新幂等键** ⇒ 一次全新的调用（新 run），不改动原运行。
    const content = (override ?? draft).trim()
    if (!conversationId || !content) return
    if (!override && !canSend) return
    setState((old) => ({ ...old, sending: true, sendError: null, streamNotice: null }))
    try {
      const invocation = parseToolInvocation(content)
      if (invocation) {
        // 实时流路径（§2.4）：先重开读端（缺省 run 解析会自动发现新 run，保证「边执行边看」），
        // 响应带回 `X-Stream-Run-Id` 后锁定该 run（读端按显式 run 重连并续播）。
        setStreamRunId(undefined)
        setStreamActive(true)
        setRestartToken((value) => value + 1)
        const result = await sendConversationMessageStream(conversationId, content, newIdempotencyKey())
        // 结构化调用原文只留在**本页内存**（供未达标时一键重做）；不落库、不进存储。
        setLastInvocation(content)
        if (result.runId) {
          setStreamRunId(result.runId)
          setRestartToken((value) => value + 1)
        } else {
          // 没有运行 ⇒ 后端未装配真实执行（回落桩路径）：**如实告知并关流**，
          // 不留下一个永远「执行中」的假过程条（不谎报）。
          setStreamActive(false)
          setState((old) => ({
            ...old,
            streamNotice: '未产生运行：后端未装配真实执行，本次按桩回复处理（没有过程流）。',
          }))
        }
        if (result.body.status === 'pending_approval') {
          // 待批后不再写帧（P2b 已知限制）⇒ 主动关流，避免挂着等 6h 悬挂兜底。
          setStreamActive(false)
          setState((old) => ({ ...old, toast: '已提交审批，决议后以运行详情为准' }))
        }
      } else {
        // 纯文本 ⇒ 不带键（桩路径：不写帧、无流、无副作用）。
        await sendConversationMessage(conversationId, content)
      }
      if (!override) setDraft('')
      // 服务端已确认落库；重取详情拿到真实顺序与最新总数，不做乐观拼接。
      const nextLimit = Math.max(messagesLimit, (state.detail?.messages_total ?? 0) + 2)
      setMessagesLimit(nextLimit)
      await loadDetail(conversationId, nextLimit)
      await loadList(state.statusFilter, state.listOffset)
      setState((old) => ({ ...old, sending: false, sendError: null }))
    } catch (error) {
      setState((old) => ({ ...old, sending: false, sendError: asConversationError(error) }))
    }
  }

  // P2c-4 §2.9：改模式（仅本人）。失败只提示，**不做本地乐观更新**（服务端权威态回流）。
  const changeMode = async (mode: ConversationMode) => {
    if (!conversationId || modeSaving) return
    if (state.detail?.mode === mode) return
    setModeSaving(true)
    try {
      const updated = await setConversationMode(conversationId, mode)
      setState((old) => ({
        ...old,
        detail: old.detail ? { ...old.detail, mode: updated.mode, updated_at: updated.updated_at } : old.detail,
        toast: `已切换为「${conversationModeLabel(updated.mode)}」`,
      }))
      await loadList(state.statusFilter, state.listOffset)
    } catch (error) {
      setState((old) => ({ ...old, detailError: asConversationError(error) }))
    } finally {
      setModeSaving(false)
    }
  }

  // P2c-6 会话协作：添加成员（仅发起人；服务端权威回流，不做乐观更新）。
  const shareMember = async (memberId: string, permission: MemberPermission) => {
    if (!conversationId || state.sharing) return
    setState((old) => ({ ...old, sharing: true, shareError: null }))
    try {
      const grant = await addConversationMember(conversationId, memberId, permission)
      setState((old) => ({
        ...old,
        sharing: false,
        shareError: null,
        toast: `已添加成员 ${grant.member_id}（权限：${grant.permission === 'write' ? '可发言' : '仅查看'}）`,
      }))
      await loadParticipants(conversationId)
    } catch (error) {
      setState((old) => ({ ...old, sharing: false, shareError: asConversationError(error) }))
    }
  }

  // P2c-6 会话协作：撤销成员（仅发起人）。**已读内容不可撤回**——只影响对方新的读取 / 发言。
  const revokeMember = async (memberId: string) => {
    if (!conversationId || state.sharing) return
    setState((old) => ({ ...old, sharing: true, shareError: null }))
    try {
      await removeConversationMember(conversationId, memberId)
      setState((old) => ({
        ...old,
        sharing: false,
        shareError: null,
        toast: `已撤销成员 ${memberId}（对方新的读取会被拒绝；已读内容不可撤回）`,
      }))
      await loadParticipants(conversationId)
    } catch (error) {
      setState((old) => ({ ...old, sharing: false, shareError: asConversationError(error) }))
    }
  }

  // P2c-4 §2.11：**物理删除**（不可撤销）——二次确认后才发请求；成功后清空选择并回列表。
  const remove = async () => {
    if (!conversationId || deleting) return
    const confirmed = globalThis.confirm?.(
      '删除后：本会话的消息、过程帧、流状态与幂等记录会被物理删除（不可撤销，仅本人会话）；' +
        '会话标题会清空，运行记录与审计按合规口径保留。确认删除？',
    )
    if (confirmed === false) return
    setDeleting(true)
    try {
      const outcome = await deleteConversation(conversationId)
      setState((old) => ({
        ...old,
        toast: `已删除（消息 ${outcome.message_count} / 帧 ${outcome.frame_count} / 流状态 ${outcome.stream_state_count} / 幂等 ${outcome.idempotency_count}）`,
      }))
      setStreamActive(false)
      setLastInvocation(null)
      onSelectConversation(undefined)
      await loadList(state.statusFilter, state.listOffset)
    } catch (error) {
      setState((old) => ({ ...old, detailError: asConversationError(error) }))
    } finally {
      setDeleting(false)
    }
  }

  // P2c-4 §2.11：导出本人全部会话数据（逐页合并 → JSON 文件下载）；超上限**如实告知**。
  const exportMine = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const bundle = await exportMyConversations()
      const payload = {
        exported_at: bundle.pages[0]?.exported_at ?? new Date().toISOString(),
        conversation_count: bundle.pages.reduce((total, page) => total + page.conversations.length, 0),
        message_count: bundle.pages.reduce(
          (total, page) => total + page.conversations.reduce((sum, item) => sum + item.messages.length, 0),
          0,
        ),
        total_conversations: bundle.pages[0]?.total_conversations ?? 0,
        total_messages: bundle.pages[0]?.total_messages ?? 0,
        truncated: bundle.truncated,
        limit_reason: bundle.pages.find((page) => page.limit_reason)?.limit_reason ?? null,
        pages: bundle.pages.map((page) => ({ limit: page.limit, offset: page.offset, conversations: page.conversations })),
      }
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `conversations-export-${Date.now()}.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setState((old) => ({
        ...old,
        toast: bundle.truncated
          ? `已导出 ${payload.conversation_count} 个会话（数据量超过服务端上限，未包含全部；已如实标注 truncated）`
          : `已导出 ${payload.conversation_count} 个会话 / ${payload.message_count} 条消息`,
      }))
    } catch (error) {
      setState((old) => ({ ...old, conversationsError: asConversationError(error) }))
    } finally {
      setExporting(false)
    }
  }

  const archive = async () => {
    if (!conversationId || state.archiving) return
    setState((old) => ({ ...old, archiving: true }))
    try {
      const updated = await archiveConversation(conversationId)
      setState((old) => ({
        ...old,
        archiving: false,
        detail: old.detail ? { ...old.detail, status: updated.status, updated_at: updated.updated_at } : old.detail,
        toast: '会话已归档',
      }))
      await loadList(state.statusFilter, state.listOffset)
    } catch (error) {
      setState((old) => ({ ...old, archiving: false, detailError: asConversationError(error) }))
    }
  }

  const loadMoreMessages = () => {
    if (!conversationId) return
    const next = messagesLimit + MESSAGE_PAGE_SIZE
    setMessagesLimit(next)
    void loadDetail(conversationId, next)
  }

  const detail = state.detail

  return (
    <>
      <main className="main-content content-history conversation" ref={rootRef}>
        <div className="page-head">
          <div>
            <h1 className="page-title">对话</h1>
            <p className="page-desc">与数字员工对话。会话与消息的数据模型、权限与审计都是真实的；助手回复是后端标注的桩回复。</p>
          </div>
          <div className="actions">
            <button className="button primary" type="button" disabled={creating || forbidden} onClick={() => void startConversation()}>新建会话</button>
            <button className="button" type="button" disabled={forbidden || exporting} onClick={() => void exportMine()}>
              {exporting ? '正在导出…' : '导出我的数据'}
            </button>
            <button className="button" type="button" disabled={forbidden} onClick={() => void loadList(state.statusFilter, state.listOffset)}>刷新</button>
          </div>
        </div>

        <div className="notice" role="note">
          <div><strong>P1 桩回复</strong><p>{STUB_NOTICE}</p></div>
        </div>

        {state.createError && (
          <div className="notice notice-error" role="alert">
            <div><strong>新建会话失败</strong><p>{state.createError.message}</p></div>
            {state.createError.retryable && <button className="text-action" type="button" onClick={() => void startConversation()}>重新尝试</button>}
          </div>
        )}

        {forbidden ? (
          <div className="notice notice-error" role="alert">
            <div><strong>无法使用对话</strong><p>{state.conversationsError?.message}</p></div>
          </div>
        ) : (
          <>
            <button
              className="stage-toggle"
              type="button"
              aria-expanded={stageOpen}
              onClick={() => setStageOpen((value) => !value)}
            >
              {stageOpen ? '收起过程与运行' : '展开过程与运行'}
            </button>
            <div className="conversation-layout conversation-layout--stage">
            <section className="history-panel" aria-label="会话列表">
              <div className="panel-header">
                <h2>会话</h2>
                <span>共 {state.conversationsTotal} 条</span>
              </div>
              <div className="panel-body">
                <div className="segment" role="tablist" aria-label="会话筛选">
                  {STATUS_FILTERS.map((option) => (
                    <button
                      key={option.value}
                      role="tab"
                      type="button"
                      aria-selected={state.statusFilter === option.value}
                      className={state.statusFilter === option.value ? 'active' : ''}
                      onClick={() => void loadList(option.value, 0)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {state.conversationsLoading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话…</div>}

              {!state.conversationsLoading && state.conversationsError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>会话列表加载失败</strong><p>{state.conversationsError.message}</p></div>
                  {state.conversationsError.retryable && <button className="text-action" type="button" onClick={() => void loadList(state.statusFilter, state.listOffset)}>重新尝试</button>}
                </div>
              )}

              {!state.conversationsLoading && !state.conversationsError && state.conversations.length === 0 && (
                <div className="empty-state"><strong>还没有会话</strong><span>点击「新建会话」开始，或在输入框里直接发第一条消息。</span></div>
              )}

              {!state.conversationsLoading && !state.conversationsError && state.conversations.map((item) => (
                <div
                  className={`history-row conversation-item ${item.conversation_id === conversationId ? 'active' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-current={item.conversation_id === conversationId ? 'true' : undefined}
                  key={item.conversation_id}
                  onClick={() => onSelectConversation(item.conversation_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelectConversation(item.conversation_id)
                    }
                  }}
                >
                  <div className="history-row-main">
                    <strong>{conversationTitle(item.title)}</strong>
                    <div className="history-meta">
                      <span className={`status-badge status-${item.status}`}>{conversationStatusLabel(item.status)}</span>
                      <span className="status-badge status-reviewing">{conversationModeLabel(item.mode)}</span>
                      {item.agent_key && <span className="ws-code">{item.agent_key}</span>}
                      <span>更新于 {formatMessageTime(item.updated_at)}</span>
                    </div>
                  </div>
                </div>
              ))}

              {!state.conversationsLoading && !state.conversationsError && state.conversationsTotal > CONVERSATION_PAGE_SIZE && (
                <div className="history-pagination">
                  <button className="button" type="button" disabled={state.listOffset === 0} onClick={() => void loadList(state.statusFilter, Math.max(0, state.listOffset - CONVERSATION_PAGE_SIZE))}>上一页</button>
                  <span>{state.listOffset + 1}–{Math.min(state.listOffset + CONVERSATION_PAGE_SIZE, state.conversationsTotal)} / {state.conversationsTotal}</span>
                  <button className="button" type="button" disabled={state.listOffset + CONVERSATION_PAGE_SIZE >= state.conversationsTotal} onClick={() => void loadList(state.statusFilter, state.listOffset + CONVERSATION_PAGE_SIZE)}>下一页</button>
                </div>
              )}
            </section>

            <section className="history-panel" aria-label="会话内容">
              {!conversationId && (
                <div className="empty-state"><strong>选择一个会话查看消息</strong><span>左侧列表里点一个会话，就能看到消息记录并继续对话。</span></div>
              )}

              {conversationId && state.detailLoading && !detail && (
                <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话内容…</div>
              )}

              {conversationId && !state.detailLoading && state.detailError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>会话加载失败</strong><p>{state.detailError.message}</p></div>
                  {state.detailError.retryable && <button className="text-action" type="button" onClick={() => void loadDetail(conversationId, messagesLimit)}>重新尝试</button>}
                </div>
              )}

              {detail && (
                <>
                  <div className="panel-header">
                    <div>
                      <h2>{conversationTitle(detail.title)}</h2>
                      <span className="page-code">{detail.conversation_id}</span>
                    </div>
                    <div className="history-actions">
                      <span className={`status-badge status-${detail.status}`}>{conversationStatusLabel(detail.status)}</span>
                      <button className="button" type="button" disabled={archived || state.archiving} onClick={() => void archive()}>归档</button>
                      <button className="button" type="button" disabled={deleting} onClick={() => void remove()}>
                        {deleting ? '正在删除…' : '删除会话'}
                      </button>
                    </div>
                  </div>

                  <div className="panel-body">
                    <div className="history-meta">
                      {detail.agent_key && <span>执行人：<span className="ws-code">{detail.agent_key}</span></span>}
                      <span>共 {detail.messages_total} 条消息</span>
                    </div>
                    <label className="ws-field conversation-mode">
                      会话模式
                      <select
                        aria-label="会话模式"
                        value={detail.mode}
                        disabled={archived || modeSaving}
                        onChange={(event) => void changeMode(event.target.value as ConversationMode)}
                      >
                        {MODE_OPTIONS.map((mode) => (
                          <option value={mode} key={mode}>{CONVERSATION_MODE_LABELS[mode]}（{mode}）</option>
                        ))}
                      </select>
                      <small className="ws-field-hint">
                        {CONVERSATION_MODE_HINTS[detail.mode] ?? '模式由服务端判定，只收紧、不放松既有权限。'}
                        {archived && '（会话已归档，不能再修改模式）'}
                      </small>
                    </label>
                  </div>

                  {detail.messages.length === 0 && (
                    <div className="empty-state"><strong>这个会话还没有消息</strong><span>在下方输入框发送第一条消息。</span></div>
                  )}

                  {detail.messages.length > 0 && (
                    <div className="conversation-messages">
                      {detail.messages.map((message) => (
                        <article className={`conversation-message conversation-message--${message.role}`} key={message.message_id}>
                          <div className="conversation-message__head">
                            <strong>{speakerLabel(message, state.participants)}</strong>
                            {message.role === 'assistant' && message.stub && <span className="status-badge status-reviewing">桩回复</span>}
                            {message.tool_name && <span className="ws-code">{message.tool_name}</span>}
                            <span>{formatMessageTime(message.created_at)}</span>
                          </div>
                          <p className="conversation-message__body">{message.content}</p>
                        </article>
                      ))}
                    </div>
                  )}

                  <ProcessBar frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />

                  <ArtifactChips
                    frames={stream.frames}
                    runId={effectiveRunId}
                    onOpenRunDetail={(runId) => onNavigate?.('run', undefined, runId)}
                  />

                  {pendingApprovals.length > 0 && (
                    <div className="conversation-approvals" aria-label="待审批">
                      {pendingApprovals.map((approval) => (
                        <ApprovalCard
                          key={approval.approval_id}
                          approval={approval}
                          canDecide={canDecide}
                          deciding={approvals.decidingId === approval.approval_id}
                          onDecide={(approved) => void handleDecide(approval.approval_id, approved)}
                        />
                      ))}
                    </div>
                  )}

                  {detail.messages.length < detail.messages_total && (
                    <div className="history-pagination">
                      <button className="button" type="button" disabled={state.detailLoading} onClick={loadMoreMessages}>加载更多消息</button>
                      <span>已显示 {detail.messages.length} / {detail.messages_total}</span>
                    </div>
                  )}

                  <div className="conversation-composer">
                    <form
                      className="composer"
                      onSubmit={(event) => {
                        event.preventDefault()
                        void send()
                      }}
                    >
                      <textarea
                        className="composer-input"
                        aria-label="消息内容"
                        placeholder={archived ? '会话已归档，不能发送新消息' : '给数字员工发一条消息…'}
                        rows={3}
                        maxLength={MAX_MESSAGE_LENGTH}
                        value={draft}
                        disabled={archived}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                      <div className="composer-bar">
                        <span className="composer-field">
                          {archived
                            ? '会话已归档，不能发送'
                            : draftInvocation
                              ? detail.mode === 'ask'
                                ? `结构化调用：${draftInvocation.tool_key}（当前为「只问答」，服务端会拒绝执行）`
                                : detail.mode === 'plan'
                                  ? `结构化调用：${draftInvocation.tool_key}（当前为「先计划后执行」，一律先落待批）`
                                  : `结构化调用：${draftInvocation.tool_key}（按真实执行路径发送）`
                              : `最长 ${MAX_MESSAGE_LENGTH} 字符 · 纯文本不触发真实执行`}
                        </span>
                        <button className="composer-send" type="submit" disabled={!canSend} aria-label="发送消息">
                          <Icon name="send" size={18} />
                        </button>
                      </div>
                    </form>

                    {archived && (
                      <div className="notice" role="status">
                        <div><strong>会话已归档</strong><p>归档后不能再发送新消息（后端会返回 409），历史消息仍可查看；如需继续对话，请新建会话。</p></div>
                      </div>
                    )}

                    {state.sendError && (
                      <div className="notice notice-error" role="alert">
                        <div><strong>消息发送失败</strong><p>{state.sendError.message}</p></div>
                      </div>
                    )}

                    {state.streamNotice && (
                      <div className="notice" role="status">
                        <div><strong>本次没有过程流</strong><p>{state.streamNotice}</p></div>
                      </div>
                    )}
                  </div>
                </>
              )}
            </section>

            <StagePanel
              runId={effectiveRunId}
              stream={stream}
              overview={overview}
              approvals={approvalsView}
              artifacts={artifacts}
              acceptance={acceptance}
              mode={detail?.mode}
              redoAvailable={Boolean(lastInvocation)}
              onRedo={() => {
                if (lastInvocation) void send(lastInvocation)
              }}
              canDecide={canDecide}
              expanded={stageOpen}
              onOpenRunDetail={(runId) => onNavigate?.('run', undefined, runId)}
              // P2c-6：参与者与分享（舞台呈现；数据与增删回调都由本页提供，舞台只渲染）。
              collaboration={{
                items: state.participants,
                lastActivityAt: detail?.updated_at ?? null,
                loading: state.participantsLoading,
                error: state.shareError?.message ?? state.participantsError?.message ?? null,
                sharing: state.sharing,
                onAdd: (memberId, permission) => void shareMember(memberId, permission),
                onRemove: (memberId) => void revokeMember(memberId),
              }}
            />
            </div>
          </>
        )}
      </main>
      <Toast message={state.toast} />
    </>
  )
}