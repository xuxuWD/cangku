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
  MessageOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BellOutlined,
  BookOutlined,
  BranchesOutlined,
  ExperimentOutlined,
  RobotOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import type { Role } from './session'

/** 导航项唯一键，同时也是页面注册表（`AppShell` 的 `PAGES`）的键。 */
export type NavKey =
  | 'conversation'
  | 'my-workbench'
  | 'inbox'
  | 'my-agents'
  | 'knowledge'
  | 'dynamics'
  | 'team'
  | 'agent-admin'
  | 'permissions'
  | 'skills-mcp'
  | 'audit-log'
  | 'billing'
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
 * 「用量与费用」入口的可见角色（`docs/api-contract.md` §私有部署商业化 G0 逐字）：
 * `GET /api/v1/commercial/usage` 的权限 = **`super_admin`，或本租户已登记的 `customer_admin`**；
 * 其他角色 `403`。⇒ 入口**只给这两个角色**（页面另有整页无权限态兜底），
 * **不对全员开放** —— 否则就是一个点了必 403 的「假入口」（D-041 正在治这类问题）。
 */
const BILLING_ROLES: readonly Role[] = ['super_admin', 'customer_admin']

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
  // 「对话」= B3 §0 说的**唯一创建入口**，故排在第一位（2026-09-23 由 D-050⑤ 合并移植）。
  { key: 'conversation', title: '对话', icon: MessageOutlined, roles: ALL_ROLES },
  // 员工可见的业务页（第 8 轮起含「Skill & MCP」，第 10 轮起含「审计日志」）
  { key: 'my-workbench', title: '我的工作台', icon: AppstoreOutlined, roles: ALL_ROLES },
  // 「通知」= admin-web「收件箱」模块的合并移植（D-050⑤ 基座重组第一件）。
  // 通知按当前登录身份自限（服务端强制），五个角色都有本人通知 ⇒ 全员可见。
  { key: 'inbox', title: '通知', icon: BellOutlined, roles: ALL_ROLES },
  { key: 'my-agents', title: '我的数字员工', icon: RobotOutlined, roles: ALL_ROLES },
  { key: 'knowledge', title: '知识库', icon: BookOutlined, roles: ALL_ROLES },
  // 「协同动态」= admin-web 同模块的合并移植（契约：普通员工看自己有权限的任务子集，全员可访问）
  { key: 'dynamics', title: '协同动态', icon: BranchesOutlined, roles: ALL_ROLES },
  { key: 'skills-mcp', title: 'Skill & MCP', icon: ApiOutlined, roles: SKILL_ROLES },
  { key: 'team', title: '团队协作', icon: TeamOutlined, roles: ALL_ROLES },
  { key: 'audit-log', title: '审计日志', icon: AuditOutlined, roles: AUDIT_ROLES },
  ...DEV_NAV_ITEMS,
]

/**
 * **管理类入口：收进设置弹窗**（B3 §7 第 1 步 / §2「管理类收进设置弹窗」）。
 *
 * ⚠️ 这三项**从侧栏移到设置弹窗**，**页面一行没改、功能一条没删**（可逆收敛 —— §13.2 R5）。
 *
 * **为什么只移这三项**：它们**本来就只对管理员可见**（`ADMIN_ONLY` / `BILLING_ROLES`），
 * 移走不会让任何一个非管理员"少看到东西"；同时侧栏对**所有角色**降到 8 项（目标 ≤10）。
 * 而 §2 里还提到「审计」「知识权限」等也要收 —— 那属于 **B1 §4.2 逐模块归属表（待你勾选）**，
 * B3 §10 明写「本文不重复」⇒ **本轮不预判**。
 */
export interface AdminSettingsEntry {
  key: NavKey
  title: string
  /** 原本在侧栏的哪个位置（可逆收敛的"来源"证据）。 */
  from: string
  how: '配置类收进设置' | '同类合并'
  roles: readonly Role[]
}

export const ADMIN_SETTINGS_ENTRIES: readonly AdminSettingsEntry[] = [
  {
    key: 'agent-admin',
    title: '数字员工管理',
    from: '侧栏（仅超管可见）',
    how: '配置类收进设置',
    roles: ADMIN_ONLY,
  },
  {
    key: 'permissions',
    title: '权限配置',
    from: '侧栏（仅超管可见）',
    how: '配置类收进设置',
    roles: ADMIN_ONLY,
  },
  {
    key: 'billing',
    title: '用量与费用',
    from: '侧栏（超管 + 客户管理员可见）',
    how: '配置类收进设置',
    roles: BILLING_ROLES,
  },
]

/** 当前角色在设置弹窗里能到达的管理项键。 */
export function adminSettingsKeysForRole(role: Role): NavKey[] {
  return ADMIN_SETTINGS_ENTRIES.filter((entry) => entry.roles.includes(role)).map((entry) => entry.key)
}

/**
 * **全部合法视图键** —— 路由允许出现哪些 `?view=`。
 *
 * ⚠️ **与 `NAV_ITEMS` 不是一回事，不能互相替代**：
 * - `NAV_ITEMS` = **侧栏显示**哪些（收敛后只有 8 项）；
 * - 本表 = **路由接受**哪些 —— 还必须包含**不在侧栏**的页：设置弹窗里的三项管理页，以及开发期样品页。
 *
 * 2026-09-23 加这张表的**原因（一个真 bug）**：`shellRouter` 原先用 `NAV_ITEMS` 判合法性，
 * 侧栏收敛把三项管理页移出 `NAV_ITEMS` 之后，**设置弹窗里的「打开」链接会被路由器判为非法并回落到首页**
 * —— 页面从此进不去。AppShell 的用例当场把它照出来了。
 */
/**
 * 某个视图键的标题（侧栏项或设置项；都没有则 `null`）。
 *
 * ⚠️ **不要在这里硬写任何开发期入口的标题字符串**。开发期入口（`components-playground`）
 * 的标题必须**只**来自 `DEV_NAV_ITEMS` —— 它在生产构建里是空数组，整条（含字符串与图标）被摇掉。
 * 2026-09-23 换壳时在这里硬写了一行 `'组件样品'`，**生产包里立刻多出 1 处命中**
 * （既有验收要求是 0 命中，`npm run build` 后 grep 验证），已删。
 */
export function navTitle(key: NavKey): string | null {
  const inSidebar = NAV_ITEMS.find((item) => item.key === key)
  if (inSidebar) return inSidebar.title
  const inSettings = ADMIN_SETTINGS_ENTRIES.find((entry) => entry.key === key)
  if (inSettings) return inSettings.title
  return null
}

export const ALL_NAV_KEYS: readonly NavKey[] = [
  'conversation',
  'my-workbench',
  'inbox',
  'my-agents',
  'knowledge',
  'dynamics',
  'team',
  'agent-admin',
  'permissions',
  'skills-mcp',
  'audit-log',
  'billing',
  'components-playground',
]

/** 按角色过滤后的导航项（顺序即展示顺序）。 */
export function navItemsForRole(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role))
}