import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 开发期把 `/api` 代理到本机后端：前端与后端**同源**，绕开后端 fail-closed 的 CORS
    // （空配置 = 不允许跨源；开发模式仅放行 localhost）。生产期由反代做同样的事。
    // 目标**可外置**（`VITE_DEV_PROXY_TARGET`，不设时用下方默认值）：本机 8000 常被别的服务占用，
    // 硬编码会让 `npm run dev` 静默把请求发到**错误的后端**，排查成本很高。
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    globals: true,
    // 单条用例默认 5s：AntD 全页渲染 + 多次 userEvent 交互本身就要数秒，
    // 全量并行跑时 CPU 争抢会让它**假红**（2026-09-19 实测：注册中心页 12 条用例
    // 单独跑 29s 全绿，并行跑时 6 条撞 5s 上限）。放宽到 15s 只改"等待上限"，
    // 不改任何断言口径；真卡住的用例仍会失败，只是晚 10 秒。
    testTimeout: 15000,
  },
})