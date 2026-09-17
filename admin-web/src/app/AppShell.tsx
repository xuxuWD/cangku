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
  | 'crmAccounts'
  | 'crmOpportunities'
  | 'crmQuotes'
  | 'crmContracts'
  | 'crmProgress'

interface NavItem {
  icon: IconName
  label: string
  view: AppView
}

/**
 * 侧栏分组（P2c-1 / 立项 §17.2 Q10 落地）：
 * 「对话」是主轴（默认视图）；其余入口按能力归档。
 * 纪律：**每条入口必须指向已交付且可用的页面**，不摆空入口——
 * 「资产」（记忆与画像 / 技能与工具）与「数字员工工作看板」的前端页面尚未落地，故本期不建。
 */
const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  { label: '对话', items: [{ icon: 'chat', label: '对话', view: 'conversation' }] },
  {
    label: '任务与项目',
    items: [
      { icon: 'home', label: '概览', view: 'home' },
      { icon: 'sparkle', label: '内容工作台', view: 'workbench' },
      { icon: 'history', label: '历史草稿', view: 'history' },
      { icon: 'project', label: '协同动态', view: 'dynamics' },
    ],
  },
  {
    label: '员工',
    items: [
      { icon: 'user', label: '员工与岗位', view: 'workforce' },
      { icon: 'agent', label: '数字员工设置', view: 'workforceSettings' },
    ],
  },
  { label: '知识', items: [{ icon: 'access', label: '知识权限管理', view: 'knowledge' }] },
  {
    label: '治理',
    items: [
      { icon: 'check', label: '安全与审计', view: 'audit' },
      { icon: 'bell', label: '通知', view: 'inbox' },
      { icon: 'model', label: '用量与费用', view: 'billing' },
    ],
  },
  {
    label: '客户与商务',
    items: [
      { icon: 'user', label: '客户', view: 'crmAccounts' },
      { icon: 'project', label: '商机', view: 'crmOpportunities' },
      { icon: 'document', label: '报价', view: 'crmQuotes' },
      { icon: 'content', label: '合同', view: 'crmContracts' },
      { icon: 'model', label: '进度概览', view: 'crmProgress' },
    ],
  },
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
          {NAV_GROUPS.map((section) => {
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
                  section.items.map((item) => (
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
