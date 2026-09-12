import { useState } from 'react'
import type { IconName } from '../components/Icon'
import { Icon } from '../components/Icon'
import { useUnreadCount } from '../features/inbox/useUnreadCount'
import { THEME_LABELS, THEME_MODES, useThemeMode } from './theme'

export type AppView =
  | 'home'
  | 'workbench'
  | 'conversation'
  | 'history'
  | 'knowledge'
  | 'dynamics'
  | 'inbox'
  | 'run'
  | 'audit'
  | 'workforce'
  | 'workforceSettings'
  | 'billing'

const navigation: Array<{ icon: IconName; label: string; view: AppView }> = [
  { icon: 'home', label: '首页', view: 'home' },
  { icon: 'chat', label: '对话', view: 'conversation' },
  { icon: 'sparkle', label: '内容工作台', view: 'workbench' },
  { icon: 'bell', label: '通知', view: 'inbox' },
  { icon: 'history', label: '历史草稿', view: 'history' },
  { icon: 'project', label: '协同动态', view: 'dynamics' },
  { icon: 'user', label: '员工与岗位', view: 'workforce' },
  { icon: 'access', label: '知识权限管理', view: 'knowledge' },
  { icon: 'agent', label: '数字员工设置', view: 'workforceSettings' },
  { icon: 'model', label: '用量与费用', view: 'billing' },
  { icon: 'check', label: '安全与审计', view: 'audit' },
]

/** 侧栏分组标签：只是把入口归类，不引入任何统计数字。 */
const SECTIONS: Array<{ label: string; from: number; to: number }> = [
  { label: '工作台', from: 0, to: 6 },
  { label: '管理', from: 6, to: navigation.length },
]

const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  ceo: 'CEO',
  department_lead: '部门负责人',
  employee: '员工',
  customer_admin: '客户管理员',
}

/** 开发身份的岗位标签；未配置或未知角色时原样展示，不做猜测。 */
function resolveIdentity(): { roleLabel: string; userId: string } {
  const role = import.meta.env.VITE_USER_ROLE || 'super_admin'
  return {
    roleLabel: ROLE_LABELS[role] ?? role,
    userId: import.meta.env.VITE_USER_ID || 'admin',
  }
}

function ThemeSwitch() {
  const { mode, setMode } = useThemeMode()
  return (
    <div className="theme-switch" role="group" aria-label="外观">
      {THEME_MODES.map((option) => (
        <button
          key={option}
          type="button"
          className={`theme-option ${option === mode ? 'active' : ''}`}
          aria-pressed={option === mode}
          onClick={() => setMode(option)}
        >
          {THEME_LABELS[option]}
        </button>
      ))}
    </div>
  )
}

export function AppShell({
  children,
  activeView = 'workbench',
  onNavigate,
}: {
  children: React.ReactNode
  activeView?: AppView
  onNavigate?: (view: AppView) => void
}) {
  const unreadCount = useUnreadCount()
  const identity = resolveIdentity()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const toggleSection = (label: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">智</span>
          <span className="brand-copy">
            <strong>公司数字员工工作台</strong>
            <small>数字员工协作管理台</small>
          </span>
        </div>

        <nav className="sidebar-nav" aria-label="主导航">
          {SECTIONS.map((section) => {
            const items = navigation.slice(section.from, section.to)
            const isCollapsed = collapsed.has(section.label)
            return (
              <div className="side-section" key={section.label}>
                <button
                  type="button"
                  className="side-label"
                  aria-expanded={!isCollapsed}
                  onClick={() => toggleSection(section.label)}
                >
                  {section.label}
                  <Icon name="chevron" size={12} className={isCollapsed ? 'flip' : ''} />
                </button>
                {!isCollapsed &&
                  items.map((item) => (
                    <div
                      className={`nav-item ${item.view === activeView ? 'active' : ''}`}
                      role={onNavigate ? 'button' : undefined}
                      tabIndex={onNavigate ? 0 : undefined}
                      onClick={() => onNavigate?.(item.view)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') onNavigate?.(item.view)
                      }}
                      key={item.label}
                    >
                      <Icon name={item.icon} />
                      {item.label}
                      {item.view === 'inbox' && unreadCount > 0 && (
                        <span className="nav-badge" aria-label={`未读通知 ${unreadCount} 条`}>
                          {unreadCount > 99 ? '99+' : unreadCount}
                        </span>
                      )}
                    </div>
                  ))}
              </div>
            )
          })}
        </nav>

        <div className="sidebar-foot">
          <ThemeSwitch />
          <div className="sidebar-user">
            <span className="avatar" aria-hidden="true">{identity.roleLabel.slice(0, 1)}</span>
            <span className="user-meta">
              <strong>{identity.roleLabel}</strong>
              <small>{identity.userId}</small>
            </span>
          </div>
        </div>
      </aside>
      <div className="workspace">{children}</div>
    </div>
  )
}
