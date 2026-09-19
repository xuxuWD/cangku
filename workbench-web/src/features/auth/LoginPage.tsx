/**
 * 登录页（第 6 轮 · 接线批 1）。
 *
 * - 表单字段与后端 `SessionCreate` 对齐：账号（**手机号**）+ 密码 + 动态验证码（可选）；
 *   **表单里没有任何硬编码账号 / 密码 / 租户**，也不预填任何值。
 * - 失败按状态给文案：401（密码错 / 需要或输错动态验证码）、429（限流）、503（后端未配会话密钥）、
 *   网络失败（服务不可达）——文案来自统一请求层，**不含堆栈 / SQL / 内部路径**。
 * - 前端只做"长度与必填"的易用性校验；**认证与授权一律以服务端判定为准**。
 *
 * `externalNotice`（第 6 轮 · 接线批 1 收口补）：由壳层传入的**跨页面**提示，当前唯一来源是
 * 「退出登录时服务端会话撤销失败」。这类提示必须渲染在**登录页**上 —— 它产生的同一刻壳层就切到了
 * 登录页（2026-09-19 真机走查发现：原实现渲染在已登录分支 ⇒ 用户永远看不到，等于没告知）。
 */
import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd'
import { ApiError } from '../../api/client'
import { useSession } from '../../app/session'
import { tokens } from '../../theme/tokens'
import { TOTP_ENROLLMENT_SCOPE, login } from './services/authService'

interface LoginFormValues {
  phone: string
  password: string
  totp_code?: string
}

/** 后端要求 / 校验动态验证码时的提示（对应 `app/main.py:4813-4816` 的两条 401 detail）。 */
const TOTP_HINT = '该账号已启用动态验证码：请填写认证器上的 6 位验证码后重试。'

export function LoginPage({ externalNotice = null }: { externalNotice?: string | null } = {}) {
  const signIn = useSession((state) => state.signIn)
  const [form] = Form.useForm<LoginFormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [totpHint, setTotpHint] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const handleFinish = async (values: LoginFormValues) => {
    setSubmitting(true)
    setError(null)
    setNotice(null)
    try {
      const session = await login({
        phone: values.phone.trim(),
        password: values.password,
        totp_code: values.totp_code?.trim() || undefined,
      })
      signIn({ token: session.access_token, role: session.role })
      if (session.scope === TOTP_ENROLLMENT_SCOPE) {
        // 如实告知：受限会话（动态验证码登记中），不能假装是完整会话
        setNotice('当前为动态验证码登记会话，可用范围受限；完成登记后请重新登录。')
      }
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : '登录失败，请稍后重试。'
      setError(message)
      setTotpHint(caught instanceof ApiError && caught.status === 401 && message.includes('动态验证码'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: tokens.color.contentBg,
        padding: tokens.spacing.lg,
      }}
    >
      <Card style={{ width: 420 }}>
        <Space direction="vertical" size={tokens.spacing.md} style={{ width: '100%' }}>
          <Typography.Title level={2} style={{ marginBottom: 0 }}>
            公司数字员工工作台
          </Typography.Title>
          <Typography.Text type="secondary">
            请使用管理员发放的账号登录（账号为手机号）。账号与权限由服务端校验，界面提示仅为易用性。
          </Typography.Text>

          {error && <Alert type="error" showIcon message={error} />}
          {externalNotice && <Alert type="warning" showIcon message={externalNotice} />}
          {totpHint && !error && <Alert type="warning" showIcon message={TOTP_HINT} />}
          {notice && <Alert type="info" showIcon message={notice} />}

          <Form<LoginFormValues> form={form} layout="vertical" onFinish={handleFinish} disabled={submitting}>
            <Form.Item
              label="账号（手机号）"
              name="phone"
              rules={[{ required: true, message: '请输入账号' }, { max: 20, message: '账号最长 20 位' }]}
            >
              <Input autoComplete="username" maxLength={20} placeholder="请输入手机号" />
            </Form.Item>

            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }, { max: 128, message: '密码最长 128 位' }]}
            >
              <Input.Password autoComplete="current-password" maxLength={128} placeholder="请输入密码" />
            </Form.Item>

            <Form.Item label="动态验证码（如已启用）" name="totp_code" rules={[{ max: 20, message: '验证码最长 20 位' }]}>
              <Input autoComplete="one-time-code" maxLength={20} placeholder="6 位动态验证码，未启用可留空" />
            </Form.Item>

            <Button type="primary" htmlType="submit" block loading={submitting}>
              登录
            </Button>
          </Form>
        </Space>
      </Card>
    </div>
  )
}