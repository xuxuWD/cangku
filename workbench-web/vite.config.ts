import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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