import { KnowledgeAccessPage } from '../features/knowledgeAccess/KnowledgeAccessPage'
import { ContentWorkbenchPage } from '../features/contentWorkbench/ContentWorkbenchPage'
import { ContentHistoryPage } from '../features/contentHistory/ContentHistoryPage'
import { CollaborationDynamicsPage } from '../features/collaborationDynamics/CollaborationDynamicsPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { RunDetailPage } from '../features/runDetail/RunDetailPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { WorkforcePage } from '../features/workforce/WorkforcePage'
import { WorkforceSettingsPage } from '../features/workforceSettings/WorkforceSettingsPage'
import { UsageBillingPage } from '../features/billing/UsageBillingPage'
import { HomePage } from '../features/home/HomePage'
import type { AppView } from './AppShell'
import { useEffect, useState } from 'react'

// 除运行详情（需 run 参数）外，其余视图都能用一个查询串表达；首页是默认视图，查询串留空。
const VIEW_QUERY: Record<Exclude<AppView, 'run'>, string> = {
  home: '',
  workbench: '?view=workbench',
  history: '?view=history',
  knowledge: '?view=knowledge',
  dynamics: '?view=dynamics',
  inbox: '?view=inbox',
  audit: '?view=audit',
  workforce: '?view=workforce',
  workforceSettings: '?view=workforceSettings',
  billing: '?view=billing',
}

const DIRECT_VIEWS = Object.keys(VIEW_QUERY) as AppView[]

interface Route {
  view: AppView
  taskId?: string
  runId?: string
}

function routeFromLocation(): Route {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  const runId = params.get('run') || undefined
  const taskId = params.get('task') || undefined
  // 运行详情必须带 run 参数，否则视为未知视图。
  if (view === 'run' && runId) return { view: 'run', runId, taskId }
  if (view && DIRECT_VIEWS.includes(view as AppView)) return { view: view as AppView, taskId }
  // 只带 task 参数时归到内容工作台（历史草稿与通知的跳转都走这条）。
  if (taskId) return { view: 'workbench', taskId }
  return { view: 'home' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromLocation)

  useEffect(() => {
    const update = () => setRoute(routeFromLocation())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])

  const go = (query: string) => {
    window.history.pushState({}, '', query || window.location.pathname)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  const navigate = (view: AppView, taskId?: string, runId?: string) => {
    if (view === 'run') return go(`?view=run&run=${encodeURIComponent(runId ?? '')}`)
    if (view === 'workbench' && taskId) return go(`?task=${encodeURIComponent(taskId)}`)
    return go(VIEW_QUERY[view])
  }

  if (route.view === 'home') return <HomePage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={navigate} />
  if (route.view === 'knowledge') return <KnowledgeAccessPage onNavigate={navigate} />
  if (route.view === 'dynamics') return <CollaborationDynamicsPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'history') return <ContentHistoryPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'inbox') return <InboxPage onOpenTask={(taskId) => navigate('workbench', taskId)} onOpenRun={(runId) => navigate('run', undefined, runId)} onNavigate={(view) => navigate(view)} />
  if (route.view === 'audit') return <AuditLogPage onNavigate={navigate} />
  if (route.view === 'workforce') return <WorkforcePage onNavigate={navigate} />
  if (route.view === 'workforceSettings') return <WorkforceSettingsPage onNavigate={navigate} />
  if (route.view === 'billing') return <UsageBillingPage onNavigate={navigate} />
  if (route.view === 'run' && route.runId) return <RunDetailPage runId={route.runId} onNavigate={navigate} />
  return <ContentWorkbenchPage taskId={route.taskId} onNavigate={(view) => navigate(view)} />
}
