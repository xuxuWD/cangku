import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import { EmptyState } from '../../components/ui/EmptyState'
import { relativeTime } from '../../utils/time'
import { ApprovalCard } from '../stage/ApprovalCard'
import { StagePanel } from '../stage/StagePanel'
import { ArtifactChips } from '../stage/ArtifactChips'
import { useRunAcceptance } from '../stage/useRunAcceptance'
import { useRunArtifacts } from '../stage/useRunArtifacts'
import { useRunApprovals } from '../stage/useRunApprovals'
import { useRunOverview } from '../stage/useRunOverview'
import { runStatusLabel } from '../runDetail/types'
import {
  addConversationMember,
  archiveConversation,
  createConversation,
  deleteConversation,
  exportMyConversations,
  getConversation,
  listConversationMembers,
  removeConversationMember,
  sendConversationMessage,
  sendConversationMessageStream,
  setConversationMode,
} from './api'
import { parseToolInvocation } from './invocation'
import { useConversationList } from './listStore'
import { ProcessBar } from './ProcessBar'
import { asConversationError, initialConversationState } from './state'
import { useRunStream } from './useRunStream'
import { useSlotVisible } from './useSlotVisible'
import {
  CONVERSATION_MODE_HINTS,
  CONVERSATION_MODE_LABELS,
  MAX_MESSAGE_LENGTH,
  MESSAGE_PAGE_SIZE,
  conversationModeLabel,
  conversationStatusLabel,
  conversationTitle,
  formatMessageTime,
  speakerLabel,
  type ConversationMode,
  type ConversationState,
  type MemberPermission,
} from './types'

/** 模式顺序：由宽到严（完整执行 → 先计划后执行 → 目标驱动 → 只问答）。 */
const MODE_OPTIONS: ConversationMode[] = ['craft', 'plan', 'goal', 'ask']

/** 斜杠指令最小集（S6）：在输入框里以 `/` 开头即触发，不发送给服务端。 */
const SLASH_COMMANDS: Array<{ key: string; what: string }> = [
  { key: '/new', what: '新建一个对话并切过去（当前会话不丢）' },
  { key: '/stop', what: '停止跟随本次执行过程（运行仍在后台继续，点「刷新」看最新进展）' },
  { key: '/help', what: '打开指令说明（本面板）' },
  { key: '/status', what: '看当前会话的状态（模式 / 消息数 / 运行 / 待批 / 参与者）' },
]

type ComposerPanel = 'none' | 'mode' | 'ability' | 'help' | 'status'

// 每条消息生成一个新幂等键（§3.2 第四条）：同一键重放由服务端返回既有结果，
// 因此重试/双击不会产生第二次真实执行。优先用 `crypto.randomUUID`，不可用时回落。
function newIdempotencyKey(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * 对话页（模板 T2）：消息流 + 右侧舞台 + 富控件输入卡。
 *
 * S6（模式与场景可见）：模式做成一等公民（输入栏可切换 + 文案解释）；斜杠指令最小集；
 * 「本会话能力」可见（模式口径 / 结构化调用入口 / 本次运行出现过的工具——全部来自真实数据）。
 *
 * 纪律：一切状态以服务端为准（不做乐观更新）；失败如实提示，不假装成功。
 */
export function ConversationPage({
  conversationId,
  focusApprovalId,
  onNavigate,
  onSelectConversation,
}: {
  conversationId?: string
  /** S1 第三款：通知点开时带上的审批标识 ⇒ 页内定位并高亮那张卡（数据仍全部来自服务端权威态）。 */
  focusApprovalId?: string
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
  // S6：输入栏上方的面板（模式 / 能力 / 指令 / 状态）。
  const [panel, setPanel] = useState<ComposerPanel>('none')
  // P2c-4：模式切换 / 删除 / 导出各自独立忙碌位（互不阻塞；失败不改动已加载列表）。
  const [modeSaving, setModeSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  // P2c-4 §2.5：**一键重做**仅当本页仍持有原结构化调用时可用（内存态，刷新即失；不落库）。
  const [lastInvocation, setLastInvocation] = useState<string | null>(null)

  const rootRef = useRef<HTMLElement | null>(null)
  // S1 第三款：已经按哪个审批标识滚过（同一个标识只滚一次）。
  const focusedRef = useRef<string | null>(null)
  const messagesLimitRef = useRef(messagesLimit)
  messagesLimitRef.current = messagesLimit
  const messageFrameSeqRef = useRef(0)

  // 切走即断开（§2.3）：视图槽 hidden / 标签页不可见时不保持长连接。
  const visible = useSlotVisible(rootRef)

  // 左栏与会话页共用同一份列表状态（真源 §2.17.3），页面不再自己拉列表。
  const list = useConversationList()

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
      const items = Array.isArray(data.items) ? data.items : []
      setState((old) => ({
        ...old,
        participants: items,
        // 命中总数取服务端口径（`total > items.length` ⇒ 本页之外还有成员，界面如实告知，不谎报为全部）。
        participantsTotal: typeof data.total === 'number' ? data.total : items.length,
        participantsLoading: false,
        participantsError: null,
      }))
    } catch (error) {
      setState((old) => ({
        ...old,
        participants: [],
        participantsTotal: 0,
        participantsLoading: false,
        participantsError: asConversationError(error),
      }))
    }
  }, [])

  // URL 里带 conversation 时直接打开该会话；切换会话时清空残留详情、草稿与流状态。
  useEffect(() => {
    setDraft('')
    setMessagesLimit(MESSAGE_PAGE_SIZE)
    setStreamRunId(undefined)
    setPanel('none')
    // P2c-4 §2.5：跨会话不携带「原结构化调用」（一键重做只在**本页当次**持有原件时可用）。
    setLastInvocation(null)
    // S1 第三款：换会话即忘掉上一次的聚焦（同一标识在新会话里应重新定位）。
    focusedRef.current = null
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
    void list.reload()
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
  // S1：已决议的审批也回到消息流（窄卡），与舞台 / 运行详情显示同一权威态。
  const decidedApprovals = approvals.items.filter((item) => item.status !== 'pending')

  // S1 第三款：通知带审批标识时**只做定位与高亮**——命中与否都以服务端返回的审批列表为准。
  const focusTarget = focusApprovalId && approvals.items.some((item) => item.approval_id === focusApprovalId) ? focusApprovalId : undefined
  useEffect(() => {
    // 同一个标识只滚一次（审批列表每次重取都会重跑本效果，否则会一直把页面拽回去）。
    if (!focusTarget || focusedRef.current === focusTarget) return
    focusedRef.current = focusTarget
    const node = rootRef.current?.querySelector<HTMLElement>(`[data-approval-id="${focusTarget}"]`)
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focusTarget])
  // 带了标识却对不上：如实说明（本页只展示**最近一次运行**的审批），不留「跳过来什么都没有」的死角。
  // 判定要等**运行解析完**：回放读端还在连接（streaming）时不下结论，避免误报「没找到」。
  const focusMissing =
    Boolean(focusApprovalId) &&
    !focusTarget &&
    !approvals.loading &&
    (Boolean(effectiveRunId) || stream.status === 'closed' || stream.status === 'error')

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

  const forbidden = list.error?.status === 403
  const archived = state.detail?.status !== 'active'
  const canSend = draft.trim().length > 0 && !state.sending && !archived
  const draftInvocation = parseToolInvocation(draft)

  // 「本会话能力」里的工具画像：从**本次运行的真实帧**里取出现过的工具键（不虚构清单）。
  const seenTools = Array.from(
    new Set(
      stream.frames
        .filter((frame) => frame.kind === 'tool.call')
        .map((frame) => String(frame.payload.tool_key ?? frame.payload.tool ?? '').trim())
        .filter(Boolean),
    ),
  )

  const startConversation = async () => {
    setCreating(true)
    setState((old) => ({ ...old, createError: null }))
    try {
      // 新建会话不需要选入员工：agent_key 缺省即用默认员工。
      const created = await createConversation({})
      await list.reload()
      onSelectConversation(created.conversation_id)
    } catch (error) {
      setState((old) => ({ ...old, createError: asConversationError(error) }))
    } finally {
      setCreating(false)
    }
  }

  // S6 斜杠指令：只在**未发送**的输入上生效，命中即就地执行、不写消息表。
  const runSlashCommand = (raw: string): void => {
    const [command] = raw.split(/\s+/)
    if (command === '/new') {
      setPanel('none')
      void startConversation()
      setState((old) => ({ ...old, toast: '已新建对话（原来的会话还在左栏）' }))
      return
    }
    if (command === '/stop') {
      setPanel('none')
      if (streamActive) {
        // 只停**跟随**，不谎称取消了运行：运行仍在后台继续，刷新即可看最新进展。
        setStreamActive(false)
        setState((old) => ({ ...old, toast: '已停止跟随过程；运行仍在继续，点「刷新」可看最新进展' }))
      } else {
        setState((old) => ({ ...old, toast: '当前没有正在跟随的过程' }))
      }
      return
    }
    if (command === '/help') {
      setPanel('help')
      return
    }
    if (command === '/status') {
      setPanel('status')
      return
    }
    setState((old) => ({
      ...old,
      toast: `不认识的指令：${command}。可用：${SLASH_COMMANDS.map((item) => item.key).join(' ')}`,
    }))
  }

  const send = async (override?: string) => {
    // P2c-4 §2.5：`override` 只由**一键重做**传入（本页仍持有的原结构化调用原文）；
    // 重做走的是同一条正常发送路径 + **新幂等键** ⇒ 一次全新的调用（新 run），不改动原运行。
    const content = (override ?? draft).trim()
    if (!conversationId || !content) return
    if (!override && content.startsWith('/')) {
      setDraft('')
      runSlashCommand(content)
      return
    }
    if (!override && !canSend) return
    setPanel('none')
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
            streamNotice: '这次没有产生执行过程，回复由系统占位内容生成（所以看不到过程流）。',
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
      await list.reload()
      setState((old) => ({ ...old, sending: false, sendError: null }))
    } catch (error) {
      setState((old) => ({ ...old, sending: false, sendError: asConversationError(error) }))
    }
  }

  // P2c-4 §2.9：改模式（仅本人）。失败只提示，**不做本地乐观更新**（服务端权威态回流）。
  const changeMode = async (mode: ConversationMode) => {
    if (!conversationId || modeSaving) return
    if (state.detail?.mode === mode) {
      setPanel('none')
      return
    }
    setModeSaving(true)
    try {
      const updated = await setConversationMode(conversationId, mode)
      setState((old) => ({
        ...old,
        detail: old.detail ? { ...old.detail, mode: updated.mode, updated_at: updated.updated_at } : old.detail,
        toast: `已切换为「${conversationModeLabel(updated.mode)}」`,
      }))
      await list.reload()
      setPanel('none')
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
      '删除后：本会话的消息与执行过程会被彻底删除，无法恢复（仅限你自己的会话）；' +
        '会话标题会清空，运行记录与审计按合规口径保留。确认删除？',
    )
    if (confirmed === false) return
    setDeleting(true)
    try {
      const outcome = await deleteConversation(conversationId)
      setState((old) => ({
        ...old,
        toast: `已删除：消息 ${outcome.message_count} 条、执行过程记录 ${outcome.frame_count} 条`,
      }))
      setStreamActive(false)
      setLastInvocation(null)
      onSelectConversation(undefined)
      await list.reload()
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
    setState((old) => ({ ...old, exportError: null }))
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
          ? `已导出 ${payload.conversation_count} 个会话（数据量超过服务端上限，未包含全部；已在文件里注明不完整）`
          : `已导出 ${payload.conversation_count} 个会话 / ${payload.message_count} 条消息`,
      }))
    } catch (error) {
      setState((old) => ({ ...old, exportError: asConversationError(error) }))
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
      await list.reload()
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
  // 只有在**真的出现占位回复**时才提示（不常驻横幅）：与环境分支文案一致，开发术语不进生产产物。
  const hasStubReply = Boolean(detail?.messages.some((message) => message.role === 'assistant' && message.stub))
  const modeLabel = detail ? conversationModeLabel(detail.mode) : '—'

  const panelBody = () => {
    if (panel === 'mode') {
      return (
        <>
          <h3>
            本会话模式
            <button className="icon-btn" type="button" aria-label="关闭" onClick={() => setPanel('none')}>
              <Icon name="close" size={14} />
            </button>
          </h3>
          <div className="rows">
            {MODE_OPTIONS.map((mode) => (
              <button
                key={mode}
                className={`row ${detail?.mode === mode ? 'is-active' : ''}`}
                type="button"
                disabled={archived || modeSaving}
                aria-pressed={detail?.mode === mode}
                onClick={() => void changeMode(mode)}
              >
                <span className="row__main">
                  <span className="row__title">
                    {CONVERSATION_MODE_LABELS[mode]}
                    {detail?.mode === mode ? '（当前）' : ''}
                  </span>
                  <span className="row__sub">{CONVERSATION_MODE_HINTS[mode]}</span>
                </span>
              </button>
            ))}
          </div>
          <p className="form-field__hint">
            模式只决定「怎么执行」（是否允许真实执行、是否一律先待批），与审批档（谁批、批几档）是两件事，互不替代。
          </p>
        </>
      )
    }
    if (panel === 'ability') {
      return (
        <>
          <h3>
            本会话能力
            <button className="icon-btn" type="button" aria-label="关闭" onClick={() => setPanel('none')}>
              <Icon name="close" size={14} />
            </button>
          </h3>
          <div className="cmd-panel__row">
            <span className="cmd-panel__key">模式</span>
            <span>{detail ? `${modeLabel}：${CONVERSATION_MODE_HINTS[detail.mode]}` : '打开一个会话后显示。'}</span>
          </div>
          <div className="cmd-panel__row">
            <span className="cmd-panel__key">真实执行</span>
            <span>
              纯文本只当对话；要触发真实执行，需发送 <code>{'{"tool_key":"…","params":{…}}'}</code> 形式的结构化调用。
              是否执行、是否需要审批一律由服务端判定。
            </span>
          </div>
          <div className="cmd-panel__row">
            <span className="cmd-panel__key">本次运行的工具</span>
            <span>{seenTools.length > 0 ? seenTools.join('、') : '本次运行还没有工具调用记录（过程开始后会实时出现）。'}</span>
          </div>
          <p className="form-field__hint">
            执行人：{detail?.agent_key || '默认员工'}；参与者 {state.participantsTotal} 人。
          </p>
        </>
      )
    }
    if (panel === 'help') {
      return (
        <>
          <h3>
            指令说明
            <button className="icon-btn" type="button" aria-label="关闭" onClick={() => setPanel('none')}>
              <Icon name="close" size={14} />
            </button>
          </h3>
          {SLASH_COMMANDS.map((item) => (
            <div className="cmd-panel__row" key={item.key}>
              <span className="cmd-panel__key">{item.key}</span>
              <span>{item.what}</span>
            </div>
          ))}
          <p className="form-field__hint">在下面的输入框里以「/」开头输入即可；指令不会发送给服务端。</p>
        </>
      )
    }
    if (panel === 'status') {
      const rows: Array<{ label: string; value: string }> = [
        { label: '会话模式', value: modeLabel },
        { label: '消息', value: detail ? `${detail.messages.length} / ${detail.messages_total} 条` : '—' },
        { label: '执行人', value: detail?.agent_key || '默认员工' },
        {
          label: '当前运行',
          value: effectiveRunId
            ? `${effectiveRunId}${overview.metrics ? ` · ${runStatusLabel(overview.metrics.status)}` : ''}`
            : '暂无（还没跑过结构化调用）',
        },
        { label: '待你审批', value: `${pendingApprovals.length} 项` },
        { label: '过程帧', value: `${stream.frames.length} 条 · ${stream.status === 'streaming' ? '跟随中' : stream.status === 'closed' ? '已结束' : stream.status === 'error' ? '连接出错' : '未开启'}` },
        { label: '参与者', value: `${state.participantsTotal} 人` },
        { label: '最近更新', value: detail ? relativeTime(detail.updated_at) : '—' },
      ]
      return (
        <>
          <h3>
            当前会话状态
            <button className="icon-btn" type="button" aria-label="关闭" onClick={() => setPanel('none')}>
              <Icon name="close" size={14} />
            </button>
          </h3>
          {rows.map((row) => (
            <div className="cmd-panel__row" key={row.label}>
              <span className="cmd-panel__key">{row.label}</span>
              <span>{row.value}</span>
            </div>
          ))}
        </>
      )
    }
    return null
  }

  return (
    <>
      <main className="chat-page" ref={rootRef}>
        {state.createError && (
          <div className="chat__notices">
            <div className="notice notice-error" role="alert">
              <div><strong>新建对话失败</strong><p>{state.createError.message}</p></div>
              {state.createError.retryable && <button className="text-action" type="button" onClick={() => void startConversation()}>重新尝试</button>}
            </div>
          </div>
        )}

        {state.exportError && (
          <div className="chat__notices">
            <div className="notice notice-error" role="alert">
              <div><strong>导出没有完成</strong><p>{state.exportError.message}</p></div>
              {state.exportError.retryable && <button className="text-action" type="button" onClick={() => void exportMine()}>重新尝试</button>}
            </div>
          </div>
        )}

        {forbidden ? (
          <div className="chat__notices">
            <div className="notice notice-error" role="alert">
              <div><strong>无法使用对话</strong><p>{list.error?.message}</p></div>
            </div>
          </div>
        ) : !conversationId ? (
          <div className="chat__empty">
            <EmptyState
              illustration="chat"
              title="选择一个会话查看消息"
              text="在左栏的会话列表里点一个会话，就能看到消息记录并继续对话；也可以直接点左栏顶部的「新建对话」开始。"
            >
              <button className="btn btn--primary" type="button" disabled={creating} onClick={() => void startConversation()}>
                {creating ? '正在新建…' : '新建对话'}
              </button>
            </EmptyState>
          </div>
        ) : (
          <>
            {state.detailLoading && !detail && (
              <div className="chat__notices">
                <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话内容…</div>
              </div>
            )}

            {!state.detailLoading && state.detailError && (
              <div className="chat__notices">
                <div className="notice notice-error" role="alert">
                  <div><strong>会话加载失败</strong><p>{state.detailError.message}</p></div>
                  {state.detailError.retryable && <button className="text-action" type="button" onClick={() => void loadDetail(conversationId, messagesLimit)}>重新尝试</button>}
                </div>
              </div>
            )}

            {detail && (
              <div className="chat">
                <div className="chat__main">
                  <div className="chat-head">
                    <span className="chat-head__title" title={conversationTitle(detail.title)}>{conversationTitle(detail.title)}</span>
                    <span className={`badge ${detail.status === 'active' ? 'badge--accent' : ''}`}>{conversationStatusLabel(detail.status)}</span>
                    <span className="chat-head__meta">共 {detail.messages_total} 条消息 · 更新于 {relativeTime(detail.updated_at)}</span>
                    <div className="chat-head__actions">
                      <button
                        className="stage-toggle btn btn--secondary btn--sm"
                        type="button"
                        aria-expanded={stageOpen}
                        onClick={() => setStageOpen((value) => !value)}
                      >
                        {stageOpen ? '收起过程与运行' : '展开过程与运行'}
                      </button>
                      <button className="btn btn--secondary btn--sm" type="button" disabled={archived || state.archiving} onClick={() => void archive()}>
                        {state.archiving ? '归档中…' : '归档'}
                      </button>
                      <button className="btn btn--ghost btn--sm" type="button" disabled={forbidden || exporting} onClick={() => void exportMine()}>
                        {exporting ? '正在导出…' : '导出'}
                      </button>
                      <button className="btn btn--danger btn--sm" type="button" disabled={deleting} onClick={() => void remove()}>
                        {deleting ? '正在删除…' : '删除'}
                      </button>
                    </div>
                  </div>

                  {hasStubReply && (
                    <div className="chat__notices">
                      <div className="notice" role="note">
                        <div>
                          <strong>能力说明</strong>
                          <p>
                            {/* 开发态文案写成**内联字面量**：生产构建会把整个分支折叠掉，开发术语不会进产物（D-01）。 */}
                            {import.meta.env.DEV
                              ? '【开发态】助手回复是确定性桩回复，仅用于打通会话 / 权限 / 审计链路，请勿当作真实模型输出。' // ui-copy:dev-only
                              : '数字员工尚未接入真实模型，当前回复由系统占位内容生成；开通后自动切换，无需重新配置。'}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  {detail.messages.length === 0 ? (
                    <div className="messages">
                      <EmptyState
                        illustration="chat"
                        title="这个会话还没有消息"
                        text="在下方输入框发送第一条消息；需要真实执行时，服务端会先请求你的审批。"
                      />
                    </div>
                  ) : (
                    <div className="messages" aria-label="会话消息">
                      {detail.messages.map((message) => {
                        const system = message.role === 'system'
                        const mine = message.role === 'user'
                        return (
                          <article
                            className={`msg ${system ? 'msg--system' : mine ? 'msg--me' : 'msg--them'}`}
                            key={message.message_id}
                          >
                            <div className="bubble">{message.content}</div>
                            <div className="msg__meta">
                              <span>{speakerLabel(message, state.participants)}</span>
                              {message.tool_name && <span className="kbd">{message.tool_name}</span>}
                              {message.role === 'assistant' && message.stub && <span className="badge badge--warn">占位回复</span>}
                              <span>{formatMessageTime(message.created_at)}</span>
                            </div>
                          </article>
                        )
                      })}
                    </div>
                  )}

                  <ProcessBar frames={stream.frames} status={stream.status} error={stream.error} noData={stream.noData} />

                  <ArtifactChips
                    frames={stream.frames}
                    runId={effectiveRunId}
                    onOpenRunDetail={(runId) => onNavigate?.('run', undefined, runId)}
                  />

                  {focusMissing && (
                    <div className="chat__block">
                      <div className="notice" role="note">
                        <div>
                          <strong>没有定位到那条审批</strong>
                          <p>
                            这条通知指向的审批不在本会话当前展示的运行里（可能是更早的一次运行——这里只显示最近一次运行）；
                            到运行详情里可以按运行号查看历史。
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  {pendingApprovals.length > 0 && (
                    <div className="chat__block" aria-label="待审批">
                      {pendingApprovals.map((approval) => (
                        <div
                          className={`flow-card${focusTarget === approval.approval_id ? ' flow-card--focus' : ''}`}
                          key={approval.approval_id}
                          data-approval-id={approval.approval_id}
                        >
                          {focusTarget === approval.approval_id && (
                            <p className="flow-card__focus-note" role="note">已按通知定位到这条审批</p>
                          )}
                          <ApprovalCard
                            approval={approval}
                            canDecide={canDecide}
                            deciding={approvals.decidingId === approval.approval_id}
                            onDecide={(approved) => void handleDecide(approval.approval_id, approved)}
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  {decidedApprovals.length > 0 && (
                    <div className="chat__block" aria-label="已处理的审批">
                      {decidedApprovals.map((approval) => (
                        <div
                          className={`flow-card${focusTarget === approval.approval_id ? ' flow-card--focus' : ''}`}
                          key={approval.approval_id}
                          data-approval-id={approval.approval_id}
                        >
                          {focusTarget === approval.approval_id && (
                            <p className="flow-card__focus-note" role="note">已按通知定位到这条审批</p>
                          )}
                          <ApprovalCard approval={approval} canDecide={false} deciding={false} onDecide={() => {}} compact />
                        </div>
                      ))}
                    </div>
                  )}

                  {detail.messages.length < detail.messages_total && (
                    <div className="chat__pagination">
                      <button className="btn btn--secondary btn--sm" type="button" disabled={state.detailLoading} onClick={loadMoreMessages}>
                        加载更多消息
                      </button>
                      <span>已显示 {detail.messages.length} / {detail.messages_total}</span>
                    </div>
                  )}

                  <div className="chat__composer">
                    <div className="composer-wrap">
                      {panel !== 'none' && <div className="cmd-panel" role="dialog" aria-label="输入辅助面板">{panelBody()}</div>}
                      <form
                        className="composer"
                        onSubmit={(event) => {
                          event.preventDefault()
                          void send()
                        }}
                      >
                        <textarea
                          className="composer__input"
                          aria-label="消息内容"
                          placeholder={archived ? '会话已归档，不能发送新消息' : '接着说… 输入「/」可看指令（/new /stop /help /status）'}
                          rows={2}
                          maxLength={MAX_MESSAGE_LENGTH}
                          value={draft}
                          disabled={archived}
                          onChange={(event) => setDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                              event.preventDefault()
                              void send()
                            }
                            if (event.key === 'Escape' && panel !== 'none') setPanel('none')
                          }}
                        />
                        <div className="composer__bar">
                          <button className="composer__field" type="button" onClick={() => setPanel((value) => (value === 'mode' ? 'none' : 'mode'))}>
                            模式：<strong>{modeLabel}</strong>
                          </button>
                          <button className="composer__field" type="button" onClick={() => setPanel((value) => (value === 'ability' ? 'none' : 'ability'))}>
                            本会话能力
                          </button>
                          <button className="composer__field" type="button" onClick={() => setPanel((value) => (value === 'help' ? 'none' : 'help'))}>
                            指令
                          </button>
                          <span className="composer__field">
                            {draftInvocation
                              ? detail.mode === 'ask'
                                ? `结构化调用：${draftInvocation.tool_key}（当前为「只问答」，服务端会拒绝执行）`
                                : detail.mode === 'plan'
                                  ? `结构化调用：${draftInvocation.tool_key}（当前为「先计划后执行」，一律先落待批）`
                                  : `结构化调用：${draftInvocation.tool_key}（按真实执行路径发送）`
                              : `最长 ${MAX_MESSAGE_LENGTH} 字符 · 纯文本不触发真实执行`}
                          </span>
                          <button className="composer__send" type="submit" disabled={!canSend} aria-label="发送消息">
                            <Icon name="send" size={17} />
                          </button>
                        </div>
                      </form>
                    </div>

                    {archived && (
                      <div className="notice" role="status">
                        <div><strong>会话已归档</strong><p>归档后不能再发送新消息，历史消息仍可查看；如需继续对话，请新建对话。</p></div>
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
                </div>

                <StagePanel
                  runId={effectiveRunId}
                  stream={stream}
                  overview={overview}
                  approvals={approvalsView}
                  artifacts={artifacts}
                  acceptance={acceptance}
                  mode={detail.mode}
                  redoAvailable={Boolean(lastInvocation)}
                  onRedo={() => {
                    if (lastInvocation) void send(lastInvocation)
                  }}
                  canDecide={canDecide}
                  expanded={stageOpen}
                  onOpenRunDetail={(runId) => onNavigate?.('run', undefined, runId)}
                  // S4：干预动作（暂停 / 恢复 / 取消）——发起人本人或 CEO / 超管可操作，服务端仍是权威。
                  canIntervene={overview.isInitiator || role === 'ceo' || role === 'super_admin'}
                  onNotice={(message) => setState((old) => ({ ...old, toast: message }))}
                  // P2c-6：参与者与分享（舞台呈现；数据与增删回调都由本页提供，舞台只渲染）。
                  collaboration={{
                    items: state.participants,
                    total: state.participantsTotal,
                    lastActivityAt: detail.updated_at,
                    loading: state.participantsLoading,
                    error: state.shareError?.message ?? state.participantsError?.message ?? null,
                    sharing: state.sharing,
                    onAdd: (memberId, permission) => void shareMember(memberId, permission),
                    onRemove: (memberId) => void revokeMember(memberId),
                  }}
                />
              </div>
            )}
          </>
        )}
      </main>
      <Toast message={state.toast} />
    </>
  )
}