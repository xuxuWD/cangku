import type { IconName } from '../components/FilledIcon'
import { FilledIcon } from '../components/FilledIcon'

const navigation: Array<{ icon: IconName; label: string; view?: 'workbench' | 'history' }> = [
  { icon: 'home', label: '内容工作台', view: 'workbench' },
  { icon: 'user', label: '员工与岗位' },
  { icon: 'access', label: '知识权限管理' },
  { icon: 'agent', label: '数字员工设置' },
  { icon: 'model', label: '模型与费用' },
  { icon: 'history', label: '历史草稿', view: 'history' },
]

export function AppShell({ children, activeView = 'workbench', onNavigate }: { children: React.ReactNode; activeView?: 'workbench' | 'history'; onNavigate?: (view: 'workbench' | 'history') => void }) {
  return <div className="app-shell"><header className="topbar"><div style={{ display: 'flex', alignItems: 'center' }}><div className="brand"><div className="brand-mark">智</div>公司数字员工工作台</div><span className="breadcrumb">知识权限</span></div><div className="top-actions"><span className="service-status">服务正常</span><div className="profile"><div className="avatar">超</div>超级管理员</div></div></header><div className="body-layout"><aside className="sidebar"><div className="side-label">管理中心</div>{navigation.map((item) => <div className={`nav-item ${item.view === activeView ? 'active' : ''}`} role={item.view && onNavigate ? 'button' : undefined} tabIndex={item.view && onNavigate ? 0 : undefined} onClick={() => item.view && onNavigate?.(item.view)} onKeyDown={(event) => { if ((event.key === 'Enter' || event.key === ' ') && item.view) onNavigate?.(item.view) }} key={item.label}><FilledIcon name={item.icon} label={item.label} />{item.label}</div>)}<div className="side-summary"><h4>本月授权概况</h4><p>已配置 18 个岗位<br />42 个数字员工</p><div className="stat"><span>授权覆盖</span><b>68%</b></div><div className="meter"><span /></div></div></aside>{children}</div></div>
}
