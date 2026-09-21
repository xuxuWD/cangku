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
/**
 * 本人账号标识键（第 8 轮新增）：登录响应里的 `user_id`。
 *
 * 为什么要存：技能域契约 §3 要求「不能审核自己提交的包」在界面上按"提交人 = 自己"**预置禁用 + 给原因**
 * （服务端仍会再判一次 `403`）。此前会话只存令牌与角色，界面无法知道自己是谁。
 * 它只是**呈现用**的不透明标识（非手机号），不进 URL、不进日志。
 */
export const USER_STORAGE_KEY = 'workbench.user'

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

/** 读存下来的本人账号标识（刷新后恢复"是不是自己提交的"判断用）。 */
export function readStoredUserId(): string | null {
  return sessionStore()?.getItem(USER_STORAGE_KEY) ?? null
}

/** 写本地会话（登录成功后调用）。 */
export function persistSession(token: string, role: Role, userId: string): void {
  const store = sessionStore()
  if (!store) return
  store.setItem(TOKEN_STORAGE_KEY, token)
  store.setItem(ROLE_STORAGE_KEY, role)
  store.setItem(USER_STORAGE_KEY, userId)
}

/** 清本地会话（登出 / 401 / 令牌失效）。 */
export function clearStoredSession(): void {
  const store = sessionStore()
  if (!store) return
  store.removeItem(TOKEN_STORAGE_KEY)
  store.removeItem(ROLE_STORAGE_KEY)
  store.removeItem(USER_STORAGE_KEY)
}

export interface SessionState {
  status: 'anonymous' | 'authenticated'
  token: string | null
  role: Role | null
  /** 本人账号标识（服务端登录响应 `user_id`；仅界面呈现用，安全边界在服务端）。 */
  userId: string | null
  /** 顶栏展示名：用角色名（后端未返回展示名，**不编造姓名**）。 */
  displayName: string
  /** 登录成功：令牌已落 sessionStorage。 */
  signIn: (input: { token: string; role: Role; userId: string }) => void
  /** 本地登出（服务端登出由 `authService.logout` 负责）。 */
  signOut: () => void
}

const initialToken = readToken()
const initialRole = readStoredRole()
const initialUserId = readStoredUserId()

export const useSession = create<SessionState>((set) => ({
  status: initialToken ? 'authenticated' : 'anonymous',
  token: initialToken,
  role: initialRole,
  userId: initialUserId,
  displayName: initialRole ? ROLE_LABEL[initialRole] : '',
  signIn: ({ token, role, userId }) => {
    persistSession(token, role, userId)
    set({ status: 'authenticated', token, role, userId, displayName: ROLE_LABEL[role] })
  },
  signOut: () => {
    clearStoredSession()
    set({ status: 'anonymous', token: null, role: null, userId: null, displayName: '' })
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
  | 'knowledge.search'
  | 'knowledge.register'
  | 'knowledge.manage'
  | 'skill.manage'
  | 'skill.submit'
  | 'skill.bind'
  | 'audit.view'
  | 'audit.scope.tenant'
  | 'audit.export'
  | 'data.export'
  | 'data.delete'

/** 能力显示名（用于"无权限"时的原因说明）。 */
export const CAPABILITY_LABEL: Record<Capability, string> = {
  'agent.manage': '数字员工管理',
  'permission.manage': '权限配置',
  'knowledge.search': '知识检索',
  'knowledge.register': '知识文档登记',
  'knowledge.manage': '知识库管理',
  'skill.manage': 'Skill & MCP 管理',
  'skill.submit': 'Skill 包提交',
  'skill.bind': '技能绑定',
  'audit.view': '审计日志查看',
  'audit.scope.tenant': '审计全租户范围',
  'audit.export': '审计日志导出',
  'data.export': '数据导出',
  'data.delete': '数据删除',
}

/**
 * 角色 → 能力（**仅界面呈现**；每个请求都会在服务端按角色再判一次）。
 * 依据（只读 `app/` 确认）：审批角色为 `ceo` / `super_admin`（`app/approvals.py:15`）；
 * 高权角色集合含 `department_lead` / `ceo` / `super_admin`（`app/domain.py:139`）；
 * 管理类接口一律要求 `super_admin`（如 `app/capabilities.py:48`）。
 * `customer_admin` 是受限客户角色（多处显式排除，如 `app/bootstrap.py:1093`）⇒ 不授予管理能力。
 *
 * **2026-09-19 知识域对齐矩阵（P0 修复）**：`permission-matrix.md` §3「知识」四行 ⇒
 * 检索与登记对 `employee` / `department_lead` / `ceo` / `super_admin` 开放（⚠️ 检索按绑定），
 * 发布 / 归档 / 复核 / 治理读（列表·指标·可检索清单）仅 `ceo` + `super_admin`，
 * `customer_admin` 在知识域一律 ❌。后端同一口径见
 * `app/knowledge_governance/models.py` 的 `SEARCH_ROLES` / `REGISTER_ROLES` / `GOVERNANCE_ROLES`。
 */
const ACCESS_ROLES: readonly Role[] = ['employee', 'department_lead', 'ceo', 'super_admin']
const GOVERNANCE_ROLES: readonly Role[] = ['ceo', 'super_admin']
/** 绑定 / 解绑技能：矩阵 §3 **未列**该行 ⇒ 沿用原口径，仅 `super_admin`（第 8 轮 D-026 已裁决不放开）。 */
const BIND_ROLES: readonly Role[] = ['super_admin']
/** 审计「本租户全量」档：矩阵 §3「审计：查询」里 `employee` 只到「仅本人相关」⇒ 不含在内。 */
const AUDIT_TENANT_ROLES: readonly Role[] = ['department_lead', 'ceo', 'super_admin']
/** 审计导出：矩阵 §3「审计：导出」**仅 `super_admin` ✅**（该行其余四列全 ❌）——
 *  注意与查询**不同档**：`ceo` / `department_lead` 能查本租户但**不能导出**。
 *  后端同一口径见 `app/audit/models.py` 的 `AUDIT_EXPORT_ROLES`（第 13 轮）。 */
const AUDIT_EXPORT_ROLES: readonly Role[] = ['super_admin']

/**
 * **2026-09-20 技能域对齐矩阵 §3（第 8 轮）**：`permission-matrix.md` §3「技能」两行 ⇒
 * 提交（自带 Skill 包）对四个角色开放，复核 / 启用 / 停用仅 `ceo` + `super_admin`，
 * `customer_admin` 在技能域一律 ❌（不授予任何能力，导航也不显示入口）。
 * 后端同一口径见 `app/skills/models.py` 的 `SUBMIT_ROLES` / `REVIEW_ROLES`
 * （复核行本轮由 `{super_admin}` 扩为 `{ceo, super_admin}`；**绑定不在此列**，后端仍仅 `super_admin`）。
 *
 * **2026-09-20 审计域对齐矩阵 §3（第 10 轮）**：`audit.view` 对四个业务角色开放
 * （其中 `employee` 是矩阵里的 ⚠️**仅本人相关**档，服务端强制自限），
 * `audit.scope.tenant` = 本租户全量（`department_lead` + `ceo` + `super_admin`），
 * `customer_admin` 在审计域 ❌。后端同一口径见
 * `app/audit/models.py` 的 `AUDIT_READ_ROLES` / `AUDIT_SELF_SCOPED_ROLES` / `resolve_actor_filter`。
 */
const ROLE_CAPABILITIES: Record<Role, readonly Capability[]> = {
  super_admin: [
    'agent.manage',
    'permission.manage',
    'knowledge.search',
    'knowledge.register',
    'knowledge.manage',
    'skill.manage',
    'skill.submit',
    'skill.bind',
    'audit.view',
    'audit.scope.tenant',
    'audit.export',
    'data.export',
    'data.delete',
  ],
  ceo: [
    'knowledge.search',
    'knowledge.register',
    'knowledge.manage',
    'skill.manage',
    'skill.submit',
    'audit.view',
    'audit.scope.tenant',
    'data.export',
  ],
  department_lead: [
    'knowledge.search',
    'knowledge.register',
    'skill.submit',
    'audit.view',
    'audit.scope.tenant',
    'data.export',
  ],
  employee: ['knowledge.search', 'knowledge.register', 'skill.submit', 'audit.view'],
  customer_admin: [],
}

/** 角色是否具备某能力（`role` 为 `null` = 未登录 ⇒ 一律 false）。 */
export function hasCapability(role: Role | null, capability: Capability): boolean {
  if (!role) return false
  return ROLE_CAPABILITIES[role].includes(capability)
}

/** 具备某能力的全部角色（给"哪些角色能用"这类说明文案用；顺序即展示顺序）。 */
export const CAPABILITY_ROLES: Partial<Record<Capability, readonly Role[]>> = {
  'knowledge.search': ACCESS_ROLES,
  'knowledge.register': ACCESS_ROLES,
  'knowledge.manage': GOVERNANCE_ROLES,
  'skill.submit': ACCESS_ROLES,
  'skill.manage': GOVERNANCE_ROLES,
  'skill.bind': BIND_ROLES,
  'audit.view': ACCESS_ROLES,
  'audit.scope.tenant': AUDIT_TENANT_ROLES,
  'audit.export': AUDIT_EXPORT_ROLES,
}

/** 角色显示名（`null` = 未登录 ⇒ "未登录"）：避免各处对可空角色做下标。 */
export function roleLabel(role: Role | null): string {
  return role ? ROLE_LABEL[role] : '未登录'
}