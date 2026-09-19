/**
 * 会话 / 角色上下文 —— **第 1 轮为本地桩（mock）**。
 *
 * 说明：这里不做登录、不发请求、不读 Cookie / Token，角色只存在于内存，
 * 顶栏右上角可切换角色是为了演示"导航按角色自适应"。
 * 接真实会话（登录态、服务端下发的角色与权限）属后续轮次；
 * 前端隐藏入口只是界面自适应，**真正的权限校验必须在服务端**。
 */
import { create } from 'zustand'

/** 角色取值（第 1 轮只这两种）。 */
export type Role = 'employee' | 'super_admin'

/** 角色显示名。 */
export const ROLE_LABEL: Record<Role, string> = {
  employee: '员工',
  super_admin: '超级管理员',
}

/** 角色切换器选项（开发期演示用，接真实会话后移除）。 */
export const ROLE_OPTIONS: { label: string; value: Role }[] = [
  { label: ROLE_LABEL.employee, value: 'employee' },
  { label: ROLE_LABEL.super_admin, value: 'super_admin' },
]

interface SessionState {
  /** 当前角色：第 1 轮固定初始为员工。 */
  role: Role
  /** 演示账号显示名（不含任何真实用户 ID / 租户 ID）。 */
  displayName: string
  setRole: (role: Role) => void
}

export const useSession = create<SessionState>((set) => ({
  role: 'employee',
  displayName: '演示账号',
  setRole: (role) => set({ role }),
}))