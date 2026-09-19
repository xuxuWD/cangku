/**
 * 导航定义（第 1 轮只定义入口，不接业务）。
 *
 * 员工可见 4 项；管理员在员工这 4 项之外**额外**可见 4 项（合计 8 项）。
 * 每项带 `roles` 可见角色集合，界面按当前角色过滤 —— 这只是界面自适应，
 * 真实权限必须由服务端校验（前端隐藏入口不算权限控制）。
 */
import type { ComponentType } from 'react'
import {
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BookOutlined,
  DeploymentUnitOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import type { Role } from './session'

/** 导航项唯一键，同时也是占位页注册表的键。 */
export type NavKey =
  | 'my-workbench'
  | 'my-agents'
  | 'knowledge'
  | 'team'
  | 'agent-admin'
  | 'permissions'
  | 'skills-mcp'
  | 'audit-log'

export interface NavItem {
  key: NavKey
  /** 侧栏与页面标题文案。 */
  title: string
  /** 侧栏图标（AntD 图标组件）。 */
  icon: ComponentType
  /** 可见角色集合。 */
  roles: readonly Role[]
}

/** 员工与管理员都可见。 */
const ALL_ROLES: readonly Role[] = ['employee', 'super_admin']
/** 仅管理员可见。 */
const ADMIN_ONLY: readonly Role[] = ['super_admin']

export const NAV_ITEMS: readonly NavItem[] = [
  // 员工可见的 4 项
  { key: 'my-workbench', title: '我的工作台', icon: AppstoreOutlined, roles: ALL_ROLES },
  { key: 'my-agents', title: '我的数字员工', icon: RobotOutlined, roles: ALL_ROLES },
  { key: 'knowledge', title: '知识库', icon: BookOutlined, roles: ALL_ROLES },
  { key: 'team', title: '团队协作', icon: TeamOutlined, roles: ALL_ROLES },
  // 管理员额外可见的 4 项
  { key: 'agent-admin', title: '数字员工管理', icon: DeploymentUnitOutlined, roles: ADMIN_ONLY },
  { key: 'permissions', title: '权限配置', icon: SafetyCertificateOutlined, roles: ADMIN_ONLY },
  { key: 'skills-mcp', title: 'Skill & MCP', icon: ApiOutlined, roles: ADMIN_ONLY },
  { key: 'audit-log', title: '审计日志', icon: AuditOutlined, roles: ADMIN_ONLY },
]

/** 按角色过滤后的导航项（顺序即展示顺序）。 */
export function navItemsForRole(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}