import { useCallback, useEffect, useMemo, useState } from 'react'
import type { IconName } from '../components/Icon'
import { Icon } from '../components/Icon'
import { GuideDrawer } from '../components/ui/GuideDrawer'
import { useConversationList } from '../features/conversation/listStore'
import { useUnreadCount } from '../features/inbox/useUnreadCount'
import { GUIDES } from './guides'
import { resolveIdentity } from './identity'
import { Onboarding } from './Onboarding'
import { SidebarConversations } from './SidebarConversations'
import { useTheme } from './ThemeProvider'

export type AppView =
  | 'home'
  | 'workbench'
  | 'conversation'
  | 'knowledge'
  | 'dynamics'
  | 'inbox'
  | 'run'
  | 'audit'
  | 'workforce'
  | 'workforceSettings'
  | 'billing'
  | 'crmAccounts'
  | 'crmOpportunities'
  | 'crmQuotes'
  | 'crmContracts'
  | 'crmProgress'
  | 'settings'

interface NavItem {
  icon: IconName
  label: string
  view: AppView
}

/**
 * 侧栏主导航（UI v2 §3.2）：扁平入口 + 「更多」。
 * 纪律：**每条入口必须指向已交付且可用的页面**，不摆空入口。
 */
const PRIMARY_NAV: NavItem[] = [
  { icon: 'home', label: '工作台', view: 'home' },
  { icon: 'chat', label: '对话', view: 'conversation' },
  { icon: 'tasks', label: '任务', view: 'workbench' },
  { icon: 'users', label: '员工', view: 'workforce' },
  { icon: 'book', label: '知识', view: 'knowledge' },
]

/** 「更多」子项：其余入口全在这里，先展开再点（≤1 次点击到达）。 */
const MORE_NAV: NavItem[] = [
  { icon: 'project', label: '协同动态', view: 'dynamics' },
  { icon: 'bell', label: '通知', view: 'inbox' },
  { icon: 'check', label: '安全与审计', view: 'audit' },
  { icon: 'model', label: '用量与费用', view: 'billing' },
  { icon: 'user', label: '客户', view: 'crmAccounts' },
  { icon: 'project', label: '商机', view: 'crmOpportunities' },
  { icon: 'document', label: '报价', view: 'crmQuotes' },
  { icon: 'content', label: '合同', view: 'crmContracts' },
  { icon: 'model', label: '进度概览', view: 'crmProgress' },
]

/**
 * 顶栏标题（UI v2 §3.1）：顶栏标题就是每页**唯一的 h1**，页面内不再重复标题。
 * M3 收口后 17 个视图全部按 v2 重绘，因此这里只有 `title` 一种形态。
 */
const VIEW_META: Record<AppView, { title: string }> = {
  home: { title: '工作台' },
  conversation: { title: '对话' },
  settings: { title: '设置' },
  workbench: { title: '任务' },
  workforce: { title: '员工与岗位' },
  knowledge: { title: '知识权限管理' },
  dynamics: { title: '协同动态' },
  inbox: { title: '通知' },
  audit: { title: '安全与审计' },
  billing: { title: '用量与费用' },
  crmAccounts: { title: '客户' },
  crmOpportunities: { title: '商机' },
  crmQuotes: { title: '报价' },
  crmContracts: { title: '合同' },
  crmProgress: { title: '进度概览' },
  workforceSettings: { title: '数字员工设置' },
  run: { title: '运行详情' },
}

/** 侧栏手动折叠（图标栏）跨会话保持；存储不可用时静默降级，不阻断界面。 */
const RAIL_KEY = 'workbench.sidebar.rail'

function readStoredRail(): boolean | null {
  try {
    const raw = window.localStorage.getItem(RAIL_KEY)
    return raw === '1' ? true : raw === '0' ? false : null
  } catch {
    return null
  }
}

function writeStoredRail(rail: boolean): void {
  try {
    window.localStorage.setItem(RAIL_KEY, rail ? '1' : '0')
  } catch {
    // 存不进就不存：只影响下次启动的默认形态。
  }
}

/** 媒体查询订阅（环境不支持 matchMedia，如 jsdom，按不匹配处理）。 */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    setMatches(mql.matches)
    mql.addEventListener?.('change', onChange)
    return () => mql.removeEventListener?.('change', onChange)
  }, [query])

  return matches
}

export function AppShell({
  children,
  activeView = 'conversation',
  onNavigate,
  activeConversationId,
  onSelectConversation,
}: {
  children: React.ReactNode
  activeView?: AppView
  onNavigate?: (view: AppView) => void
  activeConversationId?: string
  onSelectConversation?: (conversationId: string) => void
}) {
  const unreadCount = useUnreadCount()
  const conversationList = useConversationList()
  const identity = resolveIdentity()
  const theme = useTheme()
  // ≤1024px 默认图标栏；≤720px 侧栏收进抽屉（☰ 开合）。
  const compact = useMediaQuery('(max-width: 1024px)')
  const narrow = useMediaQuery('(max-width: 720px)')
  const [railOverride, setRailOverride] = useState<boolean | null>(() => readStoredRail())
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [creatingConversation, setCreatingConversation] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const rail = railOverride ?? compact
  const moreActive = MORE_NAV.some((item) => item.view === activeView)

  // `?` 打开本页使用指南（真源 §2.17.4）；正在输入框里打字时不拦截。
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing =
        !!target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      if (typing || event.key !== '?') return
      event.preventDefault()
      setGuideOpen((value) => !value)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // 窄屏切到抽屉形态时，收起已展开的抽屉，避免残留遮罩。
  useEffect(() => {
    if (!narrow) setDrawerOpen(false)
  }, [narrow])

  const go = useCallback(
    (view: AppView) => {
      onNavigate?.(view)
      setDrawerOpen(false)
      setGuideOpen(false)
    },
    [onNavigate],
  )

  const toggleSidebar = () => {
    if (narrow) {
      setDrawerOpen((value) => !value)
      return
    }
    const next = !rail
    setRailOverride(next)
    writeStoredRail(next)
  }

  const startConversation = async () => {
    setCreatingConversation(true)
    setCreateError(null)
    try {
      const conversationId = await conversationList.create()
      setDrawerOpen(false)
      onSelectConversation?.(conversationId)
    } catch {
      // 失败原因已由 Provider 的列表错误态承载；这里只给一句可读提示，不透技术细节。
      setCreateError('新建对话没有成功，请稍后再试。')
    } finally {
      setCreatingConversation(false)
    }
  }

  const themeToggleLabel = theme.resolved === 'dark' ? '切换到浅色外观' : '切换到深色外观'

  const navRow = (item: NavItem) => (
    <button
      key={item.view}
      type="button"
      className={`nav-item ${item.view === activeView ? 'is-active' : ''}`}
      aria-current={item.view === activeView ? 'page' : undefined}
      onClick={() => go(item.view)}
    >
      <Icon name={item.icon} size={18} />
      <span>{item.label}</span>
      {item.view === 'inbox' && unreadCount > 0 && (
        <span className="nav-count" aria-label={`未读通知 ${unreadCount} 条`}>
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </button>
  )

  const guide = GUIDES[activeView]
  const meta = VIEW_META[activeView]
  const sidebar = useMemo(
    () => (
      <aside className="sidebar" aria-label="主导航与会话">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">智</span>
          <span className="brand__copy">
            <span className="brand__name">公司数字员工工作台</span>
            <span className="brand__sub">数字员工协作管理台</span>
          </span>
        </div>

        {/* ① 主操作：每页常驻（IA-01） */}
        <button
          className="primary-action"
          type="button"
          disabled={creatingConversation}
          onClick={() => void startConversation()}
        >
          <Icon name="plus" size={16} />
          <span>{creatingConversation ? '正在新建…' : '新建对话'}</span>
        </button>
        {createError && (
          <p className="conversations__state conversations__state--error" role="alert">{createError}</p>
        )}

        {/* ②③ 中段（导航 + 会话列表）整体可滚动：底栏始终钉在底部，
            窄屏或「更多」展开后也不会互相覆盖（侧栏高度不足时中段自己滚）。 */}
        <div className="sidebar__scroll">
          <nav className="nav" aria-label="主导航">
          {PRIMARY_NAV.map(navRow)}
          <button
            type="button"
            className={`nav-item ${moreOpen ? 'is-open' : ''} ${moreActive ? 'is-active' : ''}`}
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen((value) => !value)}
          >
            <Icon name="dots" size={18} />
            <span>更多</span>
            {!moreOpen && unreadCount > 0 && (
              <span className="nav-count" aria-label={`未读通知 ${unreadCount} 条`}>
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
            <span className="nav-item__chev" aria-hidden="true"><Icon name="chevron" size={14} /></span>
          </button>
          <div className={`nav-sub ${moreOpen ? 'is-open' : ''}`}>
            {MORE_NAV.map((item) => (
              <button
                key={item.view}
                type="button"
                className={item.view === activeView ? 'is-active' : ''}
                onClick={() => go(item.view)}
              >
                {item.label}
                {item.view === 'inbox' && unreadCount > 0 ? `（${unreadCount}）` : ''}
              </button>
            ))}
          </div>
        </nav>

        {/* ③ 会话列表：常驻，与对话页同源（IA-02） */}
        <SidebarConversations
          activeConversationId={activeConversationId}
          onSelectConversation={(conversationId) => {
            setDrawerOpen(false)
            onSelectConversation?.(conversationId)
          }}
        />
        </div>

        <div className="sidebar-foot">
          <button className="user-chip" type="button" aria-label="账号与设置" onClick={() => go('settings')}>
            <span className="avatar" aria-hidden="true">{identity.roleLabel.slice(0, 1)}</span>
            <span className="user-chip__meta">
              <span className="user-chip__name">{identity.roleLabel}</span>
              <span className="user-chip__sub">{identity.userId}</span>
            </span>
          </button>
          <button
            className="icon-btn"
            type="button"
            aria-label={themeToggleLabel}
            title={themeToggleLabel}
            onClick={() => theme.setMode(theme.resolved === 'dark' ? 'light' : 'dark')}
          >
            <Icon name={theme.resolved === 'dark' ? 'sun' : 'moon'} size={16} />
          </button>
          <button
            className={`icon-btn ${activeView === 'settings' ? 'is-on' : ''}`}
            type="button"
            aria-label="设置"
            title="设置"
            onClick={() => go('settings')}
          >
            <Icon name="settings" size={16} />
          </button>
        </div>
      </aside>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeView, activeConversationId, creatingConversation, createError, moreOpen, moreActive, unreadCount, rail, identity.roleLabel, identity.userId, theme.resolved],
  )

  return (
    <div className={`app ${rail && !narrow ? 'is-rail' : ''} ${drawerOpen ? 'is-drawer-open' : ''}`}>
      {sidebar}
      {narrow && drawerOpen && <div className="sidebar-mask" role="presentation" onClick={() => setDrawerOpen(false)} />}
      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn"
            type="button"
            aria-label={narrow ? '打开或收起侧栏' : rail ? '展开侧栏' : '折叠侧栏'}
            aria-expanded={narrow ? drawerOpen : !rail}
            onClick={toggleSidebar}
          >
            <Icon name="panel" size={16} />
          </button>
          {/* M3 收口：全站 17 页都已按 v2 重绘，顶栏标题就是本页唯一的 h1（页面内不再重复标题）。 */}
          <h1 className="topbar__title">{meta.title}</h1>
          <div className="topbar__actions">
            <button className="btn btn--secondary btn--sm" type="button" onClick={() => setGuideOpen(true)}>
              <Icon name="help" size={14} />
              使用指南
            </button>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>

      {/* 使用指南与首访引导（真源 §2.17.4）：内置浮层，不外链。 */}
      <GuideDrawer open={guideOpen} guide={guide} onClose={() => setGuideOpen(false)} />
      <Onboarding onOpenHelp={() => setGuideOpen(true)} />
    </div>
  )
}