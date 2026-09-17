import { useCallback, useState } from 'react'
import { clearSession, isSessionExpired, loadSession, type Session } from './session'
import { LoginPage } from '../features/session/LoginPage'
import { ApprovalsPage } from '../features/approvals/ApprovalsPage'
import { InboxSection } from '../features/inbox/InboxSection'
import { ConversationPanel } from '../features/conversation/ConversationPanel'
import type { PendingApprovalCounts } from '../features/approvals/types'

const EMPTY_COUNTS: PendingApprovalCounts = {
  task_approval: 0,
  plan_proposal: 0,
  account_registration: 0,
  run_approval: 0,
  total: 0,
}

// 两个功能面（P2c-5）：待办（既有审批 + 提醒）与对话（新增面板）。
type AppTab = 'todo' | 'conversation'

function initialSession(): Session | null {
  const session = loadSession()
  if (!session) return null
  if (isSessionExpired(session, Date.now())) {
    clearSession()
    return null
  }
  return session
}

export default function App() {
  const [session, setSession] = useState<Session | null>(initialSession)
  const [counts, setCounts] = useState<PendingApprovalCounts>(EMPTY_COUNTS)
  const [tab, setTab] = useState<AppTab>('todo')

  const handleLogout = useCallback(() => {
    clearSession()
    setSession(null)
    setCounts(EMPTY_COUNTS)
    setTab('todo')
  }, [])

  if (!session) return <LoginPage onAuthenticated={setSession} />

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <h1 className="app-shell__title">工作台伴侣</h1>
        <span className="app-shell__badge" aria-label={`待办 ${counts.total} 项`}>
          {counts.total}
        </span>
        <button type="button" className="app-shell__logout" onClick={handleLogout}>
          退出登录
        </button>
      </header>
      <nav className="app-shell__tabs" role="tablist" aria-label="功能切换">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'todo'}
          className={tab === 'todo' ? 'app-shell__tab active' : 'app-shell__tab'}
          onClick={() => setTab('todo')}
        >
          待办
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'conversation'}
          className={tab === 'conversation' ? 'app-shell__tab active' : 'app-shell__tab'}
          onClick={() => setTab('conversation')}
        >
          对话
        </button>
      </nav>
      {/* 非激活标签不挂载：轮询与流读端随切换自然停止（手机端省电；回到标签即重新拉取）。 */}
      {tab === 'todo' ? (
        <>
          <ApprovalsPage onSessionExpired={handleLogout} onCountsChange={setCounts} />
          <InboxSection onSessionExpired={handleLogout} />
        </>
      ) : (
        <ConversationPanel onSessionExpired={handleLogout} />
      )}
    </div>
  )
}