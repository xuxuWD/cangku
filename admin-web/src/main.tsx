import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './app/App'
// 样式分层（UI v2 规格 §4）：令牌 → 基础 → 旧页面 → 组件 → 外壳 → 新页面。
// 顺序即层叠顺序：新层可以覆盖 legacy 层里同名选择器。
import './styles/tokens.css'
import './styles/base.css'
import './styles/legacy.css'
import './styles/ui.css'
import './styles/shell.css'
import './styles/pages.css'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
