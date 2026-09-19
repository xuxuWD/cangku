/**
 * 权限呈现（不是权限校验）：有权限才渲染 children；**没权限时渲染"无权限"态，而不是静默隐藏**。
 *
 * 为什么必须显式呈现：静默隐藏会让人以为"功能不存在"，也掩盖了权限配置错误；
 * 无权限时给出**原因**（缺哪个能力）+ **申请入口占位**（第 2 轮不接后端，点击只回调）。
 *
 * 安全说明：前端判定只负责"看起来对不对"，**真正的权限校验必须在服务端**（后续轮次）。
 * 判定来源是 `src/app/session.tsx` 的本地桩能力表，未接真实会话。
 */
import type { ReactNode } from 'react'
import { Button } from 'antd'
import { ContentState } from './ContentState'
import { CAPABILITY_LABEL, hasCapability, roleLabel, useSession } from '../app/session'
import type { Capability } from '../app/session'

export interface PermissionGuardProps {
  /** 需要的能力（受控枚举，不传任意字符串）。 */
  capability: Capability
  children: ReactNode
  /** 无权限时的原因说明；不传按角色与能力名生成。 */
  reason?: string
  /** 申请入口占位文案，默认"申请权限"。 */
  requestText?: string
  /** 申请入口回调（第 2 轮不接后端）。 */
  onRequestAccess?: () => void
}

export function PermissionGuard({
  capability,
  children,
  reason,
  requestText = '申请权限',
  onRequestAccess,
}: PermissionGuardProps) {
  const role = useSession((state) => state.role)

  if (hasCapability(role, capability)) return <>{children}</>

  return (
    <ContentState
      state="forbidden"
      description={
        reason ??
        `当前角色「${roleLabel(role)}」没有「${CAPABILITY_LABEL[capability]}」权限，如需使用请联系管理员开通。`
      }
      action={
        <Button type="primary" onClick={onRequestAccess}>
          {requestText}
        </Button>
      }
    />
  )
}