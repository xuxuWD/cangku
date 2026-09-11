// 会话持久化的纯函数模块：只做结构校验与读写，方便单测。
// 安全约定：解析失败或结构不合法时一律返回 null 并清理存储（fail-closed），
// 绝不把半截/被篡改的数据当作有效会话使用。

export interface Session {
  accessToken: string
  tenantId: string
  userId: string
  role: string
  expiresAt: number
}

export const SESSION_STORAGE_KEY = 'workbench.companion.session.v1'

function isSessionShaped(value: unknown): value is Session {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.accessToken === 'string' &&
    candidate.accessToken.length > 0 &&
    typeof candidate.tenantId === 'string' &&
    typeof candidate.userId === 'string' &&
    typeof candidate.role === 'string' &&
    typeof candidate.expiresAt === 'number' &&
    Number.isFinite(candidate.expiresAt)
  )
}

export function loadSession(): Session | null {
  if (typeof localStorage === 'undefined') return null
  const raw = localStorage.getItem(SESSION_STORAGE_KEY)
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isSessionShaped(parsed)) {
      clearSession()
      return null
    }
    return parsed
  } catch {
    clearSession()
    return null
  }
}

export function saveSession(value: Session): void {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(value))
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_STORAGE_KEY)
}

export function isSessionExpired(session: Session | null, now: number): boolean {
  if (!session) return true
  return session.expiresAt <= now
}
