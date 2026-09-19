import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import { EmptyState } from '../../components/ui/EmptyState'
import { relativeTime } from '../../utils/time'
import { PendingApprovalRows } from '../approvals/PendingApprovalsList'
import { usePendingApprovals } from '../approvals/usePendingApprovals'
import { useConversationList } from '../conversation/listStore'
import { conversationStatusLabel, conversationTitle } from '../conversation/types'
import { useSlotVisible } from '../conversation/useSlotVisible'
import { listInbox } from '../inbox/api'
import { inboxKindLabel } from '../inbox/types'
import { createHomeConversation, createHomeTask, listHomeConversations, listHomeEmployees, newIdempotencyKey, sendHomeMessage } from './api'
import { asHomeError, initialHomeState } from './state'
import {
  HOME_CONVERSATION_LIMIT,
  HOME_EXAMPLE_PROMPTS,
  HOME_INBOX_LIMIT,
  RISK_LABELS,
  type HomeRiskLevel,
  type HomeState,
} from './types'

const RISK_OPTIONS: HomeRiskLevel[] = ['low', 'medium', 'high', 'critical']

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 6) return '夜里好'
  if (hour < 12) return '上午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

/**
 * 工作台首页（模板 T1）：问候 + 示例 + 输入卡 + 今日指标 + 等你处理 + 最近的会话。
 *
 * 纪律：三块数据（数字员工 / 会话 / 未读通知）各自独立读取，任一侧失败只影响自己那一块；
 * 数字一律来自服务端（会话总数取 `total`、未读取 `unread_count`），不本地估。
 */
export function HomePage({
  onOpenConversation,
  onNavigate,
  onOpenTask,
  onOpenRun,
}: {
  onOpenConversation: (conversationId: string) => void
  onNavigate?: (view: AppView) => void
  /** S5：待办行的真实落点（由 App 注入，页面不自己拼 URL）。 */
  onOpenTask?: (taskId: string) => void
  onOpenRun?: (runId: string) => void
}) {
  const [state, setState] = useState<HomeState>(initialHomeState)
  const [message, setMessage] = useState('')
  const [agentKey, setAgentKey] = useState('')
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [title, setTitle] = useState('')
  const [taskAgentKey, setTaskAgentKey] = useState('')
  const [risk, setRisk] = useState<HomeRiskLevel>('low')

  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const rootRef = useRef<HTMLElement | null>(null)
  // 左栏与本页共用同一份会话列表状态：本页**写**（新建会话）后由它统一刷新（真源 §2.17.3）。
  const list = useConversationList()
  const visible = useSlotVisible(rootRef)
  // S5：待我审批（与员工页横幅同源；只在本页可见时轮询）。
  const pending = usePendingApprovals({ enabled: visible })
  const pendingCardRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    setState((old) => ({
      ...old,
      employeesLoading: true,
      employeesError: null,
      conversationsLoading: true,
      conversationsError: null,
      inboxLoading: true,
      inboxError: null,
    }))
    // 三个读取互不阻塞：任一侧失败只影响自己那一块。
    const [employees, conversations, inbox] = await Promise.allSettled([
      listHomeEmployees(),
      listHomeConversations(HOME_CONVERSATION_LIMIT),
      listInbox(true, HOME_INBOX_LIMIT),
    ])
    setState((old) => ({
      ...old,
      employees: employees.status === 'fulfilled' && Array.isArray(employees.value.items) ? employees.value.items : [],
      employeesLoading: false,
      employeesError: employees.status === 'rejected' ? asHomeError(employees.reason) : null,
      conversations: conversations.status === 'fulfilled' && Array.isArray(conversations.value.items) ? conversations.value.items : [],
      conversationsTotal: conversations.status === 'fulfilled' && typeof conversations.value.total === 'number' ? conversations.value.total : 0,
      conversationsLoading: false,
      conversationsError: conversations.status === 'rejected' ? asHomeError(conversations.reason) : null,
      inbox: inbox.status === 'fulfilled' && Array.isArray(inbox.value.items) ? inbox.value.items : [],
      inboxUnread: inbox.status === 'fulfilled' && typeof inbox.value.unread_count === 'number' ? inbox.value.unread_count : 0,
      inboxLoading: false,
      inboxError: inbox.status === 'rejected' ? asHomeError(inbox.reason) : null,
    }))
  }, [])

  // 视图槽常驻 ⇒ 只在挂载时读一次会一直显示陈旧数据：回到本页（或标签页重新可见）时重读。
  useEffect(() => {
    if (visible) void load()
  }, [visible, load])

  const usableEmployees = state.employees.filter((item) => item.status === 'active')

  // 默认选中首个启用中的数字员工；原选择被停用或删除时自动回落。
  useEffect(() => {
    const fallback = usableEmployees[0]?.agent_key ?? ''
    setAgentKey((current) => (usableEmployees.some((item) => item.agent_key === current) ? current : fallback))
    setTaskAgentKey((current) => (usableEmployees.some((item) => item.agent_key === current) ? current : fallback))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.employees])

  const canSend = message.trim().length > 0 && !state.submitting
  const canCreateTask = title.trim().length > 0 && taskAgentKey !== '' && !state.taskSubmitting

  // 第一句话即「创建会话 + 发送该消息」；两步都成功后跳转到该会话，失败只报错、不假装成功。
  const startConversation = async () => {
    const content = message.trim()
    if (!canSend || !content) return
    setState((old) => ({ ...old, submitting: true, submitError: null, toast: null }))
    try {
      const conversation = await createHomeConversation({ agentKey: agentKey || undefined, title: content.slice(0, 120) })
      await sendHomeMessage(conversation.conversation_id, content)
      setMessage('')
      setState((old) => ({ ...old, submitting: false }))
      // 左栏列表随后台统一刷新（否则「新建了但左栏还是旧条数」，得手点刷新）。
      void list.reload()
      onOpenConversation(conversation.conversation_id)
    } catch (error) {
      setState((old) => ({ ...old, submitting: false, submitError: asHomeError(error) }))
    }
  }

  const createTask = async () => {
    if (!canCreateTask) return
    setState((old) => ({ ...old, taskSubmitting: true, taskError: null, toast: null }))
    try {
      const task = await createHomeTask({
        title: title.trim(),
        employeeKey: taskAgentKey,
        riskLevel: risk,
        idempotencyKey: newIdempotencyKey(),
      })
      setTitle('')
      setState((old) => ({
        ...old,
        taskSubmitting: false,
        toast: task.status === 'pending_approval'
          ? `任务已创建并提交审批：${task.id}`
          : `任务已创建：${task.id}`,
      }))
    } catch (error) {
      setState((old) => ({ ...old, taskSubmitting: false, taskError: asHomeError(error) }))
    }
  }

  const fillExample = (prompt: string) => {
    setMessage(prompt)
    inputRef.current?.focus()
  }

  // S5：指标卡点开 = 滚到「等你拍板」并把焦点交给第一条真正可操作的按钮
  //（键盘用户可直接回车直达；卡片内没有可操作项时只滚动，不假装有动作）。
  const jumpToPending = () => {
    const card = pendingCardRef.current
    if (!card) return
    // jsdom 里没有 scrollIntoView（单测环境）：能用才滚，保证焦点行为可测。
    if (typeof card.scrollIntoView === 'function') card.scrollIntoView({ block: 'center' })
    card.querySelector<HTMLButtonElement>('button.btn')?.focus()
  }

  const hasPending = pending.counts.total > 0 && pending.items.length > 0
  const hasInbox = state.inbox.length > 0
  const todoLoading = pending.loading || state.inboxLoading

  return (
    <>
      <main className="home" ref={rootRef}>
        <section className="hero" aria-label="与数字员工对话">
          <h1>{greeting()}，今天让数字员工做点什么？</h1>
          <p className="hero__hint">说一句话就开一个会话，交给数字员工接着做；需要派活时也可以直接建任务。</p>

          <div className="chips" aria-label="试试这样问">
            {HOME_EXAMPLE_PROMPTS.map((prompt) => (
              <button className="chip" type="button" key={prompt} onClick={() => fillExample(prompt)}>
                <Icon name="plus" size={14} />
                {prompt}
              </button>
            ))}
          </div>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault()
              void startConversation()
            }}
          >
            <textarea
              className="composer__input"
              aria-label="想对数字员工说的话"
              placeholder="今天帮你做些什么？例如：把本周客户反馈整理成一页要点"
              value={message}
              rows={2}
              ref={inputRef}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void startConversation()
                }
              }}
            />
            <div className="composer__bar">
              <label className="composer__field">
                执行人
                <select
                  aria-label="执行人"
                  value={agentKey}
                  disabled={usableEmployees.length === 0}
                  onChange={(event) => setAgentKey(event.target.value)}
                >
                  {usableEmployees.length === 0 && <option value="">无可用执行人</option>}
                  {usableEmployees.map((item) => (
                    <option value={item.agent_key} key={item.agent_key}>{item.name}</option>
                  ))}
                </select>
              </label>
              <button className="composer__send" type="submit" disabled={!canSend} aria-label="开始对话">
                <Icon name="send" size={17} />
              </button>
            </div>
          </form>

          <div className="home__secondary">
            <button className="btn btn--ghost btn--sm" type="button" onClick={() => setShowTaskForm((value) => !value)}>
              {showTaskForm ? '收起建任务' : '或直接建任务'}
            </button>
          </div>

          {state.employeesLoading && <p className="hero__hint" role="status">正在读取可用的数字员工…</p>}

          {!state.employeesLoading && state.employeesError && (
            <div className="notice notice-error" role="alert">
              <div><strong>数字员工读取失败</strong><p>{state.employeesError.message}</p></div>
              {state.employeesError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          )}

          {!state.employeesLoading && !state.employeesError && usableEmployees.length === 0 && (
            <div className="notice" role="status">
              <div>
                <strong>还没有启用中的数字员工</strong>
                <p>先创建岗位与数字员工，这里才能派活；对话仍可按默认员工发起。</p>
              </div>
              {onNavigate && <button className="text-action" type="button" onClick={() => onNavigate('workforceSettings')}>去创建</button>}
            </div>
          )}

          {state.submitError && (
            <div className="notice notice-error" role="alert">
              <div><strong>会话创建失败</strong><p>{state.submitError.message}</p></div>
            </div>
          )}
        </section>

        {showTaskForm && (
          <form
            className="card"
            aria-label="直接建任务"
            onSubmit={(event) => {
              event.preventDefault()
              void createTask()
            }}
          >
            <div className="card__head">
              <h2>直接建任务</h2>
            </div>
            <div className="card__body">
              <div className="form-grid">
                <div className="form-field form-grid__wide">
                  <label htmlFor="home-task-title">任务描述</label>
                  <textarea
                    id="home-task-title"
                    aria-label="任务描述"
                    placeholder="用一句话描述要做的事，例如：整理本周客户反馈要点"
                    value={title}
                    rows={3}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="home-task-agent">执行人</label>
                  <select
                    id="home-task-agent"
                    aria-label="任务执行人"
                    value={taskAgentKey}
                    disabled={usableEmployees.length === 0}
                    onChange={(event) => setTaskAgentKey(event.target.value)}
                  >
                    {usableEmployees.length === 0 && <option value="">无可用执行人</option>}
                    {usableEmployees.map((item) => (
                      <option value={item.agent_key} key={item.agent_key}>{item.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label htmlFor="home-task-risk">风险等级</label>
                  <select
                    id="home-task-risk"
                    aria-label="风险等级"
                    value={risk}
                    onChange={(event) => setRisk(event.target.value as HomeRiskLevel)}
                  >
                    {RISK_OPTIONS.map((option) => (
                      <option value={option} key={option}>{RISK_LABELS[option]}</option>
                    ))}
                  </select>
                  <span className="form-field__hint">风险等级只作提示，是否需要审批由服务端判定。</span>
                </div>
              </div>

              {state.taskError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>任务创建失败</strong><p>{state.taskError.message}</p></div>
                </div>
              )}

              <div className="form-actions">
                <button className="btn btn--secondary" type="button" onClick={() => setShowTaskForm(false)}>取消</button>
                <button className="btn btn--primary" type="submit" disabled={!canCreateTask} aria-label="创建任务">
                  {state.taskSubmitting ? '正在创建…' : '创建任务'}
                </button>
              </div>
            </div>
          </form>
        )}

        <section aria-label="今天">
          <div className="section-title">
            <h2>今天</h2>
            <span>数字来自服务端，点一下可进入对应页面</span>
          </div>
          <div className="metrics">
            <button className="metric" type="button" onClick={() => onNavigate?.('conversation')}>
              <div className="metric__label">会话</div>
              <div className="metric__value">{state.conversationsLoading ? '—' : state.conversationsTotal}</div>
              <div className="metric__hint">左栏列表里的全部会话</div>
            </button>
            <button className="metric" type="button" onClick={() => onNavigate?.('workforce')}>
              <div className="metric__label">启用中的数字员工</div>
              <div className="metric__value">{state.employeesLoading ? '—' : usableEmployees.length}</div>
              <div className="metric__hint">可派活的执行人</div>
            </button>
            <button className={`metric ${state.inboxUnread > 0 ? 'metric--warn' : ''}`} type="button" onClick={() => onNavigate?.('inbox')}>
              <div className="metric__label">未读通知</div>
              <div className="metric__value">{state.inboxLoading ? '—' : state.inboxUnread}</div>
              <div className="metric__hint">运行结果、审批驳回、任务到期</div>
            </button>
            {/* S5：与员工页横幅同源（同一个聚合端点与 hook）；点开滚到「等你拍板」并聚焦第一项 */}
            <button className={`metric ${pending.counts.total > 0 ? 'metric--warn' : ''}`} type="button" onClick={jumpToPending}>
              <div className="metric__label">待我审批</div>
              <div className="metric__value">{pending.loading ? '—' : pending.counts.total}</div>
              <div className="metric__hint">任务 / 计划 / 运行内 / 账号注册</div>
            </button>
          </div>
        </section>

        <div className="home__cols">
          <section className="card" aria-label="等你拍板" ref={pendingCardRef}>
            <div className="card__head">
              <h2>等你拍板</h2>
              {onNavigate && (
                <button className="card__more" type="button" onClick={() => onNavigate('inbox')}>全部通知</button>
              )}
            </div>

            {pending.error && (
              <div className="card__body">
                <div className="notice notice-error" role="alert">
                  <div><strong>待办加载失败</strong><p>{pending.error.message}</p></div>
                  {pending.error.retryable && <button className="text-action" type="button" onClick={pending.reload}>重新尝试</button>}
                </div>
              </div>
            )}

            {hasPending && (
              <>
                <div className="rows-label">待我审批 {pending.counts.total} 项</div>
                <div className="rows">
                  <PendingApprovalRows items={pending.items} destinations={{ onOpenTask, onOpenRun }} />
                </div>
              </>
            )}

            {hasInbox && (
              <>
                <div className="rows-label">未读通知 {state.inboxUnread} 条</div>
                <div className="rows">
                  {state.inbox.map((item) => (
                    <button className="row" type="button" key={item.inbox_id} onClick={() => onNavigate?.('inbox')}>
                      <span className="row__main">
                        <span className="row__title">{item.title}</span>
                        <span className="row__sub">{inboxKindLabel(item.kind)}</span>
                      </span>
                      <span className="row__side">
                        <span className="row__time">{relativeTime(item.created_at)}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}

            {!hasPending && !hasInbox && todoLoading && <p className="card__body" role="status">正在加载待办…</p>}

            {!hasPending && !hasInbox && !todoLoading && (
              <EmptyState
                illustration="list"
                title="没有要你处理的事"
                text="审批、运行结果与任务到期这些事会送到这里；现在没有需要你处理的。"
              >
                <button className="btn btn--secondary btn--sm" type="button" onClick={() => onNavigate?.('inbox')}>去通知页看看</button>
              </EmptyState>
            )}

            {!state.inboxLoading && state.inboxError && (
              <div className="card__body">
                <div className="notice notice-error" role="alert">
                  <div><strong>通知加载失败</strong><p>{state.inboxError.message}</p></div>
                  {state.inboxError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
                </div>
              </div>
            )}
          </section>

          <section className="card" aria-label="最近的会话">
            <div className="card__head">
              <h2>最近的会话</h2>
              {onNavigate && (
                <button className="card__more" type="button" onClick={() => onNavigate('conversation')}>全部会话</button>
              )}
            </div>

            {state.conversationsLoading && <p className="card__body" role="status">正在加载会话…</p>}

            {!state.conversationsLoading && state.conversationsError && (
              <div className="card__body">
                <div className="notice notice-error" role="alert">
                  <div><strong>会话加载失败</strong><p>{state.conversationsError.message}</p></div>
                  {state.conversationsError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
                </div>
              </div>
            )}

            {!state.conversationsLoading && !state.conversationsError && state.conversations.length === 0 && (
              <EmptyState
                illustration="chat"
                title="还没有会话"
                text="在上面说第一句话，就会创建一个会话交给数字员工。"
              >
                <button className="btn btn--primary btn--sm" type="button" onClick={() => inputRef.current?.focus()}>去说第一句话</button>
              </EmptyState>
            )}

            {!state.conversationsLoading && !state.conversationsError && state.conversations.length > 0 && (
              <div className="rows">
                {state.conversations.map((item) => (
                  <button className="row" type="button" key={item.conversation_id} onClick={() => onOpenConversation(item.conversation_id)}>
                    <span className="row__main">
                      <span className="row__title">{conversationTitle(item.title)}</span>
                      <span className="row__sub">{conversationStatusLabel(item.status)}</span>
                    </span>
                    <span className="row__side">
                      <span className="row__time">{relativeTime(item.updated_at)}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
      <Toast message={state.toast} />
    </>
  )
}