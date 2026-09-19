import { useState } from 'react'
import { ApiError, createSession } from '../approvals/api'
import { saveSession, type Session } from '../../app/session'

interface LoginPageProps {
  onAuthenticated: (session: Session) => void
}

// 服务端把「未填动态码」与「动态码错误」区分成两个**受控 detail**
// （`app/main.py:4774`「需要动态验证码」/ `:4776`「动态验证码不正确」）。
// 必须如实传达：否则用户会把「只是没填码」误当成「密码错了」而反复重试，越试越被限流。
const TOTP_REQUIRED_DETAIL = '需要动态验证码'
const TOTP_WRONG_DETAIL = '动态验证码不正确'

function friendlyLoginError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      if (error.message === TOTP_REQUIRED_DETAIL) {
        return '登录失败：该账号已绑定动态验证码，请填写动态验证码后再登录。'
      }
      if (error.message === TOTP_WRONG_DETAIL) {
        return '登录失败：动态验证码不正确，请重新输入（验证码 30 秒一换）。'
      }
      // 其余 401 与接口契约一致：手机号不存在 / 口令错误 / 未审批统一为这一句（不区分原因，避免泄露账号是否存在）。
      return '登录失败：手机号或密码不正确。'
    }
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
      // 受限会话（`scope === 'totp_enrollment'`，见 `app/auth.py`）：管理员被要求强制绑定动态口令、
      // 尚未绑定时服务端只放行绑定相关接口。**不能把它当登录成功存下来**——那会让后续每个请求
      // 都 403，而用户完全不知道为什么（伴侣端没有绑定入口）⇒ 如实说明去哪儿绑定。
      if (result.scope === 'totp_enrollment') {
        setError('登录失败：该账号需要先绑定动态验证码。请先在网页管理台完成绑定，再回到这里登录。')
        return
      }
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
        <label htmlFor="totp">动态验证码（已绑定的账号必填）</label>
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
