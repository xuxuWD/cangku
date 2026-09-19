import { KnowledgeAccessPage } from '../features/knowledgeAccess/KnowledgeAccessPage'
import { CollaborationDynamicsPage } from '../features/collaborationDynamics/CollaborationDynamicsPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { RunDetailPage } from '../features/runDetail/RunDetailPage'
import { AuditLogPage } from '../features/auditLog/AuditLogPage'
import { WorkforcePage } from '../features/workforce/WorkforcePage'
import { WorkforceSettingsPage } from '../features/workforceSettings/WorkforceSettingsPage'
import { UsageBillingPage } from '../features/billing/UsageBillingPage'
import { ConversationPage } from '../features/conversation/ConversationPage'
import { HomePage } from '../features/home/HomePage'
import { CrmAccountsPage } from '../features/crm/CrmAccountsPage'
import { CrmOpportunitiesPage } from '../features/crm/CrmOpportunitiesPage'
import { CrmQuotesPage } from '../features/crm/CrmQuotesPage'
import { CrmContractsPage } from '../features/crm/CrmContractsPage'
import { CrmProgressPage } from '../features/crm/CrmProgressPage'
import { ConversationListProvider } from '../features/conversation/listStore'
import { TasksPage, type TasksTab } from '../features/tasks/TasksPage'
import { AppShell, type AppView } from './AppShell'
import { SettingsPage } from './SettingsPage'
import { ThemeProvider } from './ThemeProvider'
import { useEffect, useRef, useState } from 'react'

// 除运行详情（需 run 参数）外，其余视图都能用一个查询串表达。
// P2c-1 起默认视图 = 对话（主轴）；空查询串与未知 ?view= 一并回落对话，「概览」（原首页）保留显式入口 ?view=home。
const VIEW_QUERY: Record<Exclude<AppView, 'run'>, string> = {
  home: '?view=home',
  workbench: '?view=workbench',
  conversation: '?view=conversation',
  knowledge: '?view=knowledge',
  dynamics: '?view=dynamics',
  inbox: '?view=inbox',
  audit: '?view=audit',
  workforce: '?view=workforce',
  workforceSettings: '?view=workforceSettings',
  billing: '?view=billing',
  crmAccounts: '?view=crmAccounts',
  crmOpportunities: '?view=crmOpportunities',
  crmQuotes: '?view=crmQuotes',
  crmContracts: '?view=crmContracts',
  crmProgress: '?view=crmProgress',
  settings: '?view=settings',
}

const DIRECT_VIEWS = Object.keys(VIEW_QUERY) as AppView[]

// 视图槽的顺序；槽只做显隐，不代表导航顺序（导航顺序在 AppShell 的侧栏里）。
const VIEW_ORDER: AppView[] = [
  'home',
  'conversation',
  'workbench',
  'inbox',
  'dynamics',
  'workforce',
  'knowledge',
  'workforceSettings',
  'billing',
  'audit',
  'crmAccounts',
  'crmOpportunities',
  'crmQuotes',
  'crmContracts',
  'crmProgress',
  'settings',
  'run',
]

interface Route {
  view: AppView
  taskId?: string
  runId?: string
  conversationId?: string
  /** S1 第三款：通知点开后要聚焦的那条审批（`?view=conversation&conversation=…&approval=…`）。 */
  approvalId?: string
  /** 「任务」合并页的页签（`?view=workbench&tab=history`）。 */
  tab?: TasksTab
}

function routeFromLocation(): Route {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  const runId = params.get('run') || undefined
  const taskId = params.get('task') || undefined
  const conversationId = params.get('conversation') || undefined
  const approvalId = params.get('approval') || undefined
  const tab: TasksTab | undefined = params.get('tab') === 'history' ? 'history' : undefined
  // 老深链别名：`?view=history` 是「任务」页的历史草稿页签（M2 合并后不得 404 / 回落默认页）。
  if (view === 'history') return { view: 'workbench', tab: 'history' }
  // 运行详情必须带 run 参数，否则视为未知视图。
  // S3：运行详情可**携带来源会话**（`&conversation=<id>`）⇒ 页面给出「回到会话」的退路，不丢上下文。
  if (view === 'run' && runId) return { view: 'run', runId, taskId, conversationId }
  // 对话支持 URL 直达某个会话：?view=conversation&conversation=<id>，刷新后仍停留在该会话。
  // S1 第三款：再带 `&approval=<id>` 时页内聚焦该条审批卡（服务端仍是权威态来源）。
  if (view === 'conversation') return { view: 'conversation', conversationId, approvalId }
  if (view && DIRECT_VIEWS.includes(view as AppView)) return { view: view as AppView, taskId, tab }
  // 只带 task 参数时归到「任务」（历史草稿与通知的跳转都走这条）。
  if (taskId) return { view: 'workbench', taskId }
  // 默认视图 = 对话（P2c-1 主轴）；未知 ?view= 与空查询串一并回落对话。
  return { view: 'conversation' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromLocation)
  // 常驻外壳（D19）：访问过的视图保持挂载，切页不再丢草稿、滚动位置与页面内部状态。
  // 未访问过的视图**不挂载**——否则一启动就会打出十几个页面的并发请求。
  const [mounted, setMounted] = useState<ReadonlySet<AppView>>(() => new Set<AppView>([route.view]))

  // 常驻外壳（D19）：各槽记住**最后一次用过的参数**。
  // 为什么需要：槽不卸载，但 URL 换了（例如跳去 `?task=…`）后 `route` 里就没有会话 / 运行号了。
  // 不记住的两类真实缺陷：① 运行详情槽拿空运行号继续请求（`/runs//metrics` 等 404 噪音）；
  // ② 从会话跳走再回「对话」时**会话上下文丢失**（与真源 §5「会话上下文不丢」直接冲突）。
  const lastIds = useRef<{ conversationId?: string; runId?: string }>({
    conversationId: route.conversationId,
    runId: route.runId,
  })
  if (route.conversationId) lastIds.current.conversationId = route.conversationId
  if (route.runId) lastIds.current.runId = route.runId

  useEffect(() => {
    const update = () => setRoute(routeFromLocation())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])

  useEffect(() => {
    setMounted((current) => (current.has(route.view) ? current : new Set(current).add(route.view)))
  }, [route.view])

  const go = (query: string) => {
    window.history.pushState({}, '', query || window.location.pathname)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  const navigate = (view: AppView, taskId?: string, runId?: string, conversationId?: string, approvalId?: string) => {
    if (view === 'run') {
      // S3：带着当前会话跳到运行详情（有会话时），这样详情页能「回到会话」；
      // 从通知等入口进入时没有会话，就不带该参数（深链语义不变）。
      const origin = conversationId ?? route.conversationId
      return go(`?view=run&run=${encodeURIComponent(runId ?? '')}${origin ? `&conversation=${encodeURIComponent(origin)}` : ''}`)
    }
    if (view === 'conversation') {
      // IA-03（真源 §2.17.1）：点左栏「对话」时**保持当前已打开的会话**——
      // 只有显式传入新的会话 id 才切换；没有正在看的会话才回列表。
      // 兜底链里带上「记住的会话」：从别的视图切回来时 URL 与页面口径一致（不留「页面在会话里、URL 却是列表」）。
      const target = conversationId ?? route.conversationId ?? lastIds.current.conversationId
      // S1 第三款：`approvalId` 只在**显式传入**时进 URL（切换会话即自动清掉聚焦，不留悬挂参数）。
      const focus = approvalId ? `&approval=${encodeURIComponent(approvalId)}` : ''
      return go(target ? `?view=conversation&conversation=${encodeURIComponent(target)}${focus}` : VIEW_QUERY.conversation)
    }
    if (view === 'workbench' && taskId) return go(`?task=${encodeURIComponent(taskId)}`)
    return go(VIEW_QUERY[view])
  }

  // 会话选择入口（左栏列表 / 对话页内切换 / 删会话后回列表）：
  // **显式 undefined = 主动清空**（删会话 / 回列表）⇒ 连「记住的会话」一起清，避免它被后续点击复活。
  const selectConversation = (conversationId: string | undefined) => {
    if (conversationId === undefined) {
      lastIds.current.conversationId = undefined
      return go(VIEW_QUERY.conversation)
    }
    navigate('conversation', undefined, undefined, conversationId)
  }

  const renderView = (view: AppView) => {
    switch (view) {
      case 'home':
        return (
          <HomePage
            onOpenConversation={(conversationId) => navigate('conversation', undefined, undefined, conversationId)}
            onNavigate={navigate}
            // S5：待办行的真实落点（页面不自己拼 URL）。
            onOpenTask={(taskId) => navigate('workbench', taskId)}
            onOpenRun={(runId) => navigate('run', undefined, runId)}
          />
        )
      case 'conversation':
        // 记住的会话号兜底：从别的视图切回来时，槽仍是同一个会话（不因 URL 没带而回列表）。
        return <ConversationPage conversationId={route.conversationId ?? lastIds.current.conversationId} focusApprovalId={route.approvalId} onSelectConversation={selectConversation} onNavigate={navigate} />
      case 'knowledge':
        return <KnowledgeAccessPage onNavigate={navigate} />
      case 'dynamics':
        return <CollaborationDynamicsPage onOpenTask={(taskId) => navigate('workbench', taskId)} onNavigate={(view) => navigate(view)} />
      case 'workbench':
        // UI v2 §3.2：任务 = 内容工作台 + 历史草稿两个页签（同一件事不再两个入口）。
        return (
          <TasksPage
            taskId={route.taskId}
            tab={route.tab}
            onChangeTab={(next) => go(next === 'history' ? '?view=workbench&tab=history' : VIEW_QUERY.workbench)}
            onOpenTask={(taskId) => navigate('workbench', taskId)}
            onNavigate={navigate}
          />
        )
      case 'inbox':
        return (
          <InboxPage
            onOpenTask={(taskId) => navigate('workbench', taskId)}
            onOpenRun={(runId) => navigate('run', undefined, runId)}
            // S1 第三款：带会话上文的通知直达「该会话的该条卡」（无则各自回落既有落点）。
            onOpenConversation={(conversationId, approvalId) => navigate('conversation', undefined, undefined, conversationId, approvalId)}
            onNavigate={(view) => navigate(view)}
          />
        )
      case 'audit':
        return <AuditLogPage onNavigate={navigate} />
      case 'workforce':
        return (
          <WorkforcePage
            onNavigate={navigate}
            onOpenTask={(taskId) => navigate('workbench', taskId)}
            onOpenRun={(runId) => navigate('run', undefined, runId)}
          />
        )
      case 'workforceSettings':
        return <WorkforceSettingsPage onNavigate={navigate} />
      case 'billing':
        return <UsageBillingPage onNavigate={navigate} />
      case 'crmAccounts':
        return <CrmAccountsPage onNavigate={navigate} />
      case 'crmOpportunities':
        return <CrmOpportunitiesPage onNavigate={navigate} />
      case 'crmQuotes':
        return <CrmQuotesPage onNavigate={navigate} />
      case 'crmContracts':
        return <CrmContractsPage onNavigate={navigate} />
      case 'crmProgress':
        return <CrmProgressPage onNavigate={navigate} />
      case 'settings':
        return <SettingsPage />
      case 'run': {
        // 没有运行号就**不渲染**（槽被隐藏时也不该拿空号去打 `/runs//…`）；有则用记住的那个。
        const activeRunId = route.runId ?? lastIds.current.runId
        if (!activeRunId) return null
        return (
          <RunDetailPage
            runId={activeRunId}
            onNavigate={navigate}
            // S3：带来源会话时给「回到会话」退路（无来源则不给，避免假按钮）。
            originConversationId={route.conversationId}
            onOpenConversation={(conversationId) => navigate('conversation', undefined, undefined, conversationId)}
          />
        )
      }
    }
  }

  return (
    // 主题在应用级共享（外壳快捷切换与设置页「外观」读同一份状态）。
    <ThemeProvider>
      {/* 会话列表在左栏常驻（真源 §2.17.3）⇒ 状态提到 App 层做单一来源，
          左栏与对话页读同一份，避免"左栏新建了、页内列表不刷新"。 */}
      <ConversationListProvider>
        <AppShell
          activeView={route.view}
          onNavigate={navigate}
          activeConversationId={route.conversationId ?? lastIds.current.conversationId}
          onSelectConversation={selectConversation}
        >
          {VIEW_ORDER.filter((view) => mounted.has(view)).map((view) => (
            <section className="view-slot" key={view} hidden={view !== route.view}>
              {renderView(view)}
            </section>
          ))}
        </AppShell>
      </ConversationListProvider>
    </ThemeProvider>
  )
}
