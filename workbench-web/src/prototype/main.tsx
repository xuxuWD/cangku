/**
 * B3 形态原型的入口。
 *
 * ⚠️ **这是原型，不是交付物**：
 *  - 只搭 B3 的**形态**（三栏 / 对话常驻 / 右栏 / 悬浮助手 / 自建路由 / 侧栏收敛）；
 *  - **不接后端**（消息与待办都是样例）、**不改 `admin-web`**、**不动现有 `AppShell`**；
 *  - 因此现有 439 条用例不受影响；本原型**不进生产包**（`vite build` 只打 `index.html`）。
 *
 * 打开方式：`npm run dev` 后访问 **`/prototype.html`**（带 query 试直达，例如
 * `/prototype.html?view=workitems&object=task-1&panel=employee`）。
 */
// React 19 兼容补丁：与 `src/main.tsx` 同一口径，**必须在任何 antd 模块之前**引入。
// （2026-09-23 真机走查抓到：漏了它，控制台会出 `[antd: compatible]` 警告 —— 原型也不该带这种噪音。）
import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { PrototypeApp } from './PrototypeApp'
import '../styles/global.css'

const container = document.getElementById('root')
if (!container) throw new Error('找不到挂载点 #root')

createRoot(container).render(
  <StrictMode>
    <PrototypeApp />
  </StrictMode>,
)
