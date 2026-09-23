/**
 * 对话页 —— 由 `admin-web/src/features/conversation/ConversationPage.tsx`（966 行）**合并移植**。
 *
 * ⚠️ **本轮是"新写"而不是逐行翻译**（如实登记，原因见下）——
 * 原页是**手写 CSS + 老壳两栏假设**（70+ 处 className、自持右栏），
 * 而基座要 AntD + 三栏壳。逐行翻译会同时背离两边。故按**原契约行为**重写，逐条对应：
 *
 * | 原契约行为 | 本实现 |
 * | --- | --- |
 * | 左侧会话列表与会话页读**同一份**状态（前端真源 §2.17.3） | `useConversationList()`（`listStore`，单一可信来源） |
 * | **结构化**内容（`{"tool_key":...,"params":{...}}`）⇒ 带 `Idempotency-Key` 走 `messages:stream`（真实执行 + 幂等） | `parseToolInvocation` 判定 ⇒ `sendConversationMessageStream` |
 * | **非结构化**内容 ⇒ 普通端点（后端走 `stub` 桩回复，界面**原样标注桩**） | `sendConversationMessage` |
 * | `202` 待批响应**不含 reply** ⇒ 重取详情即可看到落库消息 | 发送后一律重取详情 |
 * | 发送后流读端要**重新发现新 run** | `restartToken` 递增 ⇒ `useRunStream` 重连 |
 * | 右侧舞台展示运行概览 / 过程 / 审批 / 产物 | `StagePanel`（按用户裁决**照搬**，不做"交给壳右栏"） |
 *
 * ⚠️ **本轮未带过来的（如实登记，不是漏做）**：会话归档 / 物理删除 / 模式切换 / 成员增删 / 导出
 * ——服务层（`conversationService`）**已全部就位并有用例**，只是本页暂时没接这些入口。
 * 它们各自都需要二次确认或表单，值得单独一轮，不宜塞进本轮的"让对话先跑起来"。
 *
 * 纪律：**四态齐备**；失败**不谎报成功**；桩回复**原样标注**（`stub: true` ⇒ 明确告知不是真实模型输出）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Typography } from 'antd'
import { ContentState, DangerConfirm, EmptyState, PageContainer, SkeletonList, StatusTag } from '../../components'
import { tokens } from '../../theme/tokens'
import { asConversationError } from './state'
import type { ConversationErrorShape } from './types'
import { CONVERSATION_PAGE_SIZE, MESSAGE_PAGE_SIZE, CONVERSATION_MODE_LABELS, conversationModeLabel } from './types'
import type { ConversationMember, ConversationMode, MemberPermission } from './types'
import { parseToolInvocation } from './invocation'
import { useConversationList } from './listStore'
import {
  addConversationMember,
  archiveConversation,
  deleteConversation,
  exportMyConversations,
  getConversation,
  listConversationMembers,
  removeConversationMember,
  sendConversationMessage,
  sendConversationMessageStream,
  setConversationMode,
} from './services/conversationService'
import type { CollaborationPanelState } from '../stage/ParticipantPanel'
import { useRunAcceptance } from '../stage/useRunAcceptance'
import { useRunApprovals } from '../stage/useRunApprovals'
import { useRunArtifacts } from '../stage/useRunArtifacts'
import { useRunOverview } from '../stage/useRunOverview'
import { StagePanel } from '../stage/StagePanel'
import { useRunStream } from './useRunStream'
import { useSlotVisible } from './useSlotVisible'
import { formatDateTime } from '../../utils/format'

/** 每次点击生成一个新幂等键：同一次点击重放由服务端返回既有结果，不重复执行。 */
function newSendKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `send-${crypto.randomUUID()}`
  }
  return `send-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const ROLE_LABEL: Record<string, string> = {
  user: '你',
  assistant: '数字员工',
  tool: '工具',
  system: '系统',
}

export function ConversationPage() {
  const list = useConversationList()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<ConversationErrorShape | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [restartToken, setRestartToken] = useState(0)

  const [detail, setDetail] = useState<Awaited<ReturnType<typeof getConversation>> | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<ConversationErrorShape | null>(null)

  /* ---- 会话管理：归档 / 删除 / 模式 / 成员 / 导出（2026-09-23 接入口） ---- */
  const [managing, setManaging] = useState(false)
  const [manageError, setManageError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<'archive' | 'delete' | null>(null)
  const [members, setMembers] = useState<ConversationMember[]>([])
  const [membersTotal, setMembersTotal] = useState(0)
  const [membersLoading, setMembersLoading] = useState(false)
  const [membersError, setMembersError] = useState<string | null>(null)
  const [sharing, setSharing] = useState(false)

  const slotRef = useRef<HTMLDivElement | null>(null)
  // B3 §4「切走即断」：槽不可见时**主动断开流**（不做后台堆积长连接）。
  // ⚠️ 基座壳暂无 `.view-slot` 标记 ⇒ 目前只按浏览器标签页可见性判断（优雅降级，见该文件注释）。
  const slotVisible = useSlotVisible(slotRef)

  const loadDetail = useCallback(async (conversationId: string) => {
    setDetailLoading(true)
    setDetailError(null)
    try {
      const loaded = await getConversation(conversationId, { limit: MESSAGE_PAGE_SIZE, offset: 0 })
      setDetail(loaded)
    } catch (error) {
      setDetail(null)
      setDetailError(asConversationError(error))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!activeId) {
      setDetail(null)
      setRunId(null)
      return
    }
    setRunId(null)
    void loadDetail(activeId)
  }, [activeId, loadDetail])

  // 列表首次加载完成后自动选中第一条（没有选中项时不摆空白）。
  useEffect(() => {
    if (activeId === null && list.conversations.length > 0) setActiveId(list.conversations[0].conversation_id)
  }, [activeId, list.conversations])

  const stream = useRunStream({
    conversationId: activeId ?? undefined,
    runId: runId ?? undefined,
    enabled: Boolean(activeId) && slotVisible,
    restartToken,
  })

  const overview = useRunOverview(runId ?? undefined, restartToken)
  const approvals = useRunApprovals(runId ?? undefined)
  const artifacts = useRunArtifacts(runId ?? undefined, restartToken)
  const acceptance = useRunAcceptance(runId ?? undefined, restartToken)

  /** 每次管理动作后**重取详情与列表**（以服务端回读为准，不做本地乐观更新）。 */
  const refresh = useCallback(async () => {
    if (!activeId) return
    await loadDetail(activeId)
    await list.reload()
  }, [activeId, loadDetail, list])

  const loadMembers = useCallback(async (conversationId: string) => {
    setMembersLoading(true)
    setMembersError(null)
    try {
      const data = await listConversationMembers(conversationId)
      setMembers(Array.isArray(data.items) ? data.items : [])
      setMembersTotal(typeof data.total === 'number' ? data.total : 0)
    } catch (error) {
      setMembers([])
      setMembersTotal(0)
      setMembersError(asConversationError(error).message)
    } finally {
      setMembersLoading(false)
    }
  }, [])

  // 会话详情就绪后再拉参与者（**不与详情并行**：详情失败时没必要再打一发）
  useEffect(() => {
    if (activeId && detail) void loadMembers(activeId)
  }, [activeId, detail, loadMembers])

  /** 统一的管理动作：失败**如实就地呈现**，不清空已有内容。 */
  const manage = async (label: string, run: () => Promise<void>) => {
    setManaging(true)
    setManageError(null)
    setNotice(null)
    try {
      await run()
      setNotice(`${label}已完成。`)
    } catch (error) {
      setManageError(asConversationError(error).message)
    } finally {
      setManaging(false)
    }
  }

  const createConversation = async () => {
    setSendError(null)
    try {
      const id = await list.create()
      setActiveId(id)
    } catch (error) {
      setSendError(asConversationError(error))
    }
  }

  const send = async () => {
    if (!activeId || draft.trim().length === 0) return
    const content = draft
    setSending(true)
    setSendError(null)
    setNotice(null)
    try {
      const invocation = parseToolInvocation(content)
      if (invocation) {
        // **结构化调用** ⇒ 流路径 + 幂等键（真实执行；同键重放返回既有结果）
        const result = await sendConversationMessageStream(activeId, content, newSendKey())
        setRunId(result.runId)
        if (result.body.status === 'pending_approval') {
          setNotice('这次调用需要人工审批，已提交；审批通过后才会继续执行。')
        } else if (result.body.stub) {
          // 桩回复**必须原样标注**，不得伪装成真实模型输出
          setNotice('本次为桩回复（后端未接真实模型），仅用于链路验证。')
        }
      } else {
        const body = await sendConversationMessage(activeId, content)
        if (body.status === 'pending_approval') {
          setNotice('这条消息需要人工审批，已提交；审批通过后才会继续执行。')
        } else if (body.stub) {
          setNotice('本次为桩回复（后端未接真实模型），仅用于链路验证。')
        }
      }
      setDraft('')
      // 202 待批响应不含 reply ⇒ 一律重取详情（以服务端回读为准，不做本地乐观插入）
      await loadDetail(activeId)
      setRestartToken((value) => value + 1)
    } catch (error) {
      setSendError(asConversationError(error))
    } finally {
      setSending(false)
    }
  }

  const listState: 'loading' | 'error' | 'empty' | 'ready' = list.loading
    ? 'loading'
    : list.error
      ? 'error'
      : list.conversations.length === 0
        ? 'empty'
        : 'ready'

  const messages = useMemo(() => detail?.messages ?? [], [detail])

  /** 参与者面板的数据与回调（`ParticipantPanel` 是**已移植好的展示组件**，这里只供数据）。 */
  const collaboration: CollaborationPanelState | undefined = activeId
    ? {
        items: members,
        total: membersTotal,
        lastActivityAt: detail?.updated_at ?? null,
        loading: membersLoading,
        error: membersError,
        sharing,
        onAdd: (memberId: string, permission: MemberPermission) =>
          void (async () => {
            setSharing(true)
            setMembersError(null)
            try {
              await addConversationMember(activeId, memberId, permission)
              await loadMembers(activeId) // 以服务端回读为准
            } catch (error) {
              setMembersError(asConversationError(error).message)
            } finally {
              setSharing(false)
            }
          })(),
        onRemove: (memberId: string) =>
          void (async () => {
            setSharing(true)
            setMembersError(null)
            try {
              await removeConversationMember(activeId, memberId)
              await loadMembers(activeId)
            } catch (error) {
              setMembersError(asConversationError(error).message)
            } finally {
              setSharing(false)
            }
          })(),
      }
    : undefined

  return (
    <PageContainer
      title="对话"
      description="对话是**唯一创建入口**：说清要什么，数字员工去做；右侧舞台看它做到哪一步。"
      extra={
        <Space wrap>
          <Button onClick={() => void createConversation()}>新建对话</Button>
          {activeId && detail && (
            <>
              <Select<ConversationMode>
                aria-label="会话模式"
                size="small"
                value={detail.mode}
                disabled={managing}
                onChange={(mode: ConversationMode) =>
                  void manage('切换模式', async () => {
                    await setConversationMode(activeId, mode)
                    await refresh()
                  })
                }
                options={(Object.keys(CONVERSATION_MODE_LABELS) as ConversationMode[]).map((mode) => ({
                  value: mode,
                  label: CONVERSATION_MODE_LABELS[mode],
                }))}
              />
              <Button size="small" disabled={managing} onClick={() => setConfirming('archive')}>
                归档
              </Button>
              <Button size="small" danger disabled={managing} onClick={() => setConfirming('delete')}>
                删除
              </Button>
              <Button
                size="small"
                disabled={managing}
                onClick={() =>
                  void manage('导出', async () => {
                    const bundle = await exportMyConversations()
                    // 载荷**只进文件**，不渲染到界面上
                    const blob = new Blob([JSON.stringify(bundle.pages, null, 2)], { type: 'application/json' })
                    const url = URL.createObjectURL(blob)
                    const anchor = document.createElement('a')
                    anchor.href = url
                    anchor.download = '我的会话导出.json'
                    document.body.append(anchor)
                    anchor.click()
                    anchor.remove()
                    URL.revokeObjectURL(url)
                    // 截断**如实告知**，不静默丢
                    if (bundle.truncated) setNotice('导出已完成，但服务端告知已达上限、**未取全**（包内为前若干页）。')
                  })
                }
              >
                导出
              </Button>
            </>
          )}
        </Space>
      }
    >
      <div ref={slotRef} style={{ display: 'flex', gap: tokens.spacing.md, minHeight: 480, alignItems: 'flex-start' }}>
        {/* ---------- 左：会话列表（与会话页读同一份状态） ---------- */}
        <Card
          size="small"
          title="会话"
          style={{ width: 260, flexShrink: 0 }}
        >
          {listState === 'loading' && <SkeletonList rows={3} state="loading" boxed={false} />}
          {listState === 'error' && (
            <ContentState
              state={list.error?.status === 403 ? 'forbidden' : 'error'}
              description={list.error?.message}
              onRetry={list.error?.retryable ? () => void list.reload() : undefined}
              boxed={false}
            />
          )}
          {listState === 'empty' && <EmptyState boxed={false} description="还没有会话：点右上角「新建对话」开始。" />}
          {listState === 'ready' && (
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              {list.conversations.map((item) => (
                <Button
                  key={item.conversation_id}
                  block
                  type={item.conversation_id === activeId ? 'primary' : 'default'}
                  onClick={() => setActiveId(item.conversation_id)}
                  style={{ textAlign: 'left' }}
                >
                  {item.title || '（未命名会话）'}
                </Button>
              ))}
              {list.total > list.conversations.length && (
                <Typography.Text type="secondary">
                  {`共 ${list.total} 个，当前显示前 ${list.conversations.length} 个（每页 ${CONVERSATION_PAGE_SIZE}）。`}
                </Typography.Text>
              )}
            </Space>
          )}
        </Card>

        {/* ---------- 中：消息流 + 输入 ---------- */}
        <Card size="small" title="消息" style={{ flex: 1, minWidth: 0 }}>
          {!activeId && <EmptyState boxed={false} description="左侧选一个会话，或新建一个。" />}

          {activeId && detailLoading && <SkeletonList rows={4} state="loading" boxed={false} />}
          {activeId && !detailLoading && detailError && (
            <ContentState
              state={detailError.status === 403 ? 'forbidden' : 'error'}
              description={detailError.message}
              onRetry={detailError.retryable ? () => void loadDetail(activeId) : undefined}
              boxed={false}
            />
          )}

          {activeId && detail && (
            <>
              <Space wrap size="small" style={{ marginBottom: tokens.spacing.sm }}>
                <Typography.Text type="secondary">{`模式：${conversationModeLabel(detail.mode)}`}</Typography.Text>
                {detail.status === 'archived' && <StatusTag tone="neutral">已归档</StatusTag>}
                <Typography.Text type="secondary">{`共 ${detail.messages_total} 条消息`}</Typography.Text>
              </Space>

              {messages.length === 0 && !detailLoading && !detailError && (
                <EmptyState boxed={false} description="还没有消息：在下面说清你要它做什么。" />
              )}

              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                {messages.map((message) => (
                  <article key={message.message_id}>
                    <Space size="small" wrap>
                      <Typography.Text strong>{ROLE_LABEL[message.role] ?? message.role}</Typography.Text>
                      {message.created_at && (
                        <Typography.Text type="secondary">{formatDateTime(message.created_at)}</Typography.Text>
                      )}
                      {/* 桩回复**原样标注**：不得让桩看起来像真实模型输出 */}
                      {message.stub && <StatusTag tone="warning">桩回复</StatusTag>}
                      {message.tool_name && <StatusTag tone="info">{message.tool_name}</StatusTag>}
                    </Space>
                    <div>
                      <Typography.Text>{message.content}</Typography.Text>
                    </div>
                  </article>
                ))}
              </Space>

              {notice && (
                <Alert style={{ marginTop: tokens.spacing.sm }} type="info" showIcon message={notice} closable onClose={() => setNotice(null)} />
              )}
              {sendError && (
                <Alert
                  style={{ marginTop: tokens.spacing.sm }}
                  type="error"
                  showIcon
                  message="发送未成功"
                  description={sendError.message}
                />
              )}
              {manageError && (
                <Alert
                  style={{ marginTop: tokens.spacing.sm }}
                  type="error"
                  showIcon
                  message="操作未生效"
                  description={manageError}
                  closable
                  onClose={() => setManageError(null)}
                />
              )}

              <Space.Compact style={{ width: '100%', marginTop: tokens.spacing.md }}>
                <Input.TextArea
                  value={draft}
                  rows={2}
                  placeholder='说清要做什么；也可以直接发结构化调用，如 {"tool_key":"cmd.run","params":{}}'
                  onChange={(event) => setDraft(event.target.value)}
                />
                <Button type="primary" loading={sending} disabled={draft.trim().length === 0} onClick={() => void send()}>
                  发送
                </Button>
              </Space.Compact>
              <Typography.Text type="secondary">
                结构化内容（`{'{'}"tool_key":…{'}'}`）会**真实执行**并带幂等键；普通内容走后端的桩回复，界面会明确标注"桩回复"。
                发送成功后一律**重新读取会话详情**（不做本地乐观插入）。
              </Typography.Text>
            </>
          )}
        </Card>

        {/* ---------- 右：舞台（按裁决**照搬**，不做"交给壳右栏"） ---------- */}
        <div style={{ width: 380, flexShrink: 0 }}>
          <StagePanel
            runId={runId ?? undefined}
            stream={stream}
            overview={overview}
            approvals={approvals}
            artifacts={artifacts}
            acceptance={acceptance}
            mode={detail?.mode}
            canDecide
            canIntervene
            onNotice={(message) => setNotice(message)}
            collaboration={collaboration}
          />
        </div>
      </div>

      {/* 归档：可逆（还能在「已归档」里找到）⇒ 勾选式确认即可 */}
      <DangerConfirm
        open={confirming === 'archive'}
        title="归档会话"
        description="归档后这个会话不能再发新消息（服务端会以 409 拒绝），但记录仍保留、可以查回。"
        acknowledgeText="我明白：归档后无法继续发送新消息"
        confirmText="归档"
        onCancel={() => setConfirming(null)}
        onConfirm={async () => {
          setConfirming(null)
          if (!activeId) return
          await manage('归档', async () => {
            await archiveConversation(activeId)
            await refresh()
          })
        }}
      />

      {/* 删除：**不可逆**（服务端是物理删除）⇒ 必须原样输入确认词 */}
      <DangerConfirm
        open={confirming === 'delete'}
        title="删除会话"
        description="这是**物理删除**本人会话的内容行，删除后列表 / 详情 / 流 / 发消息一律 404，且**无法恢复**。"
        confirmWord="删除"
        confirmText="删除"
        onCancel={() => setConfirming(null)}
        onConfirm={async () => {
          setConfirming(null)
          if (!activeId) return
          const removed = activeId
          await manage('删除', async () => {
            await deleteConversation(removed)
            setActiveId(null)
            setDetail(null)
            await list.reload()
          })
        }}
      />
    </PageContainer>
  )
}
