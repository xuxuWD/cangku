import { KnowledgeAccessPage } from '../features/knowledgeAccess/KnowledgeAccessPage'
import { ContentWorkbenchPage } from '../features/contentWorkbench/ContentWorkbenchPage'
import { ContentHistoryPage } from '../features/contentHistory/ContentHistoryPage'
import type { AppView } from './AppShell'
import { useEffect, useState } from 'react'

function routeFromLocation() {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  return { view: (view === 'history' || view === 'knowledge' ? view : 'workbench') as AppView, taskId: params.get('task') || undefined }
}

export default function App() {
  const [route, setRoute] = useState(routeFromLocation)
  useEffect(() => { const update = () => setRoute(routeFromLocation()); window.addEventListener('popstate', update); return () => window.removeEventListener('popstate', update) }, [])
  const navigate = (view: AppView, taskId?: string) => { const query = view === 'history' ? '?view=history' : view === 'knowledge' ? '?view=knowledge' : taskId ? `?task=${encodeURIComponent(taskId)}` : ''; window.history.pushState({}, '', query || window.location.pathname); window.dispatchEvent(new PopStateEvent('popstate')) }
  if (route.view === 'knowledge') return <KnowledgeAccessPage onNavigate={navigate} />
  if (route.view === 'history') return <ContentHistoryPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
  return <ContentWorkbenchPage taskId={route.taskId} onNavigate={(view) => navigate(view)} />
}
