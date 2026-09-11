import { useCallback, useState } from 'react'
import { clearSession, isSessionExpired, loadSession, type Session } from './session'
import { LoginPage } from '../features/session/LoginPage'
import { ApprovalsPage } from '../features/approvals/ApprovalsPage'
import { InboxSection } from '../features/inbox/InboxSection'
import type { PendingApprovalCounts } from '../features/approvals/types'

const EMPTY_COUNTS: PendingApprovalCounts = {
  task_approval: 0,
  plan_proposal: 0,
  account_registration: 0,
  run_approval: 0,
  total: 0,
}

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

  const handleLogout = useCallback(() => {
    clearSession()
    setSession(null)
    setCounts(EMPTY_COUNTS)
  }, [])

  if (!session) return <LoginPage onAuthenticated={setSession} />

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <h1 className="app-shell__title">审批与提醒</h1>
        <span className="app-shell__badge" aria-label={`待办 ${counts.total} 项`}>
          {counts.total}
        </span>
        <button type="button" className="app-shell__logout" onClick={handleLogout}>
          退出登录
        </button>
      </header>
      <ApprovalsPage onSessionExpired={handleLogout} onCountsChange={setCounts} />
      <InboxSection onSessionExpired={handleLogout} />
    </div>
  )
}
