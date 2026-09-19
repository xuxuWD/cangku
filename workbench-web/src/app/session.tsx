/**
 * 会话（第 6 轮 · 接线批 1）—— **真实会话**，替换第 1 轮的本地角色桩。
 *
 * 事实来源（只读 `app/` 确认，未改后端一行）：
 *  - 建会话 `POST /api/v1/auth/sessions`，请求 `{phone, password, totp_code?}`（`app/main.py:4582`）；
 *    响应 `{access_token, token_type:"Bearer", expires_in, tenant_id, user_id, role, scope}`（`app/main.py:4825`）。
 *    **响应里没有展示名**，因此顶栏只显示**角色名**，不编造姓名 / 手机号。
 *  - 角色取值 `employee / department_lead / ceo / super_admin / customer_admin`（`app/accounts/service.py:45`）。
 *  - 无 `GET /auth/me`、无 refresh：令牌只在本页会话期内有效，过期即重新登录（401 → 清会话）。
 *
 * 令牌存放：`sessionStorage`（键 `workbench.token`）。**不进 localStorage、不进 URL、不进日志**。
 * 登出：服务端撤销（`POST /api/v1/auth/logout`，jti 进撤销名单）+ 清本地。
 *
 * ⚠️ 这里的能力映射**只用于界面呈现**（决定入口显不显示、给不给"无权限"说明）。
 *    真正的安全边界在服务端：每个接口都会按角色再判一次，前端隐藏/显示不构成授权。
 */
import { create } from 'zustand'

/** 角色取值（受控枚举，与后端一致；前端不新增角色）。 */
export type Role = 'employee' | 'department_lead' | 'ceo' | 'super_admin' | 'customer_admin'

export const ROLE_LABEL: Record<Role, string> = {
  employee: '员工',
  department_lead: '部门负责人',
  ceo: 'CEO',
  super_admin: '超级管理员',
  customer_admin: '客户管理员',
}

/** 令牌存储键（sessionStorage）。 */
export const TOKEN_STORAGE_KEY = 'workbench.token'
/** 角色提示键：仅用于**界面呈现**（刷新后仍能画出正确的导航）；安全边界在服务端。 */
export const ROLE_STORAGE_KEY = 'workbench.role'

function sessionStore(): Storage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

/** 读当前令牌（请求层每次请求都实时读，保证登出后不再带旧令牌）。 */
export function readToken(): string | null {
  return sessionStore()?.getItem(TOKEN_STORAGE_KEY) ?? null
}

/** 读存下来的角色提示（刷新后恢复导航用；非法值一律当作"未知"）。 */
export function readStoredRole(): Role | null {
  const raw = sessionStore()?.getItem(ROLE_STORAGE_KEY)
  return raw && raw in ROLE_LABEL ? (raw as Role) : null
}

/** 写本地会话（登录成功后调用）。 */
export function persistSession(token: string, role: Role): void {
  const store = sessionStore()
  if (!store) return
  store.setItem(TOKEN_STORAGE_KEY, token)
  store.setItem(ROLE_STORAGE_KEY, role)
}

/** 清本地会话（登出 / 401 / 令牌失效）。 */
export function clearStoredSession(): void {
  const store = sessionStore()
  if (!store) return
  store.removeItem(TOKEN_STORAGE_KEY)
  store.removeItem(ROLE_STORAGE_KEY)
}

export interface SessionState {
  status: 'anonymous' | 'authenticated'
  token: string | null
  role: Role | null
  /** 顶栏展示名：用角色名（后端未返回展示名，**不编造姓名**）。 */
  displayName: string
  /** 登录成功：令牌已落 sessionStorage。 */
  signIn: (input: { token: string; role: Role }) => void
  /** 本地登出（服务端登出由 `authService.logout` 负责）。 */
  signOut: () => void
}

const initialToken = readToken()
const initialRole = readStoredRole()

export const useSession = create<SessionState>((set) => ({
  status: initialToken ? 'authenticated' : 'anonymous',
  token: initialToken,
  role: initialRole,
  displayName: initialRole ? ROLE_LABEL[initialRole] : '',
  signIn: ({ token, role }) => {
    persistSession(token, role)
    set({ status: 'authenticated', token, role, displayName: ROLE_LABEL[role] })
  },
  signOut: () => {
    clearStoredSession()
    set({ status: 'anonymous', token: null, role: null, displayName: '' })
  },
}))

/** 供**非 React**代码清会话（请求层 401 时用）。 */
export function clearSession(): void {
  useSession.getState().signOut()
}

/**
 * 能力（capability）受控枚举 —— 界面呈现用（`PermissionGuard` 按它判定）。
 * 用"能力"而不是"角色"做判断：能力名是界面与代码的稳定契约。
 */
export type Capability =
  | 'agent.manage'
  | 'permission.manage'
  | 'knowledge.manage'
  | 'skill.manage'
  | 'audit.view'
  | 'data.export'
  | 'data.delete'

/** 能力显示名（用于"无权限"时的原因说明）。 */
export const CAPABILITY_LABEL: Record<Capability, string> = {
  'agent.manage': '数字员工管理',
  'permission.manage': '权限配置',
  'knowledge.manage': '知识库管理',
  'skill.manage': 'Skill & MCP 管理',
  'audit.view': '审计日志查看',
  'data.export': '数据导出',
  'data.delete': '数据删除',
}

/**
 * 角色 → 能力（**仅界面呈现**；每个请求都会在服务端按角色再判一次）。
 * 依据（只读 `app/` 确认）：审批角色为 `ceo` / `super_admin`（`app/approvals.py:15`）；
 * 高权角色集合含 `department_lead` / `ceo` / `super_admin`（`app/domain.py:139`）；
 * 管理类接口一律要求 `super_admin`（如 `app/capabilities.py:48`）。
 * `customer_admin` 是受限客户角色（多处显式排除，如 `app/bootstrap.py:1093`）⇒ 不授予管理能力。
 */
const ROLE_CAPABILITIES: Record<Role, readonly Capability[]> = {
  super_admin: ['agent.manage', 'permission.manage', 'knowledge.manage', 'skill.manage', 'audit.view', 'data.export', 'data.delete'],
  ceo: ['audit.view', 'data.export'],
  department_lead: ['data.export'],
  employee: [],
  customer_admin: [],
}

/** 判断某角色是否具备某能力（`role` 为 `null` = 未登录 ⇒ 一律 false）。 */
export function hasCapability(role: Role | null, capability: Capability): boolean {
  if (!role) return false
  return ROLE_CAPABILITIES[role].includes(capability)
}

/** 角色显示名（`null` = 未登录 ⇒ "未登录"）：避免各处对可空角色做下标。 */
export function roleLabel(role: Role | null): string {
  return role ? ROLE_LABEL[role] : '未登录'
}