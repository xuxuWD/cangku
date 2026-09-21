/**
 * 导航定义（第 1 轮只定义入口，不接业务）。
 *
 * 员工可见 6 项（第 8 轮起「Skill & MCP」对四个业务角色开放；第 10 轮起「审计日志」同理）；
 * 管理员在其之外**额外**可见 2 项（合计 8 项）。
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

/**
 * 所有已登录角色都可见。
 *
 * 第 6 轮（接线批 1）：角色改由**服务端登录响应**下发，取值有 5 个
 * （`employee / department_lead / ceo / super_admin / customer_admin`）。任何一个角色若一项都取不到，
 * 壳里 `visibleItems[0]` 就会落空并整页崩掉，所以这里必须覆盖全部 5 个 —— 但这**只是界面可见性**，
 * 真正的权限判定仍在服务端，且各页各自再按能力判定（如注册中心只对 `agent.manage` 开放）。
 */
const ALL_ROLES: readonly Role[] = ['employee', 'department_lead', 'ceo', 'super_admin', 'customer_admin']
/** 仅管理员可见。 */
const ADMIN_ONLY: readonly Role[] = ['super_admin']

/**
 * 「Skill & MCP」入口的可见角色（**第 8 轮矩阵 §3 裁决**）。
 *
 * 矩阵 §3「技能：提交（自带 Skill 包）」= 四个角色 ✅ / `customer_admin` ❌；
 * 「技能：复核/启用/停用」= `ceo` + `super_admin` ✅。
 * ⇒ 该入口对四个业务角色开放（**同轮开放员工侧提交入口**，此前是 `ADMIN_ONLY`）；
 * `customer_admin` 没有任何技能能力，入口**不显示**（页面另有整页无权限态兜底）。
 */
const SKILL_ROLES: readonly Role[] = ['employee', 'department_lead', 'ceo', 'super_admin']

/**
 * 「审计日志」入口的可见角色（**第 10 轮矩阵 §3 裁决**）。
 *
 * 矩阵 §3「审计：查询」= `employee` ⚠️仅本人相关 / `department_lead` ✅本租户 / `ceo` ✅ / `super_admin` ✅；
 * `customer_admin` ❌ ⇒ 入口不显示（页面另有整页无权限态兜底）。
 */
const AUDIT_ROLES: readonly Role[] = ['employee', 'department_lead', 'ceo', 'super_admin']

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
  // 员工可见的 6 项（第 8 轮起含「Skill & MCP」，第 10 轮起含「审计日志」）
  { key: 'my-workbench', title: '我的工作台', icon: AppstoreOutlined, roles: ALL_ROLES },
  { key: 'my-agents', title: '我的数字员工', icon: RobotOutlined, roles: ALL_ROLES },
  { key: 'knowledge', title: '知识库', icon: BookOutlined, roles: ALL_ROLES },
  { key: 'skills-mcp', title: 'Skill & MCP', icon: ApiOutlined, roles: SKILL_ROLES },
  { key: 'team', title: '团队协作', icon: TeamOutlined, roles: ALL_ROLES },
  { key: 'audit-log', title: '审计日志', icon: AuditOutlined, roles: AUDIT_ROLES },
  // 管理员额外可见的 2 项
  { key: 'agent-admin', title: '数字员工管理', icon: DeploymentUnitOutlined, roles: ADMIN_ONLY },
  { key: 'permissions', title: '权限配置', icon: SafetyCertificateOutlined, roles: ADMIN_ONLY },
  ...DEV_NAV_ITEMS,
]

/** 按角色过滤后的导航项（顺序即展示顺序）。 */
export function navItemsForRole(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}