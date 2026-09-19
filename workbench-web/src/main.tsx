// React 19 兼容补丁：React 19 移除了 react-dom 的旧渲染入口，导致 AntD 5 的静态 API
// （message / notification / Modal.confirm 等）失效。按 AntD 官方要求，必须在**任何 antd 模块之前**
// 引入这个补丁；它只做运行时打补丁，不改变任何业务行为。
import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppShell } from './app/AppShell'
import './styles/global.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
)