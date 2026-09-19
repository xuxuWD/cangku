import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'

// 直接读文件而不是 `import pkg from './package.json'`：不依赖 tsconfig 的 resolveJsonModule。
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string }

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  // 「关于」里的版本号取 package.json 这一个来源，不在界面里另写常量。
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', css: true, globals: true },
})
