import { KnowledgeAccessPage } from '../features/knowledgeAccess/KnowledgeAccessPage'
import { ContentWorkbenchPage } from '../features/contentWorkbench/ContentWorkbenchPage'
import { ContentHistoryPage } from '../features/contentHistory/ContentHistoryPage'
import { CollaborationDynamicsPage } from '../features/collaborationDynamics/CollaborationDynamicsPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { RunDetailPage } from '../features/runDetail/RunDetailPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { WorkforcePage } from '../features/workforce/WorkforcePage'
import type { AppView } from './AppShell'
import { useEffect, useState } from 'react'

function routeFromLocation() {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  const runId = params.get('run') || undefined
  const known = view === 'history' || view === 'knowledge' || view === 'dynamics' || view === 'inbox' || view === 'audit' || view === 'workforce'
  // 运行详情必须带 run 参数，否则回落到默认视图（没有运行列表可去）。
  const resolved = known ? view : view === 'run' && runId ? 'run' : 'workbench'
  return { view: resolved as AppView, taskId: params.get('task') || undefined, runId }
}

export default function App() {
  const [route, setRoute] = useState(routeFromLocation)
  useEffect(() => { const update = () => setRoute(routeFromLocation()); window.addEventListener('popstate', update); return () => window.removeEventListener('popstate', update) }, [])
  const navigate = (view: AppView, taskId?: string, runId?: string) => { const query = view === 'history' ? '?view=history' : view === 'knowledge' ? '?view=knowledge' : view === 'dynamics' ? '?view=dynamics' : view === 'inbox' ? '?view=inbox' : view === 'audit' ? '?view=audit' : view === 'workforce' ? '?view=workforce' : view === 'run' ? `?view=run&run=${encodeURIComponent(runId ?? '')}` : taskId ? `?task=${encodeURIComponent(taskId)}` : ''; window.history.pushState({}, '', query || window.location.pathname); window.dispatchEvent(new PopStateEvent('popstate')) }
  if (route.view === 'knowledge') return <KnowledgeAccessPage onNavigate={navigate} />
  if (route.view === 'dynamics') return <CollaborationDynamicsPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'history') return <ContentHistoryPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'inbox') return <InboxPage onOpenTask={(taskId) => navigate('workbench', taskId)} onOpenRun={(runId) => navigate('run', undefined, runId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'audit') return <AuditLogPage onNavigate={navigate} />
  if (route.view === 'workforce') return <WorkforcePage onNavigate={navigate} />
  if (route.view === 'run' && route.runId) return <RunDetailPage runId={route.runId} onNavigate={navigate} />
  return <ContentWorkbenchPage taskId={route.taskId} onNavigate={(view) => navigate(view)} />
}
