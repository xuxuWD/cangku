import { useState } from 'react'
import { ApiError, createSession } from '../approvals/api'
import { saveSession, type Session } from '../../app/session'

interface LoginPageProps {
  onAuthenticated: (session: Session) => void
}

function friendlyLoginError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return '登录失败：手机号、密码或动态验证码不正确。'
    if (error.status === 429) return '登录尝试过于频繁，请稍后再试。'
    if (error.status === 503) return '服务暂未配置会话密钥，请联系管理员。'
    return error.message
  }
  return '网络异常，请检查网络后重新尝试。'
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await createSession(phone, password, totpCode || undefined)
      const session: Session = {
        accessToken: result.access_token,
        tenantId: result.tenant_id,
        userId: result.user_id,
        role: result.role,
        expiresAt: Date.now() + result.expires_in * 1000,
      }
      saveSession(session)
      onAuthenticated(session)
    } catch (err) {
      setError(friendlyLoginError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login">
      <h1 className="login__title">工作台伴侣端</h1>
      <p className="login__subtitle">审批与提醒</p>
      <form className="login__form" onSubmit={handleSubmit}>
        <label htmlFor="phone">手机号</label>
        <input
          id="phone"
          name="phone"
          type="tel"
          inputMode="numeric"
          autoComplete="username"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          required
        />
        <label htmlFor="password">密码</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        <label htmlFor="totp">动态验证码（如已绑定）</label>
        <input
          id="totp"
          name="totp"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={totpCode}
          onChange={(event) => setTotpCode(event.target.value)}
        />
        {error ? (
          <p className="login__error" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={submitting}>
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
    </main>
  )
}
