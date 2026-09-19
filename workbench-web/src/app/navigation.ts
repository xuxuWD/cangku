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
  ExperimentOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import type { Role } from './session'

/** 导航项唯一键，同时也是页面注册表（`AppShell` 的 `PAGES`）的键。 */
export type NavKey =
  | 'my-workbench'
  | 'my-agents'
  | 'knowledge'
  | 'team'
  | 'agent-admin'
  | 'permissions'
  | 'skills-mcp'
  | 'audit-log'
  | 'components-playground'

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

/**
 * 是否处于开发模式（**构建期常量**）。
 * 用 `MODE === 'development'`（`vite dev`）而不是 `DEV`：后者在 vitest 下也为真，
 * 会让样品页混进测试与业务导航。
 * 生产构建时它被替换为字面量 `false`，下面那条开发期入口会**整条**（含标题字符串与图标）被摇掉 ——
 * 所以「组件样品」不会出现在 `dist/` 里（`npm run build` 后 grep 应为 0 命中）。
 */
const IS_DEV_MODE = import.meta.env.MODE === 'development'

/**
 * 开发期辅助入口：组件样品页（不属业务导航，后续轮次可整体移除）。
 * 只在开发模式**构建进表**；生产构建里这个数组为空。
 */
const DEV_NAV_ITEMS: readonly NavItem[] = IS_DEV_MODE
  ? [{ key: 'components-playground', title: '组件样品', icon: ExperimentOutlined, roles: ALL_ROLES }]
  : []

/** 全部导航项（顺序即展示顺序；开发期入口排在最后）。 */
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
  ...DEV_NAV_ITEMS,
]

/** 按角色过滤后的导航项（顺序即展示顺序）。 */
export function navItemsForRole(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}