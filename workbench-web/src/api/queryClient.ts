/**
 * React Query 客户端（第 6 轮 · 接线批 1）—— 全应用统一一份配置。
 *
 * - `retry: false`：**不自动重试**。401/403 重试无意义；429 重试会放大限流；
 *   写操作重试可能造成重复提交（幂等由服务端保证，前端不擅自重放）。失败一律交给界面四态。
 * - `refetchOnWindowFocus: false`：批 1 不做聚焦刷新（避免无谓请求与抖动）。
 */
import { QueryClient } from '@tanstack/react-query'

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  })
}