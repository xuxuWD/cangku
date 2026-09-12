import { useCallback, useEffect, useState } from 'react'
import { AppShell, type AppView } from '../../app/AppShell'
import { Icon } from '../../components/Icon'
import { Toast } from '../../components/Toast'
import { createHomeConversation, createHomeTask, listHomeConversations, listHomeEmployees, newIdempotencyKey, sendHomeMessage } from './api'
import { asHomeError, initialHomeState } from './state'
import { HOME_CONVERSATION_LIMIT, RISK_LABELS, type HomeRiskLevel, type HomeState } from './types'
import { conversationStatusLabel, conversationTitle, formatMessageTime } from '../conversation/types'

const RISK_OPTIONS: HomeRiskLevel[] = ['low', 'medium', 'high']

export function HomePage({
  onOpenConversation,
  onNavigate,
}: {
  onOpenConversation: (conversationId: string) => void
  onNavigate?: (view: AppView) => void
}) {
  const [state, setState] = useState<HomeState>(initialHomeState)
  const [message, setMessage] = useState('')
  const [agentKey, setAgentKey] = useState('')
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [title, setTitle] = useState('')
  const [taskAgentKey, setTaskAgentKey] = useState('')
  const [risk, setRisk] = useState<HomeRiskLevel>('low')

  const load = useCallback(async () => {
    setState((old) => ({ ...old, employeesLoading: true, employeesError: null, conversationsLoading: true, conversationsError: null }))
    // 两个读取互不阻塞：任一侧失败只影响自己那一块。
    const [employees, conversations] = await Promise.allSettled([listHomeEmployees(), listHomeConversations(HOME_CONVERSATION_LIMIT)])
    setState((old) => ({
      ...old,
      employees: employees.status === 'fulfilled' && Array.isArray(employees.value.items) ? employees.value.items : [],
      employeesLoading: false,
      employeesError: employees.status === 'rejected' ? asHomeError(employees.reason) : null,
      conversations: conversations.status === 'fulfilled' && Array.isArray(conversations.value.items) ? conversations.value.items : [],
      conversationsLoading: false,
      conversationsError: conversations.status === 'rejected' ? asHomeError(conversations.reason) : null,
    }))
  }, [])

  useEffect(() => { void load() }, [load])

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

  return (
    <AppShell activeView="home" onNavigate={onNavigate}>
      <main className="main-content home">
        <section className="home-hero" aria-label="与数字员工对话">
          <h1 className="home-title">数字员工，我帮你</h1>
          <p className="home-subtitle">说一句话就开一个会话，交给数字员工接着聊；需要派活时也可以直接建任务。</p>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault()
              void startConversation()
            }}
          >
            <textarea
              className="composer-input"
              aria-label="想对数字员工说的话"
              placeholder="今天帮你做些什么？例如：整理本周客户反馈要点"
              value={message}
              rows={3}
              onChange={(event) => setMessage(event.target.value)}
            />
            <div className="composer-bar">
              <label className="composer-field">
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
              <button className="composer-send" type="submit" disabled={!canSend} aria-label="开始对话">
                <Icon name="chat" size={18} />
              </button>
            </div>
          </form>

          <div className="home-secondary">
            <button className="text-action" type="button" onClick={() => setShowTaskForm((value) => !value)}>
              {showTaskForm ? '收起建任务表单' : '或直接建任务'}
            </button>
          </div>

          {showTaskForm && (
            <form
              className="composer"
              aria-label="直接建任务"
              onSubmit={(event) => {
                event.preventDefault()
                void createTask()
              }}
            >
              <textarea
                className="composer-input"
                aria-label="任务描述"
                placeholder="用一句话描述要做的事，例如：整理本周客户反馈要点"
                value={title}
                rows={3}
                onChange={(event) => setTitle(event.target.value)}
              />
              <div className="composer-bar">
                <label className="composer-field">
                  执行人
                  <select
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
                </label>
                <label className="composer-field">
                  风险等级
                  <select
                    aria-label="风险等级"
                    value={risk}
                    onChange={(event) => setRisk(event.target.value as HomeRiskLevel)}
                  >
                    {RISK_OPTIONS.map((option) => (
                      <option value={option} key={option}>{RISK_LABELS[option]}</option>
                    ))}
                  </select>
                </label>
                <button className="composer-send" type="submit" disabled={!canCreateTask} aria-label="创建任务">
                  <Icon name="send" size={18} />
                </button>
              </div>
              {state.taskError && (
                <div className="notice notice-error" role="alert">
                  <div><strong>任务创建失败</strong><p>{state.taskError.message}</p></div>
                </div>
              )}
            </form>
          )}

          {state.employeesLoading && <p className="composer-hint" role="status">正在读取可用的数字员工…</p>}

          {!state.employeesLoading && state.employeesError && (
            <div className="notice notice-error" role="alert">
              <div><strong>数字员工读取失败</strong><p>{state.employeesError.message}</p></div>
              {state.employeesError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          )}

          {!state.employeesLoading && !state.employeesError && usableEmployees.length === 0 && (
            <div className="composer-hint composer-hint--empty">
              <strong>还没有启用中的数字员工</strong>
              <span>先创建岗位与数字员工，这里才能派活；对话仍可按默认员工发起。</span>
              {onNavigate && <button className="text-action" type="button" onClick={() => onNavigate('workforceSettings')}>去创建</button>}
            </div>
          )}

          {state.submitError && (
            <div className="notice notice-error" role="alert">
              <div><strong>会话创建失败</strong><p>{state.submitError.message}</p></div>
            </div>
          )}
        </section>

        <section className="home-drafts" aria-label="最近的会话">
          <div className="home-section-head">
            <h2>最近的会话</h2>
            {onNavigate && <button className="text-action" type="button" onClick={() => onNavigate('conversation')}>查看全部</button>}
          </div>

          {state.conversationsLoading && <div className="loading-state" role="status"><span className="loading-dot" />正在加载会话…</div>}

          {!state.conversationsLoading && state.conversationsError && (
            <div className="notice notice-error" role="alert">
              <div><strong>会话加载失败</strong><p>{state.conversationsError.message}</p></div>
              {state.conversationsError.retryable && <button className="text-action" type="button" onClick={() => void load()}>重新尝试</button>}
            </div>
          )}

          {!state.conversationsLoading && !state.conversationsError && state.conversations.length === 0 && (
            <div className="empty-state"><strong>还没有会话</strong><span>在上面说第一句话，就会创建一个会话。</span></div>
          )}

          {!state.conversationsLoading && !state.conversationsError && state.conversations.length > 0 && (
            <div className="home-card-grid">
              {state.conversations.map((item) => (
                <button className="home-card" type="button" onClick={() => onOpenConversation(item.conversation_id)} key={item.conversation_id}>
                  <span className="home-card-cover" aria-hidden="true"><Icon name="chat" size={22} /></span>
                  <span className="home-card-body">
                    <strong>{conversationTitle(item.title)}</strong>
                    <span className="home-card-meta">
                      <span className={`status-badge status-${item.status}`}>{conversationStatusLabel(item.status)}</span>
                      <span>更新于 {formatMessageTime(item.updated_at)}</span>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </main>
      <Toast message={state.toast} />
    </AppShell>
  )
}
