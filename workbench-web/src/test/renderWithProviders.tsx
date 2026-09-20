/**
 * 测试包装（第 6 轮 · 接线批 1）：需要 React Query / 会话的用例统一用它渲染。
 *
 * 每次渲染都新建 `QueryClient`（`retry: false`）：用例之间不共享缓存，
 * 避免"上一条用例的缓存让下一条假绿"。
 *
 * 会话：第 6 轮起壳里**没有**"演示用角色切换器"（角色来自服务端登录响应），
 * 用例统一用 `signInAs(role)` 直接写入会话（令牌是测试固定值，**不是**任何真实凭据）。
 */
import type { ReactElement, ReactNode } from 'react'
import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createAppQueryClient } from '../api/queryClient'
import { useSession } from '../app/session'
import type { Role } from '../app/session'

export function Providers({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createAppQueryClient()}>{children}</QueryClientProvider>
}

export function renderWithProviders(ui: ReactElement): RenderResult {
  return render(<Providers>{ui}</Providers>)
}

/**
 * 测试登录：把会话置为"已认证"（令牌 / 角色 / 账号标识均为测试值，不触达网络）。
 * `userId` 默认 `acct-self`：技能域用例需要"提交人 = 自己"的判定（契约 §3 预置禁用自审）。
 */
export function signInAs(role: Role, userId = 'acct-self'): void {
  useSession.getState().signIn({ token: 'test-token', role, userId })
}

/** 测试登出：清会话与 `sessionStorage`，避免用例之间互相污染。 */
export function signOutForTest(): void {
  useSession.getState().signOut()
  sessionStorage.clear()
}